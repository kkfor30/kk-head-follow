#!/usr/bin/env python3
"""Check atlas data and provenance, without claiming visual acceptance."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path
from PIL import Image

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)

@lru_cache(maxsize=64)
def source_frame_count(path: str, sha256: str) -> int:
    """Decode-count the hashed source; do not trust hand-written frame counts."""
    try:
        result = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-count_frames',
            '-show_entries','stream=nb_read_frames','-of','json',path],check=True,capture_output=True,text=True,timeout=120)
        streams=json.loads(result.stdout).get('streams',[])
        count=int(streams[0]['nb_read_frames'])
    except (OSError,subprocess.SubprocessError,KeyError,IndexError,ValueError,TypeError) as exc:
        raise ValueError('cannot decode-count source: '+path) from exc
    require(count>0,'source video has no readable frames')
    return count

def validate(root: Path, manifest_path: Path, compare: Path | None = None, require_ready: bool = False) -> None:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(bool(m.get("sceneId")), "sceneId is required")
    base_path = root / m["baseImage"]
    require(base_path.is_file(), f"missing base image: {base_path}")
    require(hashlib.sha256(base_path.read_bytes()).hexdigest() == m["baseImageSha256"], "base image hash mismatch")
    with Image.open(base_path) as base:
        require(list(base.size) == m["sourceSize"], "base image size mismatch")
    x, y, w, h = m["crop"]
    sw, sh = m["sourceSize"]
    require(all(type(v) is int for v in [x,y,w,h]) and min(x,y)>=0 and min(w,h)>0
            and x+w<=sw and y+h<=sh, "crop is outside source image or empty")
    eye = m.get("eye", [])
    require(len(eye)==2 and all(isinstance(v,(float,int)) and math.isfinite(v) for v in eye), "invalid eye")
    require(x<=eye[0]*sw<x+w and y<=eye[1]*sh<y+h, "eye is outside crop")
    count, columns, per_sheet = (m[k] for k in ("frameCount","columns","framesPerSheet"))
    require(all(type(v) is int and v>0 for v in [count,columns,per_sheet]), "invalid atlas capacity")
    if m.get('preview') is not None:
        from candidate_preview import validate_preview
        validate_preview(m['preview'],count)
        require(not require_ready,'experimental preview cannot be ready')
        require('directionFrames' not in m and 'phaseSamples' not in m and m.get('quality',{}).get('status')!='reviewed',
                'preview cannot claim certified directions')
        a=[]
    else:
        a=m["directionFrames"]
        require(len(a)==8 and a[0]==0 and all(type(v) is int and 0<=v<count for v in a)
                and all(left<right for left,right in zip(a,a[1:])), "invalid or duplicate direction anchors")
    if m.get('phaseSamples') is not None:
        from atlas_quality import validate_phases
        validate_phases(m['phaseSamples'], count, a)
    sheets=m["sheets"]
    require(len(sheets)==math.ceil(count/per_sheet) and len(set(sheets))==len(sheets), "sheet count mismatch")
    bg=m.get("background", {})
    owner,mode=bg.get("owner"),bg.get("mode")
    require(owner in {"page","scene"}, "unknown background.owner")
    require(mode in {"preserve","chroma-key","replace-edge-light","fit-edge-light"}, "unknown background.mode")
    require(mode not in {"replace-edge-light","fit-edge-light"} or owner=="scene", "light repair requires scene")
    if mode=="chroma-key":
        require(owner=="page" and bool(bg.get("keyColor")) and bg.get("qa",{}).get("passed") is True,
                "chroma-key requires a passing report")
    for number,name in enumerate(sheets):
        path=manifest_path.parent/name
        require(path.is_file(), f"missing sheet: {name}")
        if m.get('preview') is not None:
            require(hashlib.sha256(path.read_bytes()).hexdigest()==m.get('sheetHashes',{}).get(name),'candidate sheet changed')
        cells=min(per_sheet,count-number*per_sheet)
        with Image.open(path) as image:
            require(image.width==w*columns and image.height>=math.ceil(cells/columns)*h,
                    f"sheet dimensions cannot hold declared frames: {name}")
            require("A" in image.getbands(), f"sheet needs alpha: {name}")
            for cell in range(cells):
                box=((cell%columns)*w,(cell//columns)*h,(cell%columns+1)*w,(cell//columns+1)*h)
                low,high=image.crop(box).getchannel("A").getextrema()
                require(high>0, f"empty active frame {number*per_sheet+cell}")
                if owner=="page":
                    require(low<255, f"opaque page-owned frame {number*per_sheet+cell}")
    if owner=="page":
        require(mode in {"preserve","chroma-key"}, "page requires transparent delivery")
        plate=m.get("cleanPlate")
        require(isinstance(plate,dict) and bool(plate.get("path")), "page overlay needs cleanPlate")
        path=root/plate["path"]
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==plate.get("sha256"),
                "cleanPlate missing or changed")
        with Image.open(path) as image:
            require(list(image.size)==[sw,sh], "cleanPlate size mismatch")
        contact=bg.get("contactSheet")
        require(bool(contact) and (manifest_path.parent/contact).is_file(), "missing composite contact sheet")
    if m.get("schemaVersion",1)>=2:
        sources=m.get("frameSources",[])
        require(len(sources)==count, "frameSources length mismatch")
        hashes=m.get("sourceHashes",{})
        require(bool(hashes), "sourceHashes required")
        counts={}
        for name,expected in hashes.items():
            path=root/name
            require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==expected, f"source changed: {name}")
            counts[name]=source_frame_count(str(path.resolve()),expected)
        require(all(item.get("source") in hashes and type(item.get("frame")) is int and 0<=item["frame"]<counts[item['source']]
                    for item in sources), "invalid frame source record")
        if m.get("upperSource"):
            require(m.get("upperSeamScope")=="top-center-only", "upper seam scope must be explicit")
            require(sources[0]["source"]==sources[-1]["source"]==m["upperSource"]
                    and sources[0]["frame"]>sources[-1]["frame"], "top-center seam provenance mismatch")
    if m.get("upperSource"):
        require(m.get("upperSeam")=="adjacent-source-frames", "missing upper center seam declaration")
    if m.get('frameLineage'):
        from video_lineage import validate_lineage
        validate_lineage(root,m)
    for name,sha in m.get('repair',{}).get('inputHashes',{}).items():
        require((root/name).is_file() and hashlib.sha256((root/name).read_bytes()).hexdigest()==sha,
                'repair input missing or changed: '+name)
    if compare:
        other=json.loads(compare.read_text(encoding="utf-8"))
        require(other["baseImageSha256"]==m["baseImageSha256"] and other["sourceSize"]==m["sourceSize"],
                "comparison requires the same scene")
        bx,by,bw,bh=other["crop"]
        require(not(x<bx+bw and x+w>bx and y<by+bh and y+h>by), "subject crops overlap")
    if require_ready:
        from atlas_quality import verify_certificate
        verify_certificate(m, manifest_path, root)
    print(json.dumps(dict(valid=True,sceneId=m["sceneId"],frameCount=count,sheets=len(sheets),
                         runtimeReadiness='verified' if require_ready else 'not-checked',
                         visualAcceptance="not-evaluated"),indent=2))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--compare",type=Path)
    parser.add_argument("--root",type=Path,default=Path.cwd())
    parser.add_argument('--require-ready',action='store_true')
    args=parser.parse_args()
    validate(args.root.resolve(),args.manifest.resolve(),args.compare.resolve() if args.compare else None,args.require_ready)

