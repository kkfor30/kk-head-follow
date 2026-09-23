#!/usr/bin/env python3
"""Probe a video and produce deterministic local-motion segments for head-follow assets."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


def fail(message: str) -> None:
    raise SystemExit(f"[kk-head-follow] {message}")


def run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        fail(f"required command not found: {exc.filename}")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        fail(f"command failed: {' '.join(command)}\n{detail[-1200:]}")
    return result.stdout


def probe(video: Path) -> dict[str, Any]:
    raw = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames,duration,avg_frame_rate",
            "-of",
            "json",
            str(video),
        ]
    )
    data = json.loads(raw)
    streams = data.get("streams") or []
    if not streams:
        fail("video has no video stream")
    stream = streams[0]

    def ratio(value: str | None) -> float | None:
        if not value or value in {"0/0", "N/A"}:
            return None
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator)

    fps = ratio(stream.get("avg_frame_rate")) or ratio(stream.get("r_frame_rate"))
    duration = float(stream.get("duration") or 0)
    frames = stream.get("nb_frames")
    frame_count = int(frames) if frames and str(frames).isdigit() else round(duration * (fps or 0))
    return {
        "path": str(video),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": fps,
        "duration": duration,
        "frameCount": frame_count,
    }


def crop_box(values: list[int], width: int, height: int) -> tuple[int, int, int, int]:
    if len(values) != 4:
        fail("--crop requires x y width height")
    x, y, crop_width, crop_height = values
    if crop_width <= 0 or crop_height <= 0 or x < 0 or y < 0:
        fail("crop must be positive and non-negative")
    if x + crop_width > width or y + crop_height > height:
        fail("crop exceeds source video bounds")
    return x, y, crop_width, crop_height


def extract_samples(video: Path, directory: Path, sample_fps: float) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={sample_fps:g}",
            "-vsync",
            "0",
            "-q:v",
            "2",
            str(directory / "%06d.png"),
            "-y",
        ]
    )
    samples = sorted(directory.glob("*.png"))
    if len(samples) < 2:
        fail("video produced fewer than two analysis samples")
    return samples


def image_signal(path: Path, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, width, height = box
    with Image.open(path) as image:
        gray = image.convert("L").crop((x, y, x + width, y + height))
        gray.thumbnail((160, 160), Image.Resampling.BILINEAR)
        return np.asarray(gray, dtype=np.float32)


def motion_scores(samples: list[Path], box: tuple[int, int, int, int]) -> list[float]:
    previous = image_signal(samples[0], box)
    scores = [0.0]
    for path in samples[1:]:
        current = image_signal(path, box)
        if current.shape != previous.shape:
            current = np.asarray(Image.fromarray(current.astype(np.uint8)).resize((previous.shape[1], previous.shape[0])))
        scores.append(float(np.mean(np.abs(current - previous))))
        previous = current
    return scores


def write_contact_sheet(
    samples: list[Path], box: tuple[int, int, int, int], scores: list[float],
    sample_fps: float, output: Path,
) -> None:
    """Write a deterministic ROI-only review sheet with sample times and motion scores."""
    columns = 6
    cell_width, image_height, label_height = 148, 132, 34
    rows = math.ceil(len(samples) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * (image_height + label_height)), "#f3f1ec")
    draw = ImageDraw.Draw(sheet)
    x, y, width, height = box
    for index, path in enumerate(samples):
        with Image.open(path) as source:
            image = source.convert("RGB").crop((x, y, x + width, y + height))
        image.thumbnail((cell_width - 8, image_height - 8), Image.Resampling.LANCZOS)
        col, row = index % columns, index // columns
        left, top = col * cell_width, row * (image_height + label_height)
        sheet.paste(image, (left + (cell_width - image.width) // 2, top + (image_height - image.height) // 2))
        draw.text((left + 4, top + image_height + 2), f"{index / sample_fps:.2f}s  m={scores[index]:.1f}", fill="#222222")
    sheet.save(output, quality=88, optimize=True)


def rolling_median(values: list[float], radius: int) -> list[float]:
    result: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        result.append(float(median(values[start:end])))
    return result


def segments(
    scores: list[float],
    sample_fps: float,
    threshold: float,
    min_duration: float,
    gap_duration: float,
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    active = [score >= threshold for score in scores]
    max_gap = max(0, math.ceil(gap_duration * sample_fps))
    gap = 0
    start: int | None = None
    # Flush a trailing active segment even when short inactive gaps are allowed.
    for index, is_active in enumerate(active + [False] * (max_gap + 1)):
        if is_active:
            if start is None:
                start = index
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap <= max_gap:
            continue
        end = index - gap
        if (end - start + 1) / sample_fps >= min_duration:
            found.append(
                {
                    "startSample": start,
                    "endSample": end,
                    "startTime": round(start / sample_fps, 4),
                    "endTime": round((end + 1) / sample_fps, 4),
                    "sampleCount": end - start + 1,
                    "maxMotionScore": round(max(scores[start : end + 1]), 4),
                    "suggestedRole": "active-motion",
                }
            )
        start = None
        gap = 0
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect local head motion segments in a source video")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--crop", type=int, nargs=4, required=True, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--output", type=Path, default=Path("build/head-motion"))
    parser.add_argument("--sample-fps", type=float, default=12)
    parser.add_argument("--threshold", type=float, default=2.0, help="absolute mean grayscale delta (default: 2.0; calibrated for local ROI probe)")
    parser.add_argument("--min-duration", type=float, default=0.25)
    parser.add_argument("--gap-duration", type=float, default=0.15)
    parser.add_argument("--keep-samples", action="store_true")
    args = parser.parse_args()

    video = args.video.resolve()
    if not video.is_file():
        fail(f"video not found: {video}")
    if args.sample_fps <= 0:
        fail("--sample-fps must be positive")

    info = probe(video)
    box = crop_box(args.crop, info["width"], info["height"])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="kk-head-follow-"))
    try:
        samples = extract_samples(video, temp_root / "samples", args.sample_fps)
        raw_scores = motion_scores(samples, box)
        filtered = rolling_median(raw_scores, max(1, round(args.sample_fps * 0.08)))
        threshold = args.threshold
        found = segments(filtered, args.sample_fps, threshold, args.min_duration, args.gap_duration)
        contact_sheet = output / "contact-sheet.jpg"
        write_contact_sheet(samples, box, filtered, args.sample_fps, contact_sheet)

        (output / "video-info.json").write_text(
            json.dumps({**info, "crop": {"x": box[0], "y": box[1], "width": box[2], "height": box[3]}, "sampleFps": args.sample_fps}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output / "motion-segments.json").write_text(
            json.dumps({
                "threshold": round(threshold, 4),
                "thresholdMethod": "fixed-mean-grayscale-delta",
                "maxMotionScore": round(max(filtered), 4),
                "hasMotion": bool(found),
                "segments": found,
                "directionLabelsRequired": True,
                "contactSheet": contact_sheet.name,
                "scores": [round(value, 4) for value in filtered],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if args.keep_samples:
            shutil.copytree(temp_root / "samples", output / "samples", dirs_exist_ok=True)
        print(json.dumps({"video": str(video), "samples": len(samples), "segments": len(found), "threshold": round(threshold, 4), "hasMotion": bool(found), "contactSheet": str(contact_sheet), "output": str(output)}, ensure_ascii=False))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
