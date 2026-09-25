"""Pixel-level fixtures for representative composition; not visual acceptance."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image
from compile_head_atlas import build, frames
from review_scene_samples import review


class SceneSamplesTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc=size=64x64:rate=10:duration=1.6',
                        '-c:v','ffv1',str(self.root/'source.mkv')],check=True,capture_output=True)
        Image.new('RGB',(80,80),'#181818').save(self.root/'base.png')
        self.spec=dict(sceneId='fixture',baseImage='base.png',sourceVideo='source.mkv',sourceSize=[80,80],
            crop=[10,10,32,32],motionCrop=[16,8,32,32],renderSize=64,eye=[26,26],
            backgroundOwner='scene',backgroundMode='preserve',feather=[4,4,4,4],
            mainAnchors=list(range(0,16,2)),outputDir='atlas')

    def test_sample_pixels_match_compiler_and_are_not_approved(self):
        build(self.spec,self.root)
        report=review(self.spec,self.root,self.root/'samples',[0,4,15])
        sheet=Image.open(self.root/'atlas/sheet-0.png').convert('RGBA')
        for i in (0,4,15):
            expected=sheet.crop((i%8*32,i//8*32,i%8*32+32,i//8*32+32))
            with Image.open(self.root/f'samples/source-{i:06}-patch.png') as actual:
                np.testing.assert_array_equal(actual,expected)
        self.assertEqual(report['status'],'unreviewed')
        self.assertTrue(all(s['gaze']=='unknown' and s['occlusion']=='unknown' for s in report['samples']))
        with self.assertRaisesRegex(ValueError,'preserve existing'):review(self.spec,self.root,self.root/'samples',[1])

    def test_dark_and_textured_plate_mattes_occlusion_and_old_head_removal(self):
        for name in ('dark','texture'):
            plate=np.full((80,80,3),20,dtype=np.uint8)
            if name=='texture':plate[::2,:,0]=160;plate[:,::3,1]=90
            Image.fromarray(plate).save(self.root/'plate.png')
            base=plate.copy();base[10:42,10:42]=255;Image.fromarray(base).save(self.root/'base.png')
            mask=np.zeros((64,64),dtype=np.uint8);mask[16:32,24:40]=255
            Image.fromarray(mask).save(self.root/'mask.png')
            overlay=Image.new('RGBA',(80,80));overlay.paste((22,77,99,255),(25,25,30,30));overlay.save(self.root/'foreground.png')
            spec={**self.spec,'backgroundOwner':'page','cleanPlate':'plate.png','sampleMattes':{'3':'mask.png'},'foregroundOverlay':'foreground.png'}
            with self.subTest(background=name):
                review(spec,self.root,self.root/name,[3])
                actual=np.asarray(Image.open(self.root/f'{name}/source-000003-scene.png').convert('RGB'))
                # Transparent areas reveal the clean plate, not the static white old head.
                np.testing.assert_array_equal(actual[11,11],plate[11,11])
                np.testing.assert_array_equal(actual[26,26],[22,77,99])
                np.testing.assert_array_equal(actual[60,60],base[60,60])

    def test_missing_alpha_invalid_geometry_or_frame_never_publishes(self):
        Image.new('RGB',(80,80),'black').save(self.root/'plate.png')
        cases=[({'backgroundOwner':'page','cleanPlate':'plate.png'},[0],'no alpha'),
               ({'crop':[70,0,32,32]},[0],'outside'),({},[99],'outside'),({},[0,0],'unique'),
               ({'renderSize':[128,64]},[0],'aspect ratio'),
               ({'backgroundMode':'fit-edge-light'},[0],'simple light')]
        for j,(change,ids,message) in enumerate(cases):
            target=self.root/f'bad-{j}'
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,message):
                review({**self.spec,**change},self.root,target,ids)
            self.assertFalse(target.exists())

    def test_vfr_selects_native_indices_without_duplicate_frames(self):
        subprocess.run(['ffmpeg','-v','error','-i',str(self.root/'source.mkv'),'-vf',
            "setpts='if(lt(N,8),N,8+(N-8)*2)/(10*TB)'",'-fps_mode','vfr','-c:v','ffv1',str(self.root/'vfr.mkv')],check=True,capture_output=True)
        spec={**self.spec,'sourceVideo':'vfr.mkv'}
        report=review(spec,self.root,self.root/'vfr',[7,8,15])
        self.assertEqual([s['sourceFrame'] for s in report['samples']],[7,8,15])
        self.assertAlmostEqual(float(report['samples'][-1]['timestamp']),2.2)
        expected=frames(self.root/'vfr.mkv',(64,64))[15][8:40,16:48]
        actual=np.asarray(Image.open(self.root/'vfr/source-000015-patch.png'))
        np.testing.assert_array_equal(actual[8:24,8:24],expected[8:24,8:24])

    def test_sample_only_layers_cannot_be_silently_ignored_by_compiler(self):
        for name in ('sampleMattes','foregroundOverlay'):
            with self.subTest(field=name),self.assertRaisesRegex(ValueError,'prototypes'):
                build({**self.spec,name:{}},self.root)
            self.assertFalse((self.root/'atlas').exists())


if __name__=='__main__':unittest.main()
