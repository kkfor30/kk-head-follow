"""A real dense-video certificate must be consumable by the shipped JS verifier."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

from densify_head_video import densify
from compile_head_atlas import build
from atlas_quality import read, review_template
from audit_head_atlas import audit
from validate_head_manifest import validate


class RuntimeQualityHandoff(unittest.TestCase):
    def test_real_dense_source_approved_in_python_loads_in_javascript(self):
        if not all(shutil.which(tool) for tool in ('ffmpeg','ffprobe','node')):
            self.skipTest('FFmpeg, FFprobe and Node required')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                            'color=c=gray:size=64x64:rate=10:duration=1.6','-c:v','ffv1',
                            str(root/'source.mkv')],check=True)
            densify(root/'source.mkv',root/'dense')
            Image.new('RGB',(64,64),(128,128,128)).save(root/'base.png')
            spec=dict(sceneId='synthetic-contract-fixture',baseImage='base.png',sourceVideo='dense/candidate.mkv',
                      sourceSize=[64,64],crop=[0,0,64,64],eye=[32,32],renderSize=64,
                      backgroundOwner='scene',backgroundMode='preserve',mainAnchors=list(range(0,31,4)),
                      outputDir='atlas',frameLineage='dense/lineage.json',originalSource='source.mkv')
            build(spec,root);path=root/'atlas/manifest.json'
            motion=np.zeros((64,64),np.uint8);motion[20:44,20:44]=255
            static=np.zeros((64,64),np.uint8);static[3:14,3:61]=255
            Image.fromarray(motion).save(root/'motion.png');Image.fromarray(static).save(root/'static.png')
            (root/'evidence.txt').write_text('Synthetic contract fixture only; not real visual acceptance.')
            review=review_template(read(path),path,root)
            review['backgroundMasks']=dict(static='static.png',motionUnion='motion.png')
            for item in review['observations']:
                item.update(gaze=item['head'],evidence=['evidence.txt'],notes='Synthetic fixture only')
            for item in review['checks'].values():
                item.update(status='pass',evidence=['evidence.txt'],notes='Synthetic fixture only')
            review_path=root/'observations.json';review_path.write_text(json.dumps(review))
            with contextlib.redirect_stdout(io.StringIO()):
                audit(path,root,root/'atlas/quality-report.json',review_path,True)
                validate(root,path,require_ready=True)
            verifier=(Path(__file__).resolve().parents[1]/'assets/quality-gate.mjs').as_uri()
            code='''
                import {readFile} from 'node:fs/promises';
                import {verifyQuality} from %s;
                const manifest=new URL(%s),root=new URL(%s);
                const config=JSON.parse(await readFile(manifest,'utf8'));
                globalThis.fetch=async url=>{const bytes=await readFile(url);return {ok:true,
                  arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)};};
                const assets=await verifyQuality(config,manifest,root);
                if(!assets.has(new URL('dense/lineage.json',root).href))throw Error('lineage not verified');
                if(!assets.get(new URL('base.png',root).href).bytes.byteLength)throw Error('pixels not handed off');
                console.log('verified');
            ''' % (json.dumps(verifier),json.dumps(path.as_uri()),json.dumps(root.as_uri()+'/'))
            result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),'verified')


if __name__=='__main__':
    unittest.main()
