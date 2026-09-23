import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from compose_layered_scene import build, verify


class LayeredSceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        Image.new('RGB', (40, 30), (20, 40, 60)).save(self.root/'room.png')
        for name, color in [('actor', (220, 30, 10, 255)), ('other', (0, 255, 0, 255)), ('shadow', (0, 0, 0, 128))]:
            im = Image.new('RGBA', (6, 6))
            im.paste(color, (1, 1, 5, 5))
            im.save(self.root/f'{name}.png')
        self.spec = dict(sceneId='test', background='room.png', layers=[
            dict(id='shadow', kind='underlay', image='shadow.png', rect=[2, 2, 6, 6]),
            dict(id='actor', kind='subject', image='actor.png', rect=[2, 2, 6, 6]),
            dict(id='other', kind='subject', image='other.png', rect=[20, 2, 6, 6])])
        self.path = self.root/'spec.json'
        self.out = self.root/'out'

    def run_build(self):
        self.path.write_text(json.dumps(self.spec), encoding='utf-8')
        return build(self.path, self.root, self.out)

    def test_plates_remove_only_requested_subject_and_preserve_shadow(self):
        self.run_build()
        with Image.open(self.out/'static.png') as im:
            self.assertEqual(im.getpixel((4, 4)), (220, 30, 10))
        with Image.open(self.out/'clean-actor.png') as im:
            self.assertEqual(im.getpixel((4, 4)), (10, 20, 30))
            self.assertEqual(im.getpixel((22, 4)), (0, 255, 0))
        self.assertTrue(verify(self.out/'scene.json', self.root)['valid'])

    def test_changed_asset_and_changed_output_invalidate_record(self):
        self.run_build()
        target = self.root/'actor.png'
        saved = target.read_bytes()
        Image.new('RGBA', (6, 6), 'blue').save(target)
        with self.assertRaisesRegex(ValueError, 'input changed'):
            verify(self.out/'scene.json', self.root)
        target.write_bytes(saved)
        Image.new('RGB', (40, 30), 'red').save(self.out/'static.png')
        with self.assertRaisesRegex(ValueError, 'output changed'):
            verify(self.out/'scene.json', self.root)

    def test_reject_overlap_without_writing_outputs(self):
        self.spec['layers'][-1]['rect'] = [5, 2, 6, 6]
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.run_build()
        self.assertFalse(self.out.exists())

    def test_reject_distortion_opaque_layer_and_outside_scene(self):
        self.spec['layers'][1]['rect'] = [2, 2, 12, 6]
        with self.assertRaisesRegex(ValueError, 'aspect ratio'):
            self.run_build()
        self.spec['layers'][1]['rect'] = [38, 2, 6, 6]
        with self.assertRaisesRegex(ValueError, 'fit inside'):
            self.run_build()
        self.spec['layers'][1]['rect'] = [2, 2, 6, 6]
        Image.new('RGB', (6, 6), 'red').save(self.root/'actor.png')
        with self.assertRaisesRegex(ValueError, 'transparency'):
            self.run_build()

    def test_reject_foreground_and_do_not_overwrite(self):
        self.spec['layers'][-1]['kind'] = 'foreground'
        with self.assertRaisesRegex(ValueError, 'foreground'):
            self.run_build()
        self.spec['layers'][-1]['kind'] = 'subject'
        self.run_build()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.run_build()

    def test_contract_geometry_tamper_rejected(self):
        self.run_build()
        path = self.out/'scene.json'
        record = json.loads(path.read_text('utf-8'))
        record['subjects'][0]['rect'][0] += 1
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'geometry'):
            verify(path, self.root)


if __name__ == '__main__':
    unittest.main()
