"""Behavioral regressions for quality gates and bounded, non-destructive repairs."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from atlas_quality import (digest,binding,read,review_template,assess,write_sheets,
                           verify_certificate,background_metrics,validate_phases)
from audit_head_atlas import audit
from repair_head_atlas import correct_color,clean_composite,flow_bridge,register_translation,repair
from generation_plan import validate_plan
from generate_zenmux_video import build_content
from review_head_atlas import sweep_indices


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'manifest.json'
        counter=patch('validate_head_manifest.source_frame_count',return_value=16)
        counter.start();self.addCleanup(counter.stop)
        # The tiny fixtures test contracts, not semantic face detection.
        self.base=np.full((64,64,3),120,np.uint8)
        Image.fromarray(self.base).save(self.root/'base.png')
        (self.root/'source.mp4').write_bytes(b'fixture')
        self.motion=np.zeros((64,64),bool);self.motion[20:44,20:44]=True
        self.static=np.zeros_like(self.motion);self.static[3:14,3:61]=True
        for name,mask in [('static',self.static),('motion',self.motion)]:
            Image.fromarray((mask*255).astype('uint8')).save(self.root/f'{name}.png')
        self.frames=[np.dstack([self.base.copy(),np.full((64,64),255,np.uint8)]) for _ in range(16)]
        self.m=dict(schemaVersion=3,sceneId='fixture',baseImage='base.png',baseImageSha256=digest(self.root/'base.png'),
                    sourceSize=[64,64],crop=[0,0,64,64],eye=[.5,.5],directionFrames=list(range(0,16,2)),
                    columns=4,framesPerSheet=16,sourceHashes={'source.mp4':digest(self.root/'source.mp4')},
                    frameSources=[dict(source='source.mp4',frame=i) for i in range(16)],
                    background=dict(owner='scene',mode='preserve',qa=dict(passed=None,framesChecked=0)),
                    quality=dict(status='candidate',circular=False))
        self.save()

    def save(self):
        write_sheets(self.m,self.frames,self.root)
        self.path.write_text(json.dumps(self.m))

    def reviewed(self):
        (self.root/'evidence.txt').write_text('Synthetic engineering fixture; no real subject acceptance.')
        r=review_template(self.m,self.path,self.root)
        r['backgroundMasks']=dict(static='static.png',motionUnion='motion.png')
        for item in r['observations']:
            item.update(gaze=item['head'],evidence=['evidence.txt'],notes='Fixture direction contract')
        for item in r['checks'].values():
            item.update(status='pass',evidence=['evidence.txt'],notes='Fixture explicit review')
        return r

    def test_no_pixel_metric_can_approve_an_unreviewed_atlas(self):
        r=assess(self.m,self.path,self.root)
        self.assertEqual(r['status'],'blocked')
        self.assertEqual(r['transitions']['suspectTransitions'],[])
        self.assertIn('unreviewed-or-failed:gaze',r['issues'])

    def test_false_direction_and_unknown_gaze_are_blocked(self):
        for field,value in [('head','neutral'),('gaze','unknown')]:
            r=self.reviewed();r['observations'][0][field]=value
            self.assertIn('missing-head-or-gaze-evidence:up',assess(self.m,self.path,self.root,r)['issues'])

    def test_background_patch_blocks_even_a_claimed_visual_pass(self):
        self.frames[7][:10,:,:3]=150;self.save()
        r=assess(self.m,self.path,self.root,self.reviewed())
        self.assertIn('background-residual',r['issues'])
        self.assertEqual(r['background']['framesChecked'],16)

    def test_approval_invalidates_when_pixels_or_evidence_change(self):
        r=self.root/'review.json';r.write_text(json.dumps(self.reviewed()))
        with contextlib.redirect_stdout(io.StringIO()):audit(self.path,self.root,self.root/'quality.json',r,True)
        approved=read(self.path);verify_certificate(approved,self.path,self.root)
        (self.root/'evidence.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'evidence changed'):verify_certificate(approved,self.path,self.root)
        self.frames[0][30,30,:3]=0;write_sheets(self.m,self.frames,self.root)
        with self.assertRaisesRegex(ValueError,'changed'):verify_certificate(approved,self.path,self.root)

    def test_failed_recheck_revokes_an_older_pass_even_with_a_new_report_path(self):
        r=self.root/'review.json';r.write_text(json.dumps(self.reviewed()))
        with contextlib.redirect_stdout(io.StringIO()):audit(self.path,self.root,self.root/'quality.json',r,True)
        bad=read(r);bad['checks']['gaze']['status']='fail';r.write_text(json.dumps(bad))
        with contextlib.redirect_stdout(io.StringIO()):audit(self.path,self.root,self.root/'new-report.json',r)
        self.assertEqual(read(self.path)['quality']['status'],'blocked')
        with self.assertRaises(ValueError):verify_certificate(read(self.path),self.path,self.root)

    def test_structural_recheck_error_also_revokes_an_older_pass(self):
        r=self.root/'review.json';r.write_text(json.dumps(self.reviewed()))
        with contextlib.redirect_stdout(io.StringIO()):audit(self.path,self.root,self.root/'quality.json',r,True)
        (self.root/'source.mp4').write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError,'source changed'):
            audit(self.path,self.root,self.root/'new-report.json',r,True)
        self.assertEqual(read(self.path)['quality']['status'],'blocked')

    def test_source_indices_cannot_exceed_decoded_video(self):
        from validate_head_manifest import validate
        self.m['frameSources'][3]['frame']=1000000000;self.save()
        with self.assertRaisesRegex(ValueError,'frame source'):validate(self.root,self.path)

    def test_chained_repairs_keep_ancestor_input_hashes(self):
        from validate_head_manifest import validate
        op=dict(staticMask='static.png',motionUnion='motion.png',operations=[dict(type='color-offset')])
        with contextlib.redirect_stdout(io.StringIO()):
            repair(self.path,self.root,op,self.root/'color')
            repair(self.root/'color/manifest.json',self.root,dict(keepFrames=list(range(16))),self.root/'trim')
        self.assertIn('motion.png',read(self.root/'trim/manifest.json')['repair']['inputHashes'])
        Image.new('L',(64,64)).save(self.root/'motion.png')
        with self.assertRaisesRegex(ValueError,'repair input'):validate(self.root,self.root/'trim/manifest.json')

    def test_static_masks_cannot_include_moving_ears_or_old_head(self):
        self.static[21,21]=True
        with self.assertRaisesRegex(ValueError,'exclude'):
            background_metrics([self.base],self.base,self.static,self.motion)

    def test_color_drift_repair_preserves_spatial_structure(self):
        frame=self.frames[0].copy();frame[:,:,:3]+=6
        result,report=correct_color(frame,self.base,self.static,self.motion)
        np.testing.assert_array_equal(result[:,:,:3],self.base)
        self.assertEqual(report['after']['mae'],0)
        frame[:10,:32,:3]=80
        with self.assertRaises(ValueError):correct_color(frame,self.base,self.static,self.motion)

    def test_clean_plate_removes_old_head_without_blending_two_faces(self):
        frame=self.frames[0].copy();frame[25:35,30:40,:3]=200
        alpha=np.zeros((64,64),np.uint8);alpha[25:35,30:40]=255
        plate=np.full((64,64,3),99,np.uint8)
        out=clean_composite(frame,plate,alpha)
        np.testing.assert_array_equal(out[26:34,31:39,:3],frame[26:34,31:39,:3])
        np.testing.assert_array_equal(out[:20,:,:3],plate[:20])
        frame[26,31,3]=100
        with self.assertRaises(ValueError):clean_composite(frame,plate,alpha)

    def test_trim_keeps_originals_and_reindexes_anchors(self):
        before=digest(self.path);out=self.root/'separate-build'
        with contextlib.redirect_stdout(io.StringIO()):
            repair(self.path,self.root,dict(keepFrames=[i for i in range(16) if i not in (3,7)]),out)
        m=read(out/'manifest.json')
        self.assertEqual(m['directionFrames'],[0,2,3,5,6,8,10,12])
        self.assertEqual(m['quality']['status'],'candidate');self.assertEqual(digest(self.path),before)
        with self.assertRaises(ValueError):repair(self.path,self.root,dict(keepFrames=list(range(16))),out)

    def test_reverse_phase_and_missing_anchor_rejected(self):
        bad=[[i*2,i*45] for i in range(8)];bad[3][1]=30
        with self.assertRaises(ValueError):validate_phases(bad,16,self.m['directionFrames'])
        with self.assertRaises(ValueError):
            repair(self.path,self.root,dict(keepFrames=list(range(1,16))),self.root/'candidate')

    def test_review_sweeps_exercise_both_wrap_directions(self):
        route=sweep_indices(16)
        pairs=list(zip(route,route[1:]))
        self.assertIn((15,0),pairs);self.assertIn((0,15),pairs)

    def test_chroma_trim_preserves_source_key_qa_but_requires_new_review(self):
        self.m['background']=dict(owner='page',mode='chroma-key',keyColor='#00FF00',qa=dict(passed=True,framesChecked=16),
                                  contactSheet='background.png')
        Image.fromarray(self.base).save(self.root/'plate.png')
        self.m['cleanPlate']=dict(path='plate.png',sha256=digest(self.root/'plate.png'))
        Image.fromarray(self.base).save(self.root/'background.png')
        for frame in self.frames:frame[:3,:,3]=0
        self.save()
        with contextlib.redirect_stdout(io.StringIO()):
            repair(self.path,self.root,dict(keepFrames=[i for i in range(16) if i!=3]),self.root/'trimmed')
        result=read(self.root/'trimmed/manifest.json')
        self.assertIs(result['background']['qa']['passed'],True)
        self.assertEqual(result['quality']['status'],'candidate')

    def test_bridge_pipeline_reindexes_without_losing_synthetic_provenance(self):
        try:import cv2
        except ImportError:self.skipTest('optional OpenCV unavailable')
        spec=dict(staticMask='static.png',motionUnion='motion.png',
                  phaseSamples=[[i*2,i*45] for i in range(8)],bridges=[dict(afterFrame=1,toFrame=2,count=3)])
        with contextlib.redirect_stdout(io.StringIO()):repair(self.path,self.root,spec,self.root/'bridge')
        result=read(self.root/'bridge/manifest.json')
        self.assertEqual(result['frameCount'],19)
        self.assertEqual(result['directionFrames'],[0,5,7,9,11,13,15,17])
        self.assertEqual([i for i,s in enumerate(result['frameSources']) if s.get('synthesized')],[2,3,4])
        validate_phases(result['phaseSamples'],19,result['directionFrames'])
        self.assertEqual(result['quality']['status'],'candidate')

    def test_report_cannot_overwrite_manifest_or_media(self):
        for output in [self.path,self.root/'base.png',self.root/'source.mp4']:
            before=digest(output)
            with self.assertRaisesRegex(ValueError,'overwrite'):audit(self.path,self.root,output)
            self.assertEqual(before,digest(output))

    def test_optical_flow_small_shift_and_large_occlusion(self):
        try:import cv2
        except ImportError:self.skipTest('optional OpenCV unavailable')
        rng=np.random.default_rng(21)
        rgb=np.full((64,64,3),120,np.uint8)
        texture=rng.integers(20,240,(14,14,3),dtype=np.uint8)
        rgb[25:39,25:39]=texture
        left=np.dstack([rgb,np.full((64,64),255,np.uint8)])
        right=left.copy();right[:,:,:3]=120;right[25:39,27:41,:3]=texture
        frames,info=flow_bridge(left,right,3,self.motion)
        self.assertEqual(len(frames),3);self.assertLess(info['consistencyP95'],1.5)
        bad=right.copy();bad[20:44,20:44,:3]=rng.integers(0,255,(24,24,3),dtype=np.uint8)
        with self.assertRaises(ValueError):flow_bridge(left,bad,3,self.motion)

    def test_registration_uses_static_texture_not_subject(self):
        try:import cv2
        except ImportError:self.skipTest('optional OpenCV unavailable')
        rng=np.random.default_rng(7)
        ref=cv2.GaussianBlur(rng.integers(20,220,(64,64,3),dtype=np.uint8),(5,5),0)
        shift=cv2.warpAffine(ref,np.float32([[1,0,1],[0,1,0]]),(64,64),borderMode=cv2.BORDER_REFLECT)
        frame=np.dstack([shift,np.full((64,64),255,np.uint8)])
        _,report=register_translation(frame,ref,self.static,self.motion)
        self.assertLess(report['afterMAE'],report['beforeMAE'])


class PlanTests(unittest.TestCase):
    def test_closed_cycle_requires_actual_endpoint_and_reviewed_seam(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);Image.new('RGB',(16,16)).save(root/'up.png')
            (root/'input-review.md').write_text('Test pose evidence')
            s=dict(prompt='Continuous clockwise gaze orbit',first_frame='up.png',loop_frame=True,duration=5,
                   motionPlan=dict(kind='closed-orbit',coordinateSystem='screen',path='clockwise',seamDirection='up',
                                   seamPoseVerified=True,evidence='input-review.md',durationReason='Existing supported pilot setting'))
            validate_plan(s,build_content(s,root),root)
            for change in [dict(loop_frame=False),dict(duration=None),dict(motionPlan=None)]:
                bad=copy.deepcopy(s);bad.update(change)
                with self.assertRaises(ValueError):validate_plan(bad,build_content(bad,root),root)
            bad=copy.deepcopy(s);bad['motionPlan']['seamDirection']='neutral'
            with self.assertRaises(ValueError):validate_plan(bad,build_content(bad,root),root)


if __name__=='__main__':unittest.main()
