#!/usr/bin/env python3
"""Flatten a transparent PNG onto a uniform chroma-key background."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def parse_color(value: str) -> tuple[int, int, int]:
    normalized = value.removeprefix("#")
    if len(normalized) == 3:
        normalized = "".join(character * 2 for character in normalized)
    if len(normalized) != 6:
        raise argparse.ArgumentTypeError("color must be a six-digit hex value, for example #00FF00")
    try:
        return tuple(int(normalized[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError as error:
        raise argparse.ArgumentTypeError("color must be a six-digit hex value") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="transparent PNG source")
    parser.add_argument("output", type=Path, help="flattened RGB output PNG")
    parser.add_argument("--key-color", type=parse_color, default=parse_color("#00FF00"))
    args = parser.parse_args()

    with Image.open(args.input) as opened:
        subject = opened.convert("RGBA")
    background = Image.new("RGBA", subject.size, (*args.key_color, 255))
    background.alpha_composite(subject)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    background.convert("RGB").save(args.output, optimize=True)


if __name__ == "__main__":
    main()
