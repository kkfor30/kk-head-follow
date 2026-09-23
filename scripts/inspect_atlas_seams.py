"""Inspect rendered atlas transitions, including the last-to-first boundary.

Pixel differences flag suspects, not perceptual acceptance. No media API calls.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def transition_metrics(frames):
    diffs = [float(np.abs(frames[(i + 1) % len(frames)].astype(float)
                               - frame.astype(float)).mean()) for i, frame in enumerate(frames)]
    median = float(np.median(diffs[:-1])) if len(diffs) > 1 else 0
    # A heuristic alert only; a low score cannot certify pose continuity.
    suspects = [i for i, score in enumerate(diffs) if score > max(3 * median, 5)]
    return dict(adjacentMedian=median, boundaryDifference=diffs[-1],
                differences=diffs, suspectTransitions=suspects,
                visualAcceptance='not-evaluated')


def inspect(manifest_path, output):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    width, height = manifest['crop'][2:]
    sheets = [Image.open(manifest_path.parent / name).convert('RGBA') for name in manifest['sheets']]
    frames = []
    for index in range(manifest['frameCount']):
        sheet, cell = divmod(index, manifest['framesPerSheet'])
        x, y = cell % manifest['columns'] * width, cell // manifest['columns'] * height
        patch = sheets[sheet].crop((x, y, x + width, y + height))
        # Composite all frames on the same neutral background for fair alpha handling.
        canvas = Image.new('RGBA', patch.size, 'white')
        canvas.alpha_composite(patch)
        frames.append(np.asarray(canvas.convert('RGB')))
    metrics = transition_metrics(frames)
    metrics['frameCount'] = len(frames)
    sources = manifest.get('frameSources', [])
    edges = sorted(set(metrics['suspectTransitions'] + [len(frames) - 1]))
    if sources:
        edges = sorted(set(edges + [i for i in range(len(frames) - 1)
                                   if sources[i]['source'] != sources[i + 1]['source']]))
    output.mkdir(parents=True, exist_ok=True)
    metrics['reviewTransitions'] = edges
    metrics['sourceBoundary'] = [sources[-1], sources[0]] if sources else None
    (output / 'seams.json').write_text(json.dumps(metrics, indent=2) + '\n', encoding='utf-8')
    # Each edge gets its own bounded-size strip, not an unbounded montage.
    for edge in edges:
        strip = Image.new('RGB', (width * 4, height + 30), 'white')
        draw = ImageDraw.Draw(strip)
        for col, index in enumerate([(edge - 1) % len(frames), edge, (edge + 1) % len(frames), (edge + 2) % len(frames)]):
            strip.paste(Image.fromarray(frames[index]), (col * width, 30))
            source = sources[index]['frame'] if sources else '?'
            draw.text((col * width + 4, 5), f'atlas {index} / source {source}', fill='black')
        strip.save(output / f'edge-{edge}.jpg')
    return metrics


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.manifest, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != 'differences'}))
