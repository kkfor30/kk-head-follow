"""Actual decode and publication regressions. No generation service calls."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

from compile_head_atlas import build, frames, patch_with_background
from validate_head_manifest import validate
from prepare_head_mattes import sha
from review_source_video import review as review_source


class CompileRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        if not shutil.which('ffmpeg'):
            self.skipTest('FFmpeg required')
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc=size=64x64:rate=10:duration=1.6', '-c:v', 'ffv1',
                        str(self.root/'source.mkv')], check=True)
        Image.new('RGB', (64, 64), (120, 120, 120)).save(self.root/'base.png')
        self.spec = dict(sceneId='test', baseImage='base.png', sourceVideo='source.mkv',
                         sourceSize=[64,64], crop=[0,0,64,64], eye=[32,32], renderSize=64,
                         backgroundOwner='scene', backgroundMode='preserve',
                         mainAnchors=list(range(0,16,2)), outputDir='atlas')

    def test_failed_recompile_never_changes_published_files(self):
        build(self.spec, self.root)
        output = self.root/'atlas'
        old = {p.name: p.read_bytes() for p in output.iterdir()}
        self.spec.update(feather=[4,4,4,4], phaseSamples=[[0,0]])
        with self.assertRaisesRegex(ValueError, 'preserve existing'):
            build(self.spec, self.root)
        self.assertEqual(old, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_failure_does_not_publish_partial_new_directory(self):
        self.spec['phaseSamples'] = [[0,0]]
        with self.assertRaisesRegex(ValueError, 'phaseSamples'):
            build(self.spec, self.root)
        self.assertFalse((self.root/'atlas').exists())
        self.assertEqual(list(self.root.glob('.atlas-*')), [])
        self.spec.pop('phaseSamples')
        build(self.spec, self.root)
        with contextlib.redirect_stdout(io.StringIO()):
            validate(self.root, self.root/'atlas/manifest.json')

    def test_vfr_keeps_native_decoded_indices(self):
        video = self.root/'vfr.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.root/'source.mkv'), '-vf',
                        "setpts='if(lt(N,8),N,8+(N-8)*2)/(10*TB)'", '-fps_mode', 'vfr',
                        '-c:v', 'ffv1', str(video)], check=True)
        actual = frames(video, (64,64))
        cap, native = cv2.VideoCapture(str(video)), []
        try:
            while True:
                ok, bgr = cap.read()
                if not ok:
                    break
                native.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA))
        finally:
            cap.release()
        self.assertEqual(len(actual), 16)
        for a,b in zip(actual, native):
            np.testing.assert_array_equal(a,b)
        self.spec['sourceVideo'] = 'vfr.mkv'
        build(self.spec, self.root)
        with contextlib.redirect_stdout(io.StringIO()):
            validate(self.root, self.root/'atlas/manifest.json')
        m = json.loads((self.root/'atlas/manifest.json').read_text())
        self.assertEqual([item['frame'] for item in m['frameSources']], list(range(16)))
        r=review_source(video,self.root/'source-review',[0,0,64,64],64)
        self.assertEqual(r['frameCount'],16)
        self.assertEqual([i for page in r['contactSheets'] for i in page['sourceFrames']],list(range(16)))
        self.assertNotAlmostEqual(r['sourceTimes'][-1]-r['sourceTimes'][-2],r['sourceTimes'][1]-r['sourceTimes'][0])
        self.assertEqual(r['decision']['mode'],'unreviewed')
        self.assertEqual(r['observations']['gaze'],'unknown')
        self.assertEqual(r['overview']['sourceFrames'],list(range(16)))
        self.assertTrue((self.root/'source-review'/r['overview']['path']).is_file())
        self.assertTrue(all(row['head']=='unknown' and row['gaze']=='unknown'
                            for row in r['observations']['headAndGazeByDirection']))
        self.assertNotIn((15,0),list(zip(r['sweepFrameIndices'],r['sweepFrameIndices'][1:])))
        with self.assertRaisesRegex(ValueError,'preserve existing'):
            review_source(video,self.root/'source-review',[0,0,64,64],64)

    def test_source_review_rejects_invalid_crop_without_creating_output(self):
        with self.assertRaisesRegex(ValueError,'outside native video'):
            review_source(self.root/'source.mkv',self.root/'review',[60,0,10,20])
        self.assertFalse((self.root/'review').exists())

    def test_overview_samples_endpoints_without_losing_full_frame_evidence(self):
        source=self.root/'longer.mkv'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
                        'testsrc=size=64x64:rate=10:duration=3','-c:v','ffv1',str(source)],check=True)
        report=review_source(source,self.root/'long-review',max_side=64)
        samples=report['overview']['sourceFrames']
        self.assertEqual((samples[0],samples[-1],len(samples)),(0,29,24))
        self.assertEqual(samples,sorted(set(samples)))
        self.assertEqual([i for page in report['contactSheets'] for i in page['sourceFrames']],list(range(30)))


class ColorAndHashRegressions(unittest.TestCase):
    def test_achromatic_key_removes_background_and_keeps_distant_foreground(self):
        for key, foreground in [((255,255,255), (0,0,0)), ((128,128,128), (0,0,0)), ((0,255,0), (255,0,0))]:
            frame = np.full((12,12,4),255,dtype=np.uint8)
            frame[:,:,:3] = key
            frame[4:8,4:8,:3] = foreground
            result = np.asarray(patch_with_background(frame, frame[:,:,:3], 'chroma-key', key))
            self.assertEqual(result[0,0,3],0)
            self.assertGreater(result[5,5,3],0)
            np.testing.assert_array_equal(result[5,5,:3],foreground)

    def test_mask_hash_does_not_require_python_311_file_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'fixture.bin';p.write_bytes(b'head-follow'*(1024*200))
            self.assertEqual(sha(p),hashlib.sha256(p.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
