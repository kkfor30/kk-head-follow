import unittest
from propose_phase_map import redistribute


class TimingTests(unittest.TestCase):
    def test_preserves_anchors_and_compresses_hold(self):
        anchors=[10,14,18,22,26,30,34,38]
        motion=[.01,.01,1,1]+[1]*24
        points=dict(redistribute(anchors,motion))
        for i,frame in enumerate(anchors):self.assertEqual(points[frame],i*45)
        self.assertLess(points[12],10)
        self.assertTrue(all(points[a]<points[b] for a,b in zip(points,list(points)[1:])))

    def test_all_static_does_not_divide_by_zero(self):
        points=redistribute(list(range(8)),[0]*7)
        self.assertEqual(points[-1],[7,315.])

    def test_bad_order_or_nan_cannot_create_map(self):
        with self.assertRaises(ValueError):redistribute([0,1,2,3,4,5,6,6],[1]*6)
        with self.assertRaises(ValueError):redistribute(list(range(8)),[float('nan')]*7)
