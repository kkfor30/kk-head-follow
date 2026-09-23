import unittest
import tempfile,os,shutil,subprocess,hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from densify_head_video import sample_sources,constant_rate


class DensifyTests(unittest.TestCase):
    def test_native_and_half_time_provenance(self):
        rows=sample_sources(4)
        self.assertEqual(len(rows),7)
        self.assertEqual([r['parents'] for r in rows],[[0],[0,1],[1],[1,2],[2],[2,3],[3]])
        self.assertEqual([r['fraction'] for r in rows],[0,.5,0,.5,0,.5,0])
        self.assertFalse(any(r['parents']==[3,0] for r in rows))

    def test_vfr_or_missing_frames_refused(self):
        constant_rate([0,1/24,2/24,3/24],24)
        for times in ([0,.04,.12],[0,0,.04],[0,float('nan'),.08]):
            with self.assertRaises(ValueError):constant_rate(times,25)
        with self.assertRaises(ValueError):sample_sources(2)

    def test_real_interpolation_timing_and_lineage(self):
        ffmpeg=os.environ.get('KK_TEST_FFMPEG') or shutil.which('ffmpeg')
        ffprobe=os.environ.get('KK_TEST_FFPROBE') or shutil.which('ffprobe')
        if not ffmpeg or not ffprobe:self.skipTest('FFmpeg/FFprobe required for real interpolation test')
        from densify_head_video import densify
        from video_lineage import load_lineage,annotate,validate_lineage
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i in range(8):
                im=Image.new('RGB',(96,96),'#304050')
                ImageDraw.Draw(im).rectangle((16+i*3,24,44+i*3,64),fill='#eed080')
                im.save(root/f'{i:06}.png')
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-framerate','4',
                            '-i',str(root/'%06d.png'),'-c:v','ffv1',str(root/'native.mkv')],check=True)
            r=densify(root/'native.mkv',root/'dense',ffmpeg,ffprobe)
            for i in range(8):
                self.assertEqual((root/f'dense/native/{i:06}.png').read_bytes(),(root/f'dense/frames/{2*i:06}.png').read_bytes())
            for i in range(7):
                a=np.array(Image.open(root/f'dense/frames/{2*i+1:06}.png'))
                _,xs=np.where(a[:,:,0]>150)
                self.assertLess(abs(xs.mean()-(31.5+i*3)),1.1)
            report,meta=load_lineage(root,'dense/lineage.json','native.mkv','dense/candidate.mkv')
            origins=[dict(source='dense/candidate.mkv',frame=i) for i in range(15)]
            annotate(origins,report['frames'],'native.mkv','dense/candidate.mkv')
            m=dict(frameSources=origins,frameLineage=meta)
            validate_lineage(root,m)
            origins[1].pop('synthesized')
            with self.assertRaises(ValueError):validate_lineage(root,m)
            with self.assertRaises(ValueError):densify(root/'native.mkv',root/'dense',ffmpeg,ffprobe)
            (root/'native.mkv').write_bytes(b'changed source')
            with self.assertRaises(ValueError):load_lineage(root,'dense/lineage.json','native.mkv','dense/candidate.mkv')


if __name__=='__main__':unittest.main()
