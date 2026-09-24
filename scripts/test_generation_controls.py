"""Request-level regression tests; never invoke a paid endpoint."""
import copy
import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from generate_zenmux_video import prepare_request, build_content, write_job
from generation_controls import REQUIREMENTS, review_template, validate_review, request_options, media_inventory, archive_inputs, digest
from submission_budget import check_stage, check_limits, submission_preflight


def fixture_spec(root):
    Image.new('RGB', (256,256), 'white').save(root/'input.png')
    return dict(prompt='A fixed subject follows one moving target.',first_frame='input.png',loop_frame=True,
                duration=5,extra={'prompt_expansion_mode':'disabled'},
                motionPlan=dict(kind='closed-orbit',coordinateSystem='screen',path='clockwise',
                    seamDirection='up',seamPoseVerified=True,evidence='input-review.json',durationReason='Offline fixture',
                    requirements={name:dict(expected='Fixture '+name,controls=['prompt'],verify='Inspect fixture '+name)
                                  for name in REQUIREMENTS}))


def inspected_fixture(spec, root):
    body, _, _ = prepare_request(spec,root,require_review=False)
    review = review_template(spec,body,root,root/'input.png',root/spec['motionPlan']['evidence'])
    for check in review['checks'].values():
        check.update(status='pass',notes='Synthetic offline fixture only; not a production observation.')
    (root/spec['motionPlan']['evidence']).write_text(json.dumps(review),encoding='utf-8')
    return body, review


class ControlTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.spec=fixture_spec(self.root)

    def test_review_binds_prompt_images_plan_and_original_identity(self):
        inspected_fixture(self.spec,self.root)
        prepare_request(self.spec,self.root)
        for change in ('prompt','first_frame','plan','identity'):
            with self.subTest(change=change):
                spec=copy.deepcopy(self.spec)
                if change=='prompt':spec['prompt']+=' Another action.'
                elif change=='first_frame':
                    Image.new('RGB',(256,256),'blue').save(self.root/'other.png');spec['first_frame']='other.png'
                elif change=='plan':spec['motionPlan']['requirements']['range']['expected']='Different range'
                else:Image.new('RGB',(256,256),'red').save(self.root/'input.png')
                with self.assertRaises(ValueError):prepare_request(spec,self.root)

    def test_template_never_approves_and_limited_inputs_remain_visible(self):
        body,review=inspected_fixture(self.spec,self.root)
        path=self.root/'input-review.json'
        review['checks']['featureVisibility']={'status':'unreviewed','notes':''}
        path.write_text(json.dumps(review))
        with self.assertRaisesRegex(ValueError,'featureVisibility'):prepare_request(self.spec,self.root)
        review['checks']['featureVisibility']={'status':'limited','notes':'One eye partly covered; only visible-eye checks possible.'}
        path.write_text(json.dumps(review))
        _,_,controls=prepare_request(self.spec,self.root)
        self.assertEqual(controls['inputReview']['limitations'][0]['check'],'featureVisibility')

    def test_all_reference_modalities_conflict_with_endpoint_mode(self):
        for name,value in [('reference_video','v.mp4'),('reference_audio','a.mp3'),
                           ('reference_videos',['v.mp4']),('reference_audios',['a.mp3']),('reference_images',['input.png'])]:
            with self.subTest(name=name),self.assertRaises(SystemExit):
                build_content({**self.spec,name:value},self.root)

    def test_native_expansion_is_nested_explicit_and_model_specific(self):
        body,_,_=prepare_request(self.spec,self.root,False)
        self.assertEqual(body['extra'],{'prompt_expansion_mode':'disabled'})
        self.assertNotIn('prompt_expansion_mode', {k:v for k,v in body.items() if k!='extra'})
        for change in [dict(extra={}),dict(extra={'seed':9}),dict(extra={'prompt_expansion_mode':'balance'}),
                       dict(resolution='2K'),dict(duration=4),dict(frames=120),dict(duration=True)]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                prepare_request({**self.spec,**change},self.root,False)
        base={**self.spec,'model':'minimax/minimax-h3','extra':{},'duration':4,'resolution':'2K'}
        self.assertEqual(prepare_request(base,self.root,False)[0]['resolution'],'2K')

    def test_reference_route_and_segment_route_are_representable(self):
        spec=copy.deepcopy(self.spec);spec.pop('first_frame');spec.pop('loop_frame')
        spec['motionPlan'].update(kind='reference-motion',referenceRoles='Image 1 supplies appearance; Video 1 supplies motion')
        spec['reference_video']='motion.mp4';(self.root/'motion.mp4').write_bytes(b'fixture')
        spec['reference_image']='input.png'
        body,_,_=prepare_request(spec,self.root,False)
        self.assertEqual([v.get('role') for v in body['content'][1:]],['reference_image','reference_video'])
        # Payload composition is separate from byte/media validity; bogus media cannot be reviewed.
        with self.assertRaises(ValueError):media_inventory(body['content'])
        spec=copy.deepcopy(self.spec);spec.pop('loop_frame');spec['last_frame']='input.png'
        spec['motionPlan'].update(kind='segment',startDirection='right',endDirection='left',
                                  via='through down',assembly='lower arc, then reviewed upper arc')
        prepare_request(spec,self.root,False)

    def test_nonexistent_control_cannot_be_claimed(self):
        self.spec['motionPlan']['requirements']['motion']['controls']=['reference_video']
        with self.assertRaisesRegex(ValueError,'unavailable control'):prepare_request(self.spec,self.root,False)

    def test_repair_can_replace_bad_reference_but_must_bind_new_request(self):
        body,_=inspected_fixture(self.spec,self.root)
        import cv2
        import numpy as np
        video=self.root/'bad.avi'
        writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),24,(64,64))
        self.assertTrue(writer.isOpened())
        writer.write(np.zeros((64,64,3),np.uint8));writer.release()
        (self.root/'defects.md').write_text('Endpoint already distorted; prepare replacement from original baseline.')
        context=dict(stage='repair',sourceVideo='bad.avi',defectEvidence='defects.md',
                     inputPolicy='reviewed-replacement',inputReview='input-review.json',changeReason='Correct the input pose')
        self.assertEqual(check_stage(context,self.root,[],body)['inputPolicy'],'reviewed-replacement')
        with self.assertRaises(ValueError):check_stage(context,self.root,[],{**body,'seed':3})
        video.write_bytes(b'not a video')
        with self.assertRaises((ValueError,subprocess.SubprocessError)):
            check_stage(context,self.root,[],body)

    def test_preflight_checks_budget_structure_count_and_duplicates(self):
        body,_=inspected_fixture(self.spec,self.root)
        for budget in [dict(maxSubmissions=2,attempts=[]),dict(schemaVersion=1,purpose='test',maxSubmissions=1,
                       attempts=[dict(requestedSeconds=5)],limits=dict(maxTotalSeconds=10,changeReason='test'))]:
            with self.assertRaises(ValueError):submission_preflight(budget,self.root/'out',body,None,self.root,self.root)

    def test_provider_rewrite_is_recorded_without_claiming_unchanged_or_leaking_urls(self):
        write_job(self.root/'job.json',dict(id='test',status='running'),self.root)
        self.assertEqual(json.loads((self.root/'provider-observation.json').read_text())['effectivePromptStatus'],
                         'not-returned-or-undisclosed')
        write_job(self.root/'job.json',dict(id='test',status='succeeded',content=dict(
            expanded_prompt='Use https://signed.invalid/?token=private as reference.',seed=7)),self.root)
        result=json.loads((self.root/'provider-observation.json').read_text())
        self.assertEqual(result['returnedSeed'],7);self.assertNotIn('token=private',result['expandedPrompt'])
        write_job(self.root/'job.json',dict(id='test',status='succeeded'),self.root)
        self.assertEqual(json.loads((self.root/'provider-observation.json').read_text())['effectivePromptStatus'],'provider-returned')

    def test_input_cost_awareness_does_not_reset_output_budget(self):
        body=dict(duration=5,model='minimax/minimax-h3-max',resolution='768p',content=[dict(role='reference_video')])
        budget=dict(maxSubmissions=1,attempts=[])
        with self.assertRaisesRegex(ValueError,'input costs'):check_limits(budget,body)
        budget['limits']=dict(allowReferenceMedia=True,changeReason='Reference input included in task budget')
        self.assertEqual(check_limits(budget,body)['referenceMediaCount'],1)
        budget['attempts']=[dict(requestedSeconds=5)]
        with self.assertRaisesRegex(ValueError,'exhausted'):check_limits(budget,body)

    def test_archive_keeps_exact_inputs_when_originals_are_later_changed(self):
        body,_=inspected_fixture(self.spec,self.root)
        review_path=self.root/'input-review.json';review_hash=digest(review_path)
        original=(self.root/'input.png').read_bytes()
        archive=archive_inputs(self.root,body,review_path,review_hash)
        self.assertEqual([r['role'] for r in archive['media']],['first_frame','last_frame'])
        Image.new('RGB',(256,256),'red').save(self.root/'input.png')
        for record in [*archive['media'],archive['identityBaseline']]:
            self.assertEqual((self.root/record['path']).read_bytes(),original)
            self.assertEqual(digest(self.root/record['path']),record['sha256'])
        with self.assertRaisesRegex(ValueError,'baseline changed'):
            archive_inputs(self.root,body,review_path,review_hash)
        review_path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'review changed'):
            archive_inputs(self.root,body,review_path,review_hash)


if __name__=='__main__':unittest.main()
