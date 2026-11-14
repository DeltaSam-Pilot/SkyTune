"""Frame Hold calculates detail from mocked frame rate and altitude. It never writes a file."""
import os, shutil, tempfile, unittest
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
S24 = os.path.join(os.path.dirname(__file__), "sample_UserCfg_2024.opt")

class MockFeed:
    """Stand-in for a live simulator. Tests pass the samples. Nothing is read from a process."""
    def __init__(self, samples):
        self.samples = list(samples)
    def read(self):
        if not self.samples:
            return {"fps": None, "altitude_ft": None}
        return self.samples.pop(0)

class FrameHoldMath(unittest.TestCase):
    def test_low_frames_step_down_and_stop_at_the_minimum(self):
        hold = m.FrameHold(target_fps=60, terrain=(1.0, 2.0), objects=(1.0, 1.5), step=0.5)
        hold.start(2.0, 1.5)
        first = hold.update(fps=20)
        self.assertEqual(first["terrain"], 1.5)
        self.assertEqual(first["objects"], 1.0)
        self.assertFalse(first["written"])
        second = hold.update(fps=20)
        self.assertEqual(second["terrain"], 1.0)
        self.assertEqual(hold.update(fps=20)["terrain"], 1.0)
    def test_high_frames_step_up_and_stop_at_the_maximum(self):
        hold = m.FrameHold(target_fps=30, terrain=(1.0, 1.2), objects=(0.5, 0.7), step=0.1)
        hold.start(1.0, 0.5)
        first = hold.update(fps=80)
        self.assertEqual(first["terrain"], 1.1)
        self.assertEqual(first["objects"], 0.6)
        self.assertEqual(hold.update(fps=80)["terrain"], 1.2)
        self.assertEqual(hold.update(fps=80)["objects"], 0.7)
        self.assertEqual(hold.update(fps=80)["objects"], 0.7)
    def test_ground_stays_low_even_when_frames_are_high(self):
        hold = m.FrameHold(target_fps=30, terrain=(0.5, 2.0), objects=(0.4, 1.5),
                           altitude_mode=True, ground_ft=2000, cruise_ft=10000, step=0.2)
        hold.start(2.0, 1.5)
        out = hold.update(fps=120, altitude_ft=400)
        self.assertEqual(out["terrain"], 0.5)
        self.assertEqual(out["objects"], 0.4)
        self.assertIn("ground", out["reason"])
    def test_cruise_can_rise_and_a_slow_sample_pulls_it_back(self):
        hold = m.FrameHold(target_fps=45, terrain=(0.5, 2.0), objects=(0.5, 1.5),
                           altitude_mode=True, ground_ft=2000, cruise_ft=10000, step=0.5)
        hold.start(0.5, 0.5)
        up = hold.update(fps=90, altitude_ft=25000)
        self.assertEqual(up["terrain"], 1.0)
        self.assertIn("cruise", up["reason"])
        down = hold.update(fps=10, altitude_ft=25000)
        self.assertEqual(down["terrain"], 0.5)
        self.assertIn("under the target", down["reason"])
    def test_a_missing_frame_rate_is_not_invented(self):
        hold = m.FrameHold(target_fps=60, terrain=(1.0, 2.0), objects=(1.0, 1.5))
        hold.start(1.4, 1.2)
        out = hold.update(fps=None, altitude_ft=None)
        self.assertEqual(out["terrain"], 1.4)
        self.assertIn("No frame rate", out["reason"])
        self.assertIsNone(out.get("fps"))
    def test_stop_returns_the_original_values(self):
        hold = m.FrameHold(target_fps=30, terrain=(0.5, 3.0), objects=(0.5, 2.0), step=0.4)
        hold.start(1.7, 1.1)
        hold.update(fps=5)
        self.assertEqual(hold.stop(), (1.7, 1.1))
        self.assertFalse(hold.active)
    def test_bad_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            m.FrameHold(target_fps=0)
        hold = m.FrameHold(target_fps=30)
        hold.start(1, 1)
        with self.assertRaises(ValueError):
            hold.update(fps=-1)
    def test_mocked_feed_and_no_file_write(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "UserCfg.opt")
        shutil.copy(S24, path)
        before = open(path, "rb").read()
        cfg = m.UserCfg.load(path)
        feed = MockFeed([{"fps": 12, "altitude_ft": 800}, {"fps": 70, "altitude_ft": 18000}])
        hold = m.FrameHold(target_fps=40, terrain=(0.5, 2.0), objects=(0.5, 1.5),
                           altitude_mode=True, ground_ft=2000, cruise_ft=10000, step=0.3)
        hold.start(float(cfg.get(m.TERRAIN_LOD)), float(cfg.get(m.OBJECT_LOD)))
        first = feed.read()
        low = hold.update(fps=first["fps"], altitude_ft=first["altitude_ft"])
        self.assertLess(low["terrain"], 2.0)
        self.assertIsNone(m.frame_hold_block(True) and None)
        self.assertIn("running", m.frame_hold_block(True))
        self.assertIsNone(m.frame_hold_block(False))
        second = feed.read()
        high = hold.update(fps=second["fps"], altitude_ft=second["altitude_ft"])
        chosen = m.frame_hold_values(high, cfg)
        self.assertIn(m.TERRAIN_LOD, chosen)
        self.assertIn(m.OBJECT_LOD, chosen)
        self.assertEqual(open(path, "rb").read(), before)
        shutil.rmtree(folder)
    def test_ranges_cannot_leave_the_known_limits(self):
        hold = m.FrameHold(target_fps=30, terrain=(0.01, 50), objects=(-2, 9))
        self.assertEqual(hold.terrain_range, (0.1, 8.0))
        self.assertEqual(hold.object_range, (0.1, 4.0))
