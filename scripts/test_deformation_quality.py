import unittest
import numpy as np
from deformation_quality import inspect_inverse_map


class MapTests(unittest.TestCase):
    def setUp(self):
        y,x=np.mgrid[:30,:30];self.grid=np.dstack([x,y]).astype(float)
        self.region=np.zeros((30,30),bool);self.region[5:25,5:25]=True

    def test_interior_translation_and_identity(self):
        self.assertTrue(inspect_inverse_map(self.grid,self.region)['passed'])
        self.assertTrue(inspect_inverse_map(self.grid+[2,1],self.region)['passed'])

    def test_fold_and_missing_source_are_rejected(self):
        flipped=self.grid.copy();flipped[:,:,0]=29-flipped[:,:,0]
        self.assertFalse(inspect_inverse_map(flipped,self.region)['passed'])
        self.assertGreater(inspect_inverse_map(self.grid+[20,0],self.region)['outsidePixels'],0)

    def test_protected_head_cannot_move(self):
        self.assertFalse(inspect_inverse_map(self.grid+[1,0],self.region,self.region)['passed'])

    def test_nonfinite_and_empty_cannot_approve(self):
        with self.assertRaises(ValueError):inspect_inverse_map(self.grid*np.nan,self.region)
        with self.assertRaises(ValueError):inspect_inverse_map(self.grid,np.zeros_like(self.region))
