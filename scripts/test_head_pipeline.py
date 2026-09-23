"""Offline regression checks for real failure modes, without API requests."""
import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from compile_head_atlas import assemble_route, fit_light_background, patch_with_background, build
from validate_head_manifest import validate
from segment_head_motion import segments
from inspect_atlas_seams import transition_metrics


class PipelineTests(unittest.TestCase):
    def test_open_sequence_has_large_wrap_discontinuity(self):
        frames = [np.full((4, 4, 3), i * 10, np.uint8) for i in range(10)]
        report = transition_metrics(frames)
        self.assertIn(9, report['suspectTransitions'])
        self.assertEqual(report['boundaryDifference'], 90)
        self.assertEqual(report['visualAcceptance'], 'not-evaluated')

    def test_equal_frames_are_not_certified_as_a_good_loop(self):
        report = transition_metrics([np.zeros((4, 4, 3), np.uint8)] * 8)
        self.assertEqual(report['suspectTransitions'], [])
        self.assertEqual(report['visualAcceptance'], 'not-evaluated')

    def test_fitted_background_does_not_copy_light_hair_outline(self):
        base = np.full((40, 40, 3), 245, dtype=np.uint8)
        base[10:30, 10:30] = 50
        base[9, 10:30] = 225
        background = fit_light_background(base)
        self.assertGreater(int(background[9, 20, 0]), 240)
        self.assertLess(abs(int(background[9, 20, 0]) - int(background[8, 20, 0])), 2)

    def test_motion_segment_flushes_at_video_end(self):
        for scores, expected_end in [([0, 3, 4, 5], 3), ([0, 3, 4, 0], 2)]:
            found = segments(scores, 4, 2, .25, .15)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]['startSample'], 1)
            self.assertEqual(found[0]['endSample'], expected_end)
        self.assertEqual(segments([0, 0, 0], 4, 2, .25, .15), [])

    def test_source_range_uses_absolute_anchors(self):
        route, anchors, origins, _ = assemble_route(list(range(20)), [], {
            'sourceVideo':'main.mp4','sourceRange':[4,20],'mainAnchors':list(range(4,20,2))})
        self.assertEqual(anchors,list(range(0,16,2)))
        self.assertEqual(route[0],4);self.assertEqual(origins[0]['frame'],4)

    def test_upper_repair_derives_endpoints_and_keeps_provenance(self):
        spec=dict(sourceVideo='main.mp4',upperVideo='upper.mp4',upperStep=2,
                  upperMidpoint=4,mainAnchors=[2,4,6,8,10,12,14,16])
        route,anchors,origins,used=assemble_route(list(range(20)),list(range(100,110)),spec)
        self.assertEqual(used,[5,17]);self.assertEqual(route[anchors[1]],4)
        self.assertEqual(origins[0],dict(source='upper.mp4',frame=8))
        self.assertEqual(origins[-1],dict(source='upper.mp4',frame=6))

    def test_duplicate_anchor_is_rejected(self):
        with self.assertRaises(ValueError):
            assemble_route(list(range(20)),[],dict(sourceVideo='main.mp4',mainAnchors=[0]*8))

    def test_fitted_background_does_not_reinsert_old_head(self):
        base=np.full((10,10,3),240,dtype=np.uint8);base[3:7,3:7]=[70,40,20]
        background=fit_light_background(base)
        frame=np.full((10,10,4),255,dtype=np.uint8)
        result=np.asarray(patch_with_background(frame,background,'fit-edge-light'))
        self.assertTrue(np.all(result[4,4,:3]>235))
        self.assertTrue(np.all(result[:,:,3]==255))

    def test_documented_upper_spec_compiles(self):
        contract=(Path(__file__).resolve().parents[1]/'references/asset-contract.md').read_text(encoding='utf-8')
        spec=json.loads(contract.split('```json')[1].split('```')[0])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for key in ['baseImage','sourceVideo','upperVideo']:
                path=root/spec[key];path.parent.mkdir(parents=True,exist_ok=True)
                if key=='baseImage':Image.new('RGB',tuple(spec['sourceSize']),'white').save(path)
                else:path.write_bytes(b'offline-fixture')
            def fake_frames(video,size,step=1):
                frame=np.zeros((size[1],size[0],4),np.uint8);frame[:,:,3]=255
                return [frame]*(124//step)
            with patch('compile_head_atlas.frames',fake_frames):build(spec,root)
            with patch('validate_head_manifest.source_frame_count',return_value=124),contextlib.redirect_stdout(io.StringIO()):
                validate(root,root/spec['outputDir']/'manifest.json')

    def test_validator_rejects_each_reported_bad_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=root/'base.png';Image.new('RGB',(100,100),'white').save(base)
            Image.new('RGBA',(80,10),(1,2,3,255)).save(root/'sheet.png')
            good=dict(sceneId='test',baseImage='base.png',sourceSize=[100,100],crop=[40,40,10,10],eye=[.45,.45],
                      baseImageSha256=hashlib.sha256(base.read_bytes()).hexdigest(),frameCount=8,columns=8,
                      framesPerSheet=8,directionFrames=list(range(8)),sheets=['sheet.png'],
                      background=dict(owner='scene',mode='preserve'))
            target=root/'manifest.json';target.write_text(json.dumps(good))
            with contextlib.redirect_stdout(io.StringIO()):validate(root,target)
            for changes in [dict(sheets=[]),dict(directionFrames=[0]*8),dict(eye=[9,9]),dict(frameCount=9),
                            dict(crop=[40,40,0,10]),dict(background=dict(owner='page',mode='preserve'))]:
                with self.subTest(changes=changes):
                    bad=copy.deepcopy(good);bad.update(changes);target.write_text(json.dumps(bad))
                    with self.assertRaises(ValueError):validate(root,target)


if __name__=='__main__':unittest.main()
