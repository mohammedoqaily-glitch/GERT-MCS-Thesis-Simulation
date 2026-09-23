import math
import unittest

from sensitivity.model import load_authoritative_model, perturb_probability, routing_groups


class ProbabilityRenormalisationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_authoritative_model()

    def test_every_group_sums_to_one_after_perturbation(self):
        for group in routing_groups(self.model).values():
            for target in group:
                changed = perturb_probability(self.model, target["arc_tag"], min(0.99, target["probability"] * 1.1))
                changed_group = routing_groups(changed)[target["from_node"]]
                self.assertTrue(math.isclose(sum(arc["probability"] for arc in changed_group), 1.0, abs_tol=1e-12))

    def test_non_target_relative_proportions_are_preserved(self):
        group = routing_groups(self.model)["S2"]
        changed = perturb_probability(self.model, "e24", 0.75)
        changed_group = routing_groups(changed)["S2"]
        original = {arc["arc_tag"]: arc["probability"] for arc in group if arc["arc_tag"] != "e24"}
        modified = {arc["arc_tag"]: arc["probability"] for arc in changed_group if arc["arc_tag"] != "e24"}
        tags = list(original)
        for tag in tags[1:]:
            self.assertAlmostEqual(original[tag] / original[tags[0]], modified[tag] / modified[tags[0]], places=12)

    def test_invalid_probability_fails(self):
        with self.assertRaises(ValueError):
            perturb_probability(self.model, "e12", 1.2)
