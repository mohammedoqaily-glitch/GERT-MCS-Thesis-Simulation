import copy
import unittest

from sensitivity.model import load_authoritative_model, perturb_probability, scale_duration


class SingleParameterChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_authoritative_model()

    def test_probability_change_is_confined_to_one_xor_group(self):
        original = {arc["arc_tag"]: copy.deepcopy(arc) for arc in self.model.arcs}
        changed = perturb_probability(self.model, "e45", 0.8)
        for arc in changed.arcs:
            if arc["from_node"] != "S4":
                self.assertEqual(original[arc["arc_tag"]], arc)

    def test_duration_change_only_changes_target_triplet(self):
        original = {arc["arc_tag"]: copy.deepcopy(arc) for arc in self.model.arcs}
        changed = scale_duration(self.model, "e45", 1.1)
        for arc in changed.arcs:
            if arc["arc_tag"] == "e45":
                for actual, expected in zip((arc["o"], arc["ml"], arc["p"]), (55.0, 66.0, 88.0)):
                    self.assertAlmostEqual(actual, expected)
            else:
                self.assertEqual(original[arc["arc_tag"]], arc)

    def test_invalid_duration_scale_fails(self):
        with self.assertRaises(ValueError):
            scale_duration(self.model, "e45", 0)
