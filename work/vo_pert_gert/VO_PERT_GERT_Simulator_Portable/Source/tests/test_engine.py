import math
import unittest

from vo_pert_gert.engine import LAMBDA, alpha_beta, default_case, nearest_rank, run_gert, run_pert, sample_duration
import random


class EngineTests(unittest.TestCase):
    def test_alpha_beta_lambda(self):
        a, b = alpha_beta(1, 3, 9)
        self.assertEqual(LAMBDA, 4)
        self.assertAlmostEqual(a, 2)
        self.assertAlmostEqual(b, 4)

    def test_ceiling_each_draw_example(self):
        self.assertEqual(math.ceil(2.3) + math.ceil(2.6), 6)
        self.assertNotEqual(math.ceil(2.3 + 2.6), 6)

    def test_sample_duration_is_integer_ceiling(self):
        d = sample_duration(random.Random(42), default_case().pert[0])
        self.assertIsInstance(d, int)

    def test_pert_executes_once_per_activity(self):
        case = default_case()
        result = run_pert(case, 10)
        self.assertEqual(len(result["raw_activity"]), 10 * len(case.pert))

    def test_nearest_rank(self):
        rows = nearest_rank([10, 20, 30, 40])
        self.assertEqual(rows[49]["Rank"], 2)
        self.assertEqual(rows[49]["Duration"], 20)

    def test_gert_outcomes_sum_to_one_for_valid(self):
        result = run_gert(default_case(), 1000)
        probs = [r["Probability"] for r in result["outcome_summary"] if r["Outcome"] in ("Successful", "Terminated")]
        self.assertAlmostEqual(sum(probs), 1, places=9)

    def test_reproducibility(self):
        case = default_case()
        self.assertEqual(run_pert(case, 25)["totals"], run_pert(case, 25)["totals"])

    def test_renormalisation_ratio_example(self):
        a, b, loop = .5, .4, .1
        total = a + b
        self.assertAlmostEqual(a / total, .5555555555555556)
        self.assertAlmostEqual(b / total, .4444444444444445)
        self.assertAlmostEqual((a / total) / (b / total), 1.25)


if __name__ == "__main__":
    unittest.main()

