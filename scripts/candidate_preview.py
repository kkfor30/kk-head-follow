"""Candidate mappings are distinct from certified eight-direction atlases."""
import math


def validate_preview(preview, count):
    if not isinstance(preview, dict) or preview.get('mode') not in ('phase', 'arc'):
        raise ValueError('preview.mode must be phase or arc')
    samples = preview.get('samples')
    if not isinstance(samples, list) or len(samples) < 2:
        raise ValueError('preview needs at least two [degrees, atlasFrame] samples')
    for point in samples:
        if (not isinstance(point,list) or len(point)!=2 or type(point[0]) not in (int,float)
                or not math.isfinite(point[0]) or type(point[1]) is not int or not 0<=point[1]<count):
            raise ValueError('invalid preview sample')
    if any(a[0]>=b[0] or a[1]>=b[1] for a,b in zip(samples,samples[1:])):
        raise ValueError('preview samples must increase in angle and source frame')
    start,end=samples[0][0],samples[-1][0]
    if not 0<=start<360 or not 0<end-start<=360:
        raise ValueError('preview angle interval must span at most one turn')
    if preview['mode']=='phase' and (start!=0 or end!=360):
        raise ValueError('phase mapping spans 0–360; it does not certify head directions or a seamless loop')
    if preview['mode']=='arc' and end-start>=360:
        raise ValueError('arc must leave an unavailable interval; use a reviewed ring for complete coverage')
    if not isinstance(preview.get('notes'),str) or not preview['notes'].strip():
        raise ValueError('preview must disclose known limitations in notes')
