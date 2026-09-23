import base64
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from PIL import Image
from submission_budget import check_stage, verify_repair_inputs
from prepare_head_mattes import mask_metrics


class BindingTests(unittest.TestCase):
    def test_repair_accepts_actual_frame_rejects_other_picture(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.avi'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'MJPG'),24,(64,64))
            self.assertTrue(writer.isOpened())
            for _ in range(3):writer.write(np.full((64,64,3),(30,70,190),np.uint8))
            writer.release()
            cap=cv2.VideoCapture(str(source));ok,frame=cap.read();cap.release();self.assertTrue(ok)
            def body(rgb):
                out=io.BytesIO();Image.fromarray(rgb).save(out,format='PNG')
                return {'content':[{'type':'image_url','role':'first_frame','image_url':{'url':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()}}]}
            context={'sourceInputs':[{'role':'first_frame','frame':0}]}
            verify_repair_inputs(source,context,body(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)))
            with self.assertRaisesRegex(ValueError,'does not match'):
                verify_repair_inputs(source,context,body(np.zeros((64,64,3),np.uint8)))
            source.write_bytes(b'not a video')
            with self.assertRaisesRegex(ValueError,'not decodable'):
                verify_repair_inputs(source,context,body(np.zeros((64,64,3),np.uint8)))

    def test_expansion_must_use_actual_pilot_source_and_scene(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'pilot';out.mkdir();(out/'result.mp4').write_bytes(b'pilot result')
            manifest=root/'manifest.json'
            m=dict(sceneId='scene-a',sourceHashes={'source.mp4':hashlib.sha256(b'pilot result').hexdigest()})
            manifest.write_text(json.dumps(m))
            attempts=[dict(stage='pilot',requestSha256='request-a',outputDir='pilot')]
            context=dict(stage='expansion',root='.',pilotManifest='manifest.json',pilotRequestSha256='request-a',sceneId='scene-a')
            # Certificate verification has separate real artifact tests; isolate the new source association.
            with patch('validate_head_manifest.validate'):
                self.assertEqual(check_stage(context,root,attempts)['stage'],'expansion')
                with self.assertRaisesRegex(ValueError,'sceneId'):
                    check_stage({**context,'sceneId':'other'},root,attempts)
                m['sourceHashes']={'other.mp4':hashlib.sha256(b'other result').hexdigest()};manifest.write_text(json.dumps(m))
                with self.assertRaisesRegex(ValueError,'recorded pilot video'):
                    check_stage(context,root,attempts)

    def test_mask_bottom_attachment_is_not_head_clipping(self):
        alpha=np.zeros((20,20),np.uint8);alpha[5:,5:15]=255
        self.assertFalse(mask_metrics(alpha)['topOrSideClipped'])
        alpha[5,0]=255
        self.assertTrue(mask_metrics(alpha)['topOrSideClipped'])
