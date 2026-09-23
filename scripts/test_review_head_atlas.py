import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from review_head_atlas import review


class SceneReviewTest(unittest.TestCase):
    def test_composites_page_on_plate_and_scene_on_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            Image.new('RGB',(8,8),'red').save(root/'base.png')
            Image.new('RGB',(8,8),'blue').save(root/'plate.png')
            Image.new('RGBA',(2,2),(0,0,0,0)).save(root/'sheet.png')
            m=dict(baseImage='base.png',baseImageSha256=hashlib.sha256((root/'base.png').read_bytes()).hexdigest(),
                crop=[3,3,2,2],frameCount=1,columns=1,framesPerSheet=1,sheets=['sheet.png'],
                frameSources=[dict(source='source.mp4',frame=0,synthesized=True)],
                background=dict(owner='scene'))
            for owner,color in [('scene',(255,0,0)),('page',(0,0,255))]:
                m['background']['owner']=owner
                m['cleanPlate']=dict(path='plate.png')
                (root/'manifest.json').write_text(json.dumps(m))
                report=review(root/'manifest.json',root,root/owner)
                image=Image.open(root/owner/'scene-sweep.webp').convert('RGB')
                self.assertEqual(image.getpixel((3,3)),color)
                self.assertEqual(image.getpixel((0,0)),(255,0,0))
                self.assertEqual(report['syntheticFrames'],[0])
                self.assertEqual(report['browserInteraction'],'not-tested')
            m['baseImageSha256']='wrong'
            (root/'manifest.json').write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                review(root/'manifest.json',root,root/'invalid')


if __name__=='__main__':unittest.main()
