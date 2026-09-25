"""Verify actual request text, input binding and offline prompt export."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from build_motion_prompt import build
from generate_zenmux_video import build_content, prepare_request
from motion_prompt import resolve_prompt
from test_generation_controls import fixture_spec, inspected_fixture


def structured_spec(root):
    spec=fixture_spec(root); spec.pop('prompt')
    spec['motionPlan']['requirements']['rest']['controls']=['runtime']
    spec['motionPlan']['promptSpec']=dict(subjectDescription='the illustrated character',
        startPose='A readable upward gaze with lifted chin', endPose='The same upward gaze and expression',
        allowedMotion='Head yaw, chin elevation and visible eyes following the same target',
        framing='The complete head, neck and shoulders remain inside the frame',
        background=dict(mode='scene-preserve',description='The actual dark blue wall in the supplied image'),
        staticContext='The neighboring seated pet and furniture')
    return spec


class PromptTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.spec=structured_spec(self.root)

    def test_export_matches_actual_request_and_changes_with_requirements(self):
        path=self.root/'request.json';path.write_text(json.dumps(self.spec),encoding='utf-8')
        report=build(path,self.root/'bundle')
        body,_,controls=prepare_request(self.spec,self.root,False)
        self.assertEqual((self.root/'bundle/prompt.txt').read_text(encoding='utf-8'),body['content'][0]['text'])
        self.assertEqual(report['requirementsIncluded'],controls['promptAssembly']['requirementsIncluded'])
        self.assertNotIn('rest',report['requirementsIncluded'])
        self.assertNotIn('Fixture rest',body['content'][0]['text'])
        inspected_fixture(self.spec,self.root)
        changed=copy.deepcopy(self.spec);changed['motionPlan']['requirements']['gaze']['expected']='A visible upward iris shift'
        self.assertIn('A visible upward iris shift',build_content(changed,self.root)[0]['text'])
        with self.assertRaisesRegex(ValueError,'stale'):prepare_request(changed,self.root)
        with self.assertRaisesRegex(ValueError,'preserve existing'):build(path,self.root/'bundle')

    def test_all_routes_use_plan_and_real_media_roles(self):
        for kind in ('closed-orbit','entry-orbit','upper-arc','segment','reference-motion','diagnostic'):
            spec=copy.deepcopy(self.spec);p=spec['motionPlan'];p['kind']=kind
            if kind=='entry-orbit':p.update(firstPose='neutral',cycleStart='up',cycleEnd='up',excludeEntry=True)
            if kind in ('upper-arc','segment'):
                spec.pop('loop_frame');spec['last_frame']='input.png'
                p.update(startDirection='upper-left',endDirection='upper-right',via='up',assembly='upper sweep')
            if kind=='reference-motion':
                spec.pop('first_frame');spec.pop('loop_frame');spec['reference_image']='input.png'
                spec['reference_video']='motion.mp4';(self.root/'motion.mp4').write_bytes(b'payload assembly only')
                p['referenceRoles']='Image 1 supplies identity; Video 1 supplies the motion'
            with self.subTest(kind=kind):
                body,_,controls=prepare_request(spec,self.root,False)
                self.assertEqual(controls['promptAssembly']['recipe'],kind)
                self.assertEqual(body['content'][0]['text'],resolve_prompt(spec,self.root)[0])
                points=controls['promptAssembly']['checkpoints']
                if kind=='upper-arc':self.assertEqual([v['direction'] for v in points],['upper-left','up','upper-right'])
                if kind=='entry-orbit':self.assertEqual([v['direction'] for v in points][1:-1],
                    ['up','upper-right','right','lower-right','down','lower-left','left','upper-left','up'])

    def test_ambiguous_or_unfinished_prompt_never_silently_submits(self):
        for field,value in [('prompt','Different instructions'),('prompt_file','old.txt')]:
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'silently override'):
                build_content({**self.spec,field:value},self.root)
        spec=copy.deepcopy(self.spec);spec['motionPlan']['promptSpec']['startPose']='[ACTUAL START POSE]'
        with self.assertRaisesRegex(ValueError,'placeholder'):build_content(spec,self.root)
        spec=copy.deepcopy(self.spec);spec['motionPlan']['promptSpec']['route']='right to left'
        with self.assertRaisesRegex(ValueError,'unknown promptSpec'):build_content(spec,self.root)

    def test_media_contracts_are_still_enforced(self):
        self.spec.pop('loop_frame')
        with self.assertRaisesRegex(ValueError,'actual last_frame'):prepare_request(self.spec,self.root,False)
        self.spec['loop_frame']=True
        (self.root/'input.png').unlink()
        with self.assertRaises(SystemExit):prepare_request(self.spec,self.root,False)

    def test_timing_and_background_are_explicit(self):
        p=self.spec['motionPlan'];p.update(kind='entry-orbit',firstPose='neutral',cycleStart='up',cycleEnd='up',excludeEntry=True)
        p['promptSpec']['timing']={'entryEnd':.1,'cycleEnd':1}
        self.assertEqual(resolve_prompt(self.spec,self.root)[1]['checkpoints'][-1],dict(fraction=1.,direction='up'))
        for timing in ({'entryEnd':.8,'cycleEnd':.2},{'entryEnd':True},{'entryEnd':float('nan')},{'atSecond':1}):
            p['promptSpec']['timing']=timing
            with self.subTest(timing=timing),self.assertRaises(ValueError):resolve_prompt(self.spec,self.root)
        p['promptSpec'].pop('timing')
        p['promptSpec']['background']=dict(mode='chroma-key',description='No clothing matches the key color',keyColor='#FF00FF')
        self.assertIn('#FF00FF',resolve_prompt(self.spec,self.root)[0])
        p['promptSpec']['background']['mode']='alpha-matte'
        with self.assertRaisesRegex(ValueError,'keyColor'):resolve_prompt(self.spec,self.root)

    def test_prompt_only_targets_are_sent_and_compositor_targets_stay_local(self):
        requirements=self.spec['motionPlan']['requirements']
        requirements['fixedParts']=dict(expected='Restore the texture behind the old head',controls=['compositing'],verify='Inspect the clean plate')
        prompt,report=resolve_prompt(self.spec,self.root)
        self.assertNotIn(requirements['fixedParts']['expected'],prompt)
        self.assertIn('fixedParts',report['requirementsNotSent'])
        requirements['fixedParts']['controls'].append('prompt')
        self.assertIn(requirements['fixedParts']['expected'],resolve_prompt(self.spec,self.root)[0])

    def test_manual_route_remains_available(self):
        spec=fixture_spec(self.root)
        self.assertEqual(resolve_prompt(spec,self.root)[0],spec['prompt'])
        text=spec.pop('prompt');spec['prompt_file']='prompt.txt'
        (self.root/'prompt.txt').write_text(text,encoding='utf-8')
        self.assertEqual(resolve_prompt(spec,self.root)[0],text)

    def test_bundled_recipes_build_requests_with_local_fixture_media(self):
        from PIL import Image
        for path in sorted((Path(__file__).resolve().parents[1]/'references').glob('zenmux*example.json')):
            spec=json.loads(path.read_text(encoding='utf-8'))
            for key in ('first_frame','last_frame','reference_images','reference_videos'):
                values=spec.get(key,[])
                for name in values if isinstance(values,list) else [values]:
                    target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True)
                    if key=='reference_videos':target.write_bytes(b'payload composition fixture only')
                    else:Image.new('RGB',(256,256),'gray').save(target)
            with self.subTest(recipe=path.name):
                body,_,_=prepare_request(spec,self.root,False)
                self.assertLessEqual(len(body['content'][0]['text']),7000)
                self.assertEqual(len(spec['motionPlan']['subjects']),1)


if __name__=='__main__':unittest.main()
