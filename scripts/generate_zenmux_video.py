#!/usr/bin/env python3
"""Generate a head-follow source video through ZenMux's native video API."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from zenmux_config import configured_api_key
from submission_budget import reserve, write_atomic, submission_preflight
from generation_plan import validate_plan
from generation_controls import (request_options, validate_requirements, review_template,
                                 validate_review, provider_observation, archive_inputs, PROFILE_DATE)

DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"
DEFAULT_MODEL = "minimax/minimax-h3-max"
DEFAULT_RESOLUTION = "768p"
MAX_PROMPT_CHARACTERS = 7000
TERMINAL_STATES = {"succeeded", "failed", "cancelled", "canceled"}
COMMON_RATIOS = {
    "21:9": 21 / 9,
    "16:9": 16 / 9,
    "4:3": 4 / 3,
    "1:1": 1.0,
    "3:4": 3 / 4,
    "9:16": 9 / 16,
}


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def fail(message: str) -> None:
    raise SystemExit(f"[kk-head-follow] {message}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"spec not found: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    if not isinstance(value, dict):
        fail("spec root must be an object")
    return value


def local_media_uri(value: str, base_dir: Path) -> str:
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(value)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    if not path.is_file():
        fail(f"media file not found: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def infer_ratio(value: str | None, base_dir: Path) -> str:
    if not value:
        return "1:1"
    if value.startswith(("http://", "https://", "data:")):
        return "1:1"
    path = Path(value)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    if not path.is_file():
        fail(f"reference image not found: {path}")
    with Image.open(path) as image:
        actual = image.width / image.height
    return min(COMMON_RATIOS, key=lambda name: abs(COMMON_RATIOS[name] - actual))


def build_content(spec: dict[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    prompt = spec.get("prompt")
    if spec.get("prompt_file"):
        prompt_path = Path(str(spec["prompt_file"]))
        if not prompt_path.is_absolute():
            prompt_path = (base_dir / prompt_path).resolve()
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            fail(f"prompt file not found: {prompt_path}")
    if not isinstance(prompt, str) or not prompt.strip():
        fail("provide a non-empty spec.prompt or spec.prompt_file")
    prompt = prompt.strip()
    prompt_length = len(prompt)
    if prompt_length > MAX_PROMPT_CHARACTERS:
        fail(
            f"视频提示词为 {prompt_length} characters，超过 ZenMux 规范上限 "
            f"{MAX_PROMPT_CHARACTERS}；请精简后再提交"
        )
    content.append({"type": "text", "text": prompt})

    media_fields = (
        ("first_frame", "image_url", "first_frame"),
        ("last_frame", "image_url", "last_frame"),
        ("reference_image", "image_url", "reference_image"),
        ("reference_video", "video_url", "reference_video"),
        ("reference_audio", "audio_url", "reference_audio"),
    )
    first_frame = spec.get("first_frame")
    last_frame = spec.get("last_frame")
    if spec.get("loop_frame"):
        if not first_frame:
            fail("loop_frame requires first_frame")
        if last_frame:
            fail("loop_frame and last_frame cannot be used together")
        last_frame = first_frame
    if last_frame and not first_frame:
        fail("last_frame requires first_frame")
    reference_mode = any(spec.get(k) for k in ('reference_image', 'reference_images', 'reference_video',
                                              'reference_videos', 'reference_audio', 'reference_audios'))
    frame_mode = bool(first_frame or last_frame)
    if reference_mode and frame_mode:
        fail("reference image/video/audio is mutually exclusive with first_frame/last_frame")

    for field, content_type, role in media_fields:
        value = spec.get(field)
        if field == "last_frame":
            value = last_frame
        if value:
            content.append(
                {
                    "type": content_type,
                    "role": role,
                    content_type: {"url": local_media_uri(str(value), base_dir)},
                }
            )
    for key, role, kind in [('reference_images','reference_image','image_url'),
                            ('reference_videos','reference_video','video_url'),
                            ('reference_audios','reference_audio','audio_url')]:
        references = spec.get(key, [])
        if not isinstance(references, list):
            fail(f'{key} must be an array')
        for reference in references:
            content.append({'type':kind, 'role':role, kind:{'url':local_media_uri(str(reference),base_dir)}})
    return content


def request_json(
    url: str,
    method: str,
    api_key: str,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"ZenMux HTTP {exc.code}: {detail[:1000]}")
    except urllib.error.URLError as exc:
        fail(f"ZenMux request failed: {exc.reason}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        fail("ZenMux returned non-JSON data")
    if not isinstance(value, dict):
        fail("ZenMux response root must be an object")
    return value


def download(url: str, destination: Path, timeout: int = 300) -> None:
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            destination.write_bytes(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        fail(f"result download failed: {exc}")


def result_urls(response: dict[str, Any]) -> tuple[str | None, str | None]:
    content = response.get("content")
    if isinstance(content, list):
        content = next((item for item in content if isinstance(item, dict)), {})
    if not isinstance(content, dict):
        content = {}
    video_url = content.get("video_url")
    last_frame_url = content.get("last_frame_url")
    return (
        video_url if isinstance(video_url, str) else None,
        last_frame_url if isinstance(last_frame_url, str) else None,
    )


def write_job(path: Path, response: dict[str, Any], output_dir: Path) -> None:
    safe = {
        "id": response.get("id"),
        "status": response.get("status"),
        "model": response.get("model"),
        "outputDir": str(output_dir),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    write_atomic(path, safe)
    observation_path = output_dir / 'provider-observation.json'
    previous = load_json(observation_path) if observation_path.exists() else None
    write_atomic(observation_path, provider_observation(response, previous))


def prepare_request(spec, base_dir, require_review=True):
    content = build_content(spec, base_dir)
    checked_plan = validate_plan(spec, content, base_dir, require_evidence=require_review)
    warnings = validate_requirements(spec['motionPlan'], content)
    references = spec.get('reference_images') or []
    reference = spec.get('first_frame') or spec.get('reference_image') or (references[0] if references else None)
    ratio = spec.get('ratio') or infer_ratio(reference, base_dir)
    if ratio not in COMMON_RATIOS:
        raise ValueError(f'ratio must be one of {tuple(COMMON_RATIOS)}')
    body = request_options(spec, content, ratio)
    if len(json.dumps(body).encode('utf-8')) > 64 * 1024**2:
        raise ValueError('encoded request exceeds 64 MB')
    review = validate_review(base_dir/spec['motionPlan']['evidence'], body, spec['motionPlan']) if require_review else None
    if any(i.get('role') in ('first_frame','last_frame') for i in content):
        warnings.append('image-to-video uses image aspect ratio; requested ratio is not an image resize operation')
    return body, checked_plan, dict(profileDate=PROFILE_DATE, provider='zenmux', inputReview=review,
        requestedExpansion=body.get('extra',{}).get('prompt_expansion_mode','not-profiled'),
        effectivePrompt='unknown-until-provider-returns-it', warnings=warnings,
        liveAdapterValidation='not-proven-by-offline-checks')


def main() -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="Generate a head-follow source video with ZenMux")
    parser.add_argument("--spec", type=Path, help="JSON generation spec")
    parser.add_argument("--output-dir", type=Path, default=Path("build/zenmux-head"))
    parser.add_argument("--api-key-env", default="ZENMUX_API_KEY")
    parser.add_argument("--base-url", default=os.environ.get("ZENMUX_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--job-id", help="Resume polling an existing ZenMux job")
    parser.add_argument("--budget", type=Path, help="Explicit submission-count budget JSON; required for a new POST")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the request without sending it")
    parser.add_argument('--write-input-review', type=Path, help='Write an unreviewed input template; no network or budget')
    parser.add_argument('--identity', type=Path, help='Original identity baseline for the input review template')
    args = parser.parse_args()

    if not args.spec and not args.job_id:
        fail("--spec is required unless --job-id is supplied")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    body: dict[str, Any] | None = None
    if args.write_input_review and (args.job_id or args.dry_run or not args.spec or not args.identity):
        fail('--write-input-review needs --spec and --identity, and cannot combine with resume/dry-run')
    if args.spec and not args.job_id:
        spec_path = args.spec.resolve()
        spec = load_json(spec_path)
        try:
            body, checked_plan, controls = prepare_request(spec, spec_path.parent, not args.write_input_review)
            if args.write_input_review:
                target = args.write_input_review.resolve()
                if target != (spec_path.parent/spec['motionPlan']['evidence']).resolve():
                    raise ValueError('review output must equal motionPlan.evidence resolved relative to spec')
                if target.exists():
                    raise ValueError('review already exists; preserve observations and write a new review path')
                template = review_template(spec, body, spec_path.parent, args.identity, target)
                target.parent.mkdir(parents=True, exist_ok=True)
                write_atomic(target, template)
                print(json.dumps(dict(inputReview=str(target), status='unreviewed'), ensure_ascii=False))
                return 0
        except (ValueError, OSError, KeyError) as exc:
            fail(str(exc))

    if args.dry_run:
        if body is None:
            fail("--dry-run requires --spec")
        try:
            budget = load_json(args.budget.resolve()) if args.budget else dict(schemaVersion=1,
                purpose='Offline default pilot preview',maxSubmissions=1, attempts=[])
            cost_preview,stage_preview = submission_preflight(budget,output_dir,body,spec.get('production'),spec_path.parent,
                                        args.budget.resolve().parent if args.budget else spec_path.parent)
        except (ValueError, KeyError, OSError) as exc:
            fail(str(exc))
        preview = json.loads(json.dumps(body))
        for item in preview['content']:
            for field in ('image_url', 'video_url', 'audio_url'):
                if field in item:
                    item[field]['url'] = '[media omitted; validated locally]'
        print(json.dumps({"url": f"{args.base_url.rstrip('/')}/videos", "body": preview,
                          "motionPlan": checked_plan if not args.job_id else None,
                          "costLimits": cost_preview, "production": stage_preview,
                          "generationControls": controls}, ensure_ascii=False, indent=2))
        return 0

    if args.api_key_env == "ZENMUX_API_KEY":
        api_key, _ = configured_api_key()
    else:
        api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        print(f"未检测到 ZenMux API Key：{args.api_key_env}", file=sys.stderr)
        print("请先在 ZenMux 控制台的 Subscription 或 Pay As You Go → API Keys 页面创建 Key。", file=sys.stderr)
        print(f'当前 PowerShell 会话：$env:{args.api_key_env} = "<your-key>"', file=sys.stderr)
        print(f'当前用户永久配置：[Environment]::SetEnvironmentVariable("{args.api_key_env}", "<your-key>", "User")', file=sys.stderr)
        print("也可用隐藏输入保存到 kk-head-follow 本地配置：python scripts/zenmux_config.py set", file=sys.stderr)
        print("官方说明：https://zenmux.ai/docs/guide/quickstart", file=sys.stderr)
        return 2

    if args.job_id:
        job_id = args.job_id
        existing_path = output_dir / 'job.json'
        if existing_path.exists() and load_json(existing_path).get('id') != job_id:
            fail('output directory belongs to a different job')
        response = request_json(f"{args.base_url.rstrip('/')}/videos/{job_id}", "GET", api_key)
    else:
        if not args.budget:
            fail('new submissions require --budget; use --job-id to resume an existing job')
        try:
            reservation = reserve(args.budget, output_dir, body, spec.get('production'), spec_path.parent)
            input_archive = archive_inputs(output_dir,body,spec_path.parent/spec['motionPlan']['evidence'],
                                           controls['inputReview']['inputReviewSha256'])
        except (ValueError, KeyError, OSError) as exc:
            fail(str(exc))
        # Save the real prompt and content hashes, never local credentials or signed URLs.
        import hashlib
        audit_content=[]
        for item in body['content']:
            if item['type']=='text':
                audit_content.append(item)
            else:
                value=item[item['type']]['url']
                audit_content.append(dict(type=item['type'],role=item.get('role'),
                                          mediaSha256=hashlib.sha256(value.encode('utf-8')).hexdigest()))
        write_atomic(output_dir/'request-audit.json',dict(motionPlan=checked_plan,
                     request={**body,'content':audit_content},generationControls=controls,inputArchive=input_archive,
                     promptValidation='submitted-prompt-not-necessarily-effective-model-prompt'))
        response = request_json(f"{args.base_url.rstrip('/')}/videos", "POST", api_key, body)
        job_id = response.get("id")
        if not isinstance(job_id, str) or not job_id:
            fail("ZenMux submit response did not contain an id")
        write_atomic(output_dir / 'submission.json', {**reservation, 'state': 'submitted', 'id': job_id})
    job_path = output_dir / "job.json"
    write_job(job_path, response, output_dir)
    deadline = time.monotonic() + args.timeout_seconds

    while response.get("status") not in TERMINAL_STATES:
        if time.monotonic() >= deadline:
            fail(f"poll timeout; job id preserved in {job_path}: {job_id}")
        time.sleep(max(1, args.poll_seconds))
        response = request_json(f"{args.base_url.rstrip('/')}/videos/{job_id}", "GET", api_key)
        write_job(job_path, response, output_dir)

    if response.get("status") != "succeeded":
        error = response.get("error")
        fail(f"ZenMux job failed: {json.dumps(error, ensure_ascii=False)}")

    video_url, last_frame_url = result_urls(response)
    if not video_url:
        fail("successful ZenMux response did not contain content.video_url")
    download(video_url, output_dir / "result.mp4")
    if last_frame_url:
        suffix = Path(urllib.parse.urlparse(last_frame_url).path).suffix or ".jpg"
        download(last_frame_url, output_dir / f"last-frame{suffix}")
    print(json.dumps({"status": "succeeded", "jobId": job_id, "outputDir": str(output_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
