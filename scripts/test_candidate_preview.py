"""Exercise candidate compilation and certificate separation using a real local video."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from candidate_preview import validate_preview
from compile_head_atlas import build
from validate_head_manifest import validate
from audit_head_atlas import audit
from review_head_atlas import sweep_indices


class CandidateTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        Image.new('RGB',(64,64),'white').save(self.root/'base.png')
        writer=cv2.VideoWriter(str(self.root/'motion.avi'),cv2.VideoWriter_fourcc(*'MJPG'),24,(32,32))
        self.assertTrue(writer.isOpened())
        for i in range(12):writer.write(np.full((32,32,3),40+i*10,np.uint8))
        writer.release()
        self.spec=dict(sceneId='fixture',baseImage='base.png',sourceSize=[64,64],crop=[16,16,32,32],
            eye=[32,32],renderSize=32,motionCrop=[0,0,32,32],sourceVideo='motion.avi',sourceRange=[2,10],
            outputDir='candidate',backgroundOwner='scene',backgroundMode='preserve',columns=4,framesPerSheet=4,
            preview=dict(mode='phase',samples=[[0,0],[360,7]],notes='Offline synthetic phase; no direction claim.'))
        self.manifest=self.root/'candidate/manifest.json'

    def test_real_source_compiles_without_inventing_anchors_and_preserves_indices(self):
        build(self.spec,self.root)
        with contextlib.redirect_stdout(io.StringIO()):validate(self.root,self.manifest)
        m=json.loads(self.manifest.read_text())
        self.assertNotIn('directionFrames',m)
        self.assertEqual([v['frame'] for v in m['frameSources']],list(range(2,10)))
        with self.assertRaisesRegex(ValueError,'cannot be ready'):validate(self.root,self.manifest,require_ready=True)
        with self.assertRaisesRegex(ValueError,'no direction certificate'):
            audit(self.manifest,self.root,self.root/'quality.json',approve=True)
        with self.assertRaisesRegex(ValueError,'preserve existing'):build(self.spec,self.root)

    def test_tampered_assets_or_certified_metadata_are_rejected(self):
        build(self.spec,self.root);original=json.loads(self.manifest.read_text())
        for patch in [dict(directionFrames=list(range(8))),dict(phaseSamples=[[0,0],[7,315]]),
                      dict(quality=dict(status='reviewed')),dict(columns=.5)]:
            with self.subTest(patch=patch):
                self.manifest.write_text(json.dumps({**original,**patch}))
                with self.assertRaises(ValueError):validate(self.root,self.manifest)
        self.manifest.write_text(json.dumps(original))
        Image.new('RGBA',(128,32),'red').save(self.root/'candidate/sheet-0.png')
        with self.assertRaisesRegex(ValueError,'sheet changed'):validate(self.root,self.manifest)

    def test_invalid_mapping_cannot_turn_partial_motion_into_a_ring(self):
        for preview in [dict(mode='arc',samples=[[0,0],[360,7]]),dict(mode='phase',samples=[[10,0],[360,7]]),
                        dict(mode='arc',samples=[[45,0],[90,9]]),dict(mode='arc',samples=[[90,3],[180,2]]),
                        dict(mode='arc',samples=[[float('nan'),0],[90,7]])]:
            with self.subTest(preview=preview),self.assertRaises(ValueError):
                validate_preview({**preview,'notes':'fixture'},8)
        spec=copy.deepcopy(self.spec);spec['preview']=dict(mode='arc',samples=[[315,0],[405,7]],notes='Fixture only')
        build(spec,self.root)
        with contextlib.redirect_stdout(io.StringIO()):validate(self.root,self.manifest)

    def test_finite_arc_evidence_does_not_jump_between_unconnected_endpoints(self):
        path=sweep_indices(8,arc=True)
        self.assertEqual(set(path),set(range(8)))
        self.assertTrue(all(abs(a-b)==1 for a,b in zip(path,path[1:])))
        self.assertEqual(path[0],path[-1])


if __name__=='__main__':unittest.main()
