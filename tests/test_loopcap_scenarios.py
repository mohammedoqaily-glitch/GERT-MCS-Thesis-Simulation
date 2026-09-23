import unittest

from sensitivity.model import LOOP_TAGS, load_authoritative_model, set_loop_cap, simulate_gert


class LoopCapScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_authoritative_model()

    def test_caps_are_nonnegative_integers(self):
        for tag in LOOP_TAGS:
            for cap in (1, 2, 3):
                changed = set_loop_cap(self.model, tag, cap)
                target = next(arc for arc in changed.arcs if arc["arc_tag"] == tag)
                self.assertIsInstance(target["loop_cap"], int)
                self.assertGreaterEqual(target["loop_cap"], 0)

    def test_cap_is_never_exceeded(self):
        changed = set_loop_cap(self.model, "e22", 1)
        result = simulate_gert(changed, 2000, 42)
        self.assertLessEqual(int(result.loop_counts[:, 0].max()), 1)

    def test_invalid_cap_fails(self):
        with self.assertRaises(ValueError):
            set_loop_cap(self.model, "e22", -1)
