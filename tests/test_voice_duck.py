import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import voice as voice_mod  # noqa: E402


class DuckTests(unittest.TestCase):
    def make(self, level):
        v = voice_mod.Voice.__new__(voice_mod.Voice)
        v.config, v._duck_lock, v._ducked, v._duck_until = {}, threading.Lock(), None, 0.0
        self.vol = {'level': level, 'muted': False}
        return v

    def run_with_pc(self, fn):
        def set_level(x):
            self.vol['level'] = x
        with patch.object(voice_mod.pc, 'volume_get', lambda: dict(self.vol)), \
             patch.object(voice_mod.pc, 'volume_set', set_level):
            fn()

    def test_music_goes_down_while_listening_and_comes_back(self):
        v = self.make(68)
        self.run_with_pc(v.duck)
        self.assertEqual(self.vol['level'], 20)
        self.run_with_pc(v.unduck)
        self.assertEqual(self.vol['level'], 68)

    def test_volume_you_changed_meanwhile_is_kept(self):
        v = self.make(68)
        self.run_with_pc(v.duck)
        self.vol['level'] = 45
        self.run_with_pc(v.unduck)
        self.assertEqual(self.vol['level'], 45)

    def test_low_or_muted_volume_is_left_alone(self):
        v = self.make(15)
        self.run_with_pc(v.duck)
        self.assertEqual(self.vol['level'], 15)
        self.assertIsNone(v._ducked)


if __name__ == '__main__':
    unittest.main()
