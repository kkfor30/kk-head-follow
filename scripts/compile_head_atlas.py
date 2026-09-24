#!/usr/bin/env python3
"""Compile a scene-bound head-follow atlas from video outputs.

The script performs deterministic extraction and assembly only. It does not
invent poses, interpolate faces, or blend facial frames.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import tempfile
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops


def frames(video: Path, size: tuple[int, int], step: int = 1) -> list[np.ndarray]:
    width, height = size
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(video)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(probe.stdout).get("streams") or []
    if not streams:
        raise ValueError(f"video has no video stream: {video}")
    input_width, input_height = int(streams[0]["width"]), int(streams[0]["height"])
    if abs(input_width / input_height - width / height) > 0.005:
        raise ValueError(
            f"video aspect ratio {input_width}:{input_height} does not match renderSize {width}:{height}; "
            "refusing to stretch face/character geometry"
        )
    with tempfile.TemporaryDirectory() as folder:
        pattern = str(Path(folder) / "%06d.png")
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={width}:{height}:flags=lanczos", pattern], check=True)
        paths = sorted(Path(folder).glob("*.png"))[::step]
        return [np.asarray(Image.open(path).convert("RGBA")) for path in paths]


def edge_connected(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    queue = deque([(row, col) for row in range(height) for col in (0, width - 1)])
    queue.extend((row, col) for col in range(width) for row in (0, height - 1))
    while queue:
        row, col = queue.popleft()
        if row < 0 or row >= height or col < 0 or col >= width or seen[row, col] or not mask[row, col]:
            continue
        seen[row, col] = True
        queue.extend(((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)))
    return seen


def parse_key_color(value: str) -> tuple[int, int, int]:
    normalized = value.removeprefix("#")
    if len(normalized) == 3:
        normalized = "".join(character * 2 for character in normalized)
    if len(normalized) != 6:
        raise ValueError("keyColor must be 'auto' or a six-digit hex color")
    try:
        return tuple(int(normalized[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError as error:
        raise ValueError("keyColor must be 'auto' or a six-digit hex color") from error


def sample_border_key(frame: np.ndarray) -> tuple[int, int, int]:
    rgb = frame[:, :, :3]
    band = max(1, min(rgb.shape[0], rgb.shape[1], 6))
    border = np.concatenate((rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3),
                             rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3)))
    return tuple(int(statistics.median(border[:, channel].tolist())) for channel in range(3))


def key_channels(key: tuple[int, int, int]) -> list[int]:
    strongest = max(key)
    if strongest < 128:
        return []
    return [index for index, value in enumerate(key) if value >= strongest - 16 and value >= 128]


def patch_with_background(frame: np.ndarray, base: np.ndarray, mode: str,
                          key: tuple[int, int, int] | None = None,
                          transparent_threshold: int = 12,
                          opaque_threshold: int = 220) -> Image.Image:
    source_alpha = frame[:, :, 3] if frame.shape[2] == 4 else None
    rgb_frame = frame[:, :, :3]
    if mode in {"replace-edge-light", "fit-edge-light"}:
        eligible = (rgb_frame.min(axis=2) > 210) & (np.ptp(rgb_frame.astype(float), axis=2) < 30)
        connected = edge_connected(eligible)
        rgb_frame = rgb_frame.copy()
        rgb_frame[connected] = base[connected]
    image = Image.fromarray(rgb_frame).convert("RGBA")
    if source_alpha is not None:
        image.putalpha(Image.fromarray(source_alpha))
    if mode == "chroma-key":
        if key is None:
            raise ValueError("chroma-key mode requires keyColor")
        rgb = rgb_frame.astype(np.int16)
        key_rgb = np.asarray(key, dtype=np.int16)
        distance = np.max(np.abs(rgb - key_rgb), axis=2).astype(np.float32)
        ratio = np.clip((distance - transparent_threshold) / (opaque_threshold - transparent_threshold), 0, 1)
        alpha = (255 * ratio * ratio * (3 - 2 * ratio)).astype(np.uint8)
        selected = key_channels(key)
        if selected:
            other = [index for index in range(3) if index not in selected]
            key_strength = np.min(rgb[:, :, selected], axis=2)
            other_strength = np.max(rgb[:, :, other], axis=2)
            dominance = np.maximum(0, key_strength - other_strength)
            denominator = np.maximum(1, max(key) - other_strength)
            dominance_alpha = (255 * (1 - np.minimum(1, dominance / denominator))).astype(np.uint8)
            alpha = np.minimum(alpha, dominance_alpha)
            despill_mask = alpha < 252
            neutral_edge = other_strength
            rgb[:, :, selected] = np.where(
                despill_mask[:, :, None],
                np.minimum(rgb[:, :, selected], neutral_edge[:, :, None]),
                rgb[:, :, selected],
            )
        if source_alpha is not None:
            alpha = ((alpha.astype(np.uint16) * source_alpha.astype(np.uint16)) // 255).astype(np.uint8)
        output = np.dstack((rgb.clip(0, 255).astype(np.uint8), alpha))
        image = Image.fromarray(output, "RGBA")
    return image


def fit_light_background(base: np.ndarray) -> np.ndarray:
    """Fit the simple light backdrop, never copy an old face into a cleared area."""
    height, width = base.shape[:2]
    yy, xx = np.mgrid[:height, :width]
    light = (base.min(axis=2) > 215) & (np.ptp(base.astype(float), axis=2) < 30)
    coordinates = np.stack([np.ones_like(xx), xx, yy], axis=-1)
    if np.count_nonzero(light) < 3 or np.linalg.matrix_rank(coordinates[light]) < 3:
        raise ValueError("fit-edge-light needs a simple light backdrop with enough spatial samples")
    coefficients = np.linalg.lstsq(coordinates[light], base[light], rcond=None)[0]
    background = np.clip(coordinates @ coefficients, 0, 255).astype(np.uint8)
    # Even light pixels can contain antialiased hair from the static head.
    # Use the fitted backdrop everywhere; copying those pixels leaves an outline.
    return background


def check_anchors(anchors: list[int], count: int, require_zero: bool = False) -> None:
    if (not isinstance(anchors, list) or len(anchors) != 8
            or any(type(value) is not int or not 0 <= value < count for value in anchors)
            or any(a >= b for a, b in zip(anchors, anchors[1:]))
            or (require_zero and anchors[0] != 0)):
        raise ValueError("eight strictly increasing, in-range direction anchors are required (output UP=0)")


def assemble_route(main: list, upper: list, spec: dict) -> tuple[list, list, list, list]:
    """Absolute source indices in, compiled indices and traceable frame origins out."""
    main_anchors = spec["mainAnchors"]
    check_anchors(main_anchors, len(main))
    if upper:
        midpoint = spec["upperMidpoint"]
        if type(midpoint) is not int or not 0 < midpoint < len(upper) - 1:
            raise ValueError("upperMidpoint must be inside the sampled upper take")
        right, left = main_anchors[1], main_anchors[7]  # upper-right / upper-left
        if spec.get("mainRightFrame", right) != right or spec.get("mainLeftFrame", left) != left:
            raise ValueError("upper endpoints must use mainAnchors[1] and mainAnchors[7]")
        if "sourceRange" in spec and spec["sourceRange"] != [right + 1, left + 1]:
            raise ValueError("sourceRange conflicts with the main range used by upper repair")
        step = spec.get("upperStep", 1)
        upper = upper[:]
        upper[0], upper[-1] = main[left], main[right]
        route = upper[midpoint:] + main[right + 1:left + 1] + upper[1:midpoint]
        upper_ids = [{"source": spec["upperVideo"], "frame": index * step} for index in range(len(upper))]
        upper_ids[0] = {"source": spec["sourceVideo"], "frame": left}
        upper_ids[-1] = {"source": spec["sourceVideo"], "frame": right}
        origins = upper_ids[midpoint:] + [{"source": spec["sourceVideo"], "frame": index}
                   for index in range(right + 1, left + 1)] + upper_ids[1:midpoint]
        right_index = len(upper) - midpoint - 1
        anchors = [0, right_index] + [right_index + value - right for value in main_anchors[2:8]]
        source_range = [right + 1, left + 1]
    else:
        start, end = spec.get("sourceRange", [main_anchors[0], len(main)])
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(main):
            raise ValueError("sourceRange must be a valid half-open source frame range")
        route = main[start:end]
        anchors = [value - start for value in main_anchors]
        origins = [{"source": spec["sourceVideo"], "frame": index} for index in range(start, end)]
        source_range = [start, end]
    check_anchors(anchors, len(route), require_zero=True)
    return route, anchors, origins, source_range


def make_background_contact_sheet(images: list[Image.Image], anchors: list[int], output: Path) -> None:
    backgrounds = [("light", "#F2EEE7"), ("dark", "#171717"),
                   ("blue", "#2857D9"), ("magenta", "#D52C75")]
    indices = sorted({max(0, min(len(images) - 1, index)) for index in anchors})
    thumb = 176
    label_h = 24
    cell_h = thumb + label_h
    sheet = Image.new("RGB", (len(indices) * thumb, len(backgrounds) * cell_h), "#FFFFFF")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(sheet)
    for row, (name, color) in enumerate(backgrounds):
        for col, index in enumerate(indices):
            layer = images[index].copy()
            layer.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (thumb, thumb), color)
            canvas.alpha_composite(layer, ((thumb - layer.width) // 2, (thumb - layer.height) // 2))
            sheet.paste(canvas.convert("RGB"), (col * thumb, row * cell_h))
            draw.text((col * thumb + 4, row * cell_h + thumb + 4), f"{name} / frame {index}", fill="#222222")
    sheet.save(output, optimize=True)


def build(spec: dict, root: Path) -> None:
    base_path = root / spec["baseImage"]
    base_image = Image.open(base_path).convert("RGB")
    source_width, source_height = spec["sourceSize"]
    if [base_image.width, base_image.height] != [source_width, source_height]:
        raise ValueError("base image dimensions do not match sourceSize")

    x, y, width, height = spec["crop"]
    if (any(type(v) is not int for v in [x, y, width, height]) or min(x, y) < 0
            or min(width, height) <= 0 or x + width > source_width or y + height > source_height):
        raise ValueError("crop is outside sourceSize")
    eye_x, eye_y = spec["eye"]
    if not x <= eye_x < x + width or not y <= eye_y < y + height:
        raise ValueError("eye must be inside crop, in source-image pixels")
    motion_x, motion_y, motion_width, motion_height = spec.get("motionCrop", [0, 0, width, height])
    render_size = spec["renderSize"]
    if type(render_size) is int and render_size > 0:
        render_width = render_height = render_size
    elif isinstance(render_size, list) and len(render_size) == 2 and all(isinstance(value, int) and value > 0 for value in render_size):
        render_width, render_height = render_size
    else:
        raise ValueError("renderSize must be a positive square size or [width, height]")
    size = (render_width, render_height)
    if motion_x < 0 or motion_y < 0 or motion_x + motion_width > render_width or motion_y + motion_height > render_height:
        raise ValueError("motionCrop is outside generated video frame")
    if [motion_width, motion_height] != [width, height]:
        raise ValueError("motionCrop must have the same cell size as crop")

    upper_step = spec.get("upperStep", 1)
    if type(upper_step) is not int or upper_step < 1:
        raise ValueError("upperStep must be a positive integer")
    main = frames(root / spec["sourceVideo"], size)
    upper = frames(root / spec["upperVideo"], size, upper_step) if spec.get("upperVideo") else []
    preview = spec.get('preview')
    if preview is not None:
        from candidate_preview import validate_preview
        if upper or 'mainAnchors' in spec or 'phaseSamples' in spec:
            raise ValueError('candidate preview uses a continuous sourceRange, not invented direction anchors')
        start,end=spec.get('sourceRange',[0,len(main)])
        if any(type(v) is not int for v in (start,end)) or not 0<=start<end<=len(main):
            raise ValueError('invalid candidate sourceRange')
        route=main[start:end];source_range=[start,end]
        origins=[dict(source=spec['sourceVideo'],frame=i) for i in range(start,end)]
        validate_preview(preview,len(route))
        anchors=[v[1] for v in preview['samples']]  # contact sheet positions, never direction labels
    else:
        route, anchors, origins, source_range = assemble_route(main, upper, spec)
    lineage_meta = None
    if spec.get('frameLineage'):
        from video_lineage import load_lineage, annotate
        report,lineage_meta=load_lineage(root,spec['frameLineage'],spec['originalSource'],spec['sourceVideo'])
        if report['frameCount']!=len(main):raise ValueError('lineage does not match decoded video count')
        annotate(origins,report['frames'],spec['originalSource'],spec['sourceVideo'])

    background_owner = spec.get("backgroundOwner")
    background_mode = spec.get("backgroundMode")
    if background_owner not in {"page", "scene"}:
        raise ValueError("backgroundOwner is required and must be 'page' or 'scene'")
    if background_mode is None:
        raise ValueError("backgroundMode is required; choose preserve or chroma-key explicitly")
    if background_mode not in {"preserve", "replace-edge-light", "fit-edge-light", "chroma-key"}:
        raise ValueError("unknown backgroundMode")
    if background_mode == "chroma-key" and background_owner != "page":
        raise ValueError("chroma-key is only valid when backgroundOwner is 'page'")
    if background_mode in {"replace-edge-light", "fit-edge-light"} and background_owner != "scene":
        raise ValueError("light background repair is only supported for scene-owned patches")
    clean_plate = None
    if background_owner == "page":
        if not spec.get("cleanPlate"):
            raise ValueError("page-owned head overlay needs cleanPlate with the old head removed")
        clean_path = root / spec["cleanPlate"]
        with Image.open(clean_path) as clean:
            if list(clean.size) != [source_width, source_height]:
                raise ValueError("cleanPlate dimensions must match sourceSize")
        clean_plate = {"path": spec["cleanPlate"], "sha256": hashlib.sha256(clean_path.read_bytes()).hexdigest()}
    key = None
    if background_mode == "chroma-key":
        key_option = spec.get("keyColor")
        if not key_option:
            raise ValueError("chroma-key mode requires keyColor ('auto' or hex)")
        if key_option.lower() == "auto":
            candidates = [sample_border_key(main[0])]
            if upper:
                candidates.append(sample_border_key(upper[0]))
            key = tuple(int(statistics.median([candidate[channel] for candidate in candidates])) for channel in range(3))
        else:
            key = parse_key_color(key_option)
        transparent_threshold = int(spec.get("transparentThreshold", 12))
        opaque_threshold = int(spec.get("opaqueThreshold", 220))
        if not 0 <= transparent_threshold < opaque_threshold <= 255:
            raise ValueError("thresholds must satisfy 0 <= transparent < opaque <= 255")
        key_tolerance = int(spec.get("keyBorderTolerance", 48))
        key_min_match = float(spec.get("keyBorderMinMatch", 0.90))
        if not 0 <= key_tolerance <= 255 or not 0 < key_min_match <= 1:
            raise ValueError("keyBorderTolerance must be 0..255 and keyBorderMinMatch must be in (0, 1]")
        key_frames = route + (upper if upper else [])
        border_matches = []
        for frame in key_frames:
            band = max(1, min(frame.shape[0], frame.shape[1], 6))
            rgb = frame[:, :, :3]
            border = np.concatenate((rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3),
                                     rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3))).astype(np.int16)
            distances = np.max(np.abs(border - np.asarray(key, dtype=np.int16)), axis=1)
            border_matches.append(float(np.mean(distances <= key_tolerance)))
        background_qa = {
            "borderTolerance": key_tolerance,
            "minimumMatchRequired": key_min_match,
            "minimumObservedMatch": min(border_matches),
            "framesChecked": len(border_matches),
            "passed": min(border_matches) >= key_min_match,
        }
        if not background_qa["passed"]:
            raise ValueError(
                "chroma-key background is not stable at frame borders: "
                f"minimum match {background_qa['minimumObservedMatch']:.3f}, "
                f"required {key_min_match:.3f}; regenerate/repair the keyed source or set a justified QA threshold"
            )
    else:
        transparent_threshold = int(spec.get("transparentThreshold", 12))
        opaque_threshold = int(spec.get("opaqueThreshold", 220))
        background_qa = {"passed": None, "framesChecked": 0}
        if background_owner == "page":
            source_frames = route + (upper if upper else [])
            if any(frame.shape[2] != 4 or np.all(frame[:, :, 3] == 255) for frame in source_frames):
                raise ValueError("page-owned preserve requires genuine alpha in every source frame; use chroma-key for opaque RGB video")

    base_crop = np.asarray(base_image.crop((x, y, x + width, y + height)))
    if background_mode == "fit-edge-light":
        base_crop = fit_light_background(base_crop)
    output = root / spec["outputDir"]
    if preview is not None and (output/'manifest.json').exists():
        raise ValueError('preserve existing candidate; use a new outputDir')
    output.mkdir(parents=True, exist_ok=True)
    selected = []
    for frame in route:
        patch = frame[motion_y:motion_y + height, motion_x:motion_x + width]
        selected.append(patch_with_background(patch, base_crop, background_mode, key,
                                              transparent_threshold, opaque_threshold))

    if background_owner == "scene":
        alpha = np.zeros((height, width), dtype=np.uint8)
        feather_x = spec.get("featherX", 10)
        feather_y = spec.get("featherY", 18)
        feather_left, feather_top, feather_right, feather_bottom = spec.get(
            "feather", [feather_x, feather_y, feather_x, feather_y])
        if min(feather_left, feather_top, feather_right, feather_bottom) <= 0:
            raise ValueError("feather widths must be positive")
        for row in range(height):
            for col in range(width):
                distance = min(col / feather_left, (width - 1 - col) / feather_right,
                               row / feather_top, (height - 1 - row) / feather_bottom)
                alpha[row, col] = max(0, min(255, int(distance * 255)))
        alpha_image = Image.fromarray(alpha)
        for image in selected:
            image.putalpha(ImageChops.multiply(image.getchannel("A"), alpha_image))

    columns = spec.get("columns", 8)
    per_sheet = spec.get("framesPerSheet", 64)
    if type(columns) is not int or type(per_sheet) is not int or min(columns, per_sheet) < 1:
        raise ValueError("columns and framesPerSheet must be positive integers")
    sheets = []
    for start in range(0, len(selected), per_sheet):
        batch = selected[start:start + per_sheet]
        rows = (len(batch) + columns - 1) // columns
        atlas = Image.new("RGBA", (width * columns, height * rows))
        for index, image in enumerate(batch):
            atlas.paste(image, ((index % columns) * width, (index // columns) * height))
        name = f"sheet-{len(sheets)}.png"
        atlas.save(output / name, optimize=True)
        sheets.append(name)
    background_contact = None
    if background_owner == "page":
        background_contact = "background-contact-sheet.png"
        make_background_contact_sheet(selected, anchors, output / background_contact)
    base_image.crop((x, y, x + width, y + height)).save(output / "neutral.png")

    manifest = {
        "schemaVersion": 3,
        "sceneId": spec["sceneId"],
        "baseImage": spec["baseImage"],
        "baseImageSha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
        "sourceSize": [source_width, source_height],
        "crop": [x, y, width, height],
        "frameCount": len(selected),
        "fps": spec.get("fps", "24/1"),
        "columns": columns,
        "framesPerSheet": per_sheet,
        "sheets": sheets,
        "neutralImage": "neutral.png",
        "directionFrames": anchors,
        "eye": [spec["eye"][0] / source_width, spec["eye"][1] / source_height],
        "source": spec["sourceVideo"],
        "sourceRange": source_range,
        "upperSource": spec.get("upperVideo"),
        "upperFrameCount": len(upper),
        "upperMidpoint": spec.get("upperMidpoint"),
        "upperSeam": "adjacent-source-frames" if upper else None,
        "upperSeamScope": "top-center-only" if upper else None,
        "frameSources": origins,
        "sourceTransform": {"renderSize": list(size), "motionCrop": [motion_x, motion_y, width, height]},
        "sourceHashes": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                         for name in [spec["sourceVideo"], *([spec["upperVideo"]] if upper else [])]},
        "calibration": spec.get("calibration"),
        "runtime": spec.get("runtime", {}),
        "quality": {"status": "candidate", "circular": False},
        "cleanPlate": clean_plate,
        "background": {
            "owner": background_owner,
            "mode": background_mode,
            "keyColor": None if key is None else "#%02X%02X%02X" % key,
            "transparentThreshold": transparent_threshold if key is not None else None,
            "opaqueThreshold": opaque_threshold if key is not None else None,
            "qa": background_qa,
            "contactSheet": background_contact,
        },
    }
    if spec.get("phaseSamples") is not None:
        from atlas_quality import validate_phases
        validate_phases(spec['phaseSamples'], len(selected), anchors)
        manifest['phaseSamples'] = spec['phaseSamples']
    if lineage_meta:
        manifest['frameLineage']=lineage_meta
        manifest['sourceHashes'][spec['originalSource']]=lineage_meta['sourceSha256']
    if preview is not None:
        manifest.pop('directionFrames')
        manifest['preview']=preview
        manifest['sheetHashes']={p:hashlib.sha256((output/p).read_bytes()).hexdigest() for p in sheets}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path, help="JSON compiler specification")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    build(json.loads(args.spec.read_text(encoding="utf-8")), args.root.resolve())


if __name__ == "__main__":
    main()
