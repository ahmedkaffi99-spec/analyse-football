import math
import unittest

import coupons_score_exact as cs


class TestScoreExact(unittest.TestCase):
    def test_lecture_des_scores_1xbet(self):
        bks = [{"id": 11, "bets": [{"name": "Exact Score", "values": [
            {"value": "1:0", "odd": "7.5"}, {"value": "2-1", "odd": "9"}, {"value": "Other", "odd": "30"},
            {"value": "0:0", "odd": "x"}, {"value": "3:3", "odd": "0.9"}]}]},
               {"id": 4, "bets": [{"name": "Exact Score", "values": [{"value": "1:0", "odd": "7"}]}]}]
        self.assertEqual(cs.scores_1xbet(bks), {(1, 0): 7.5, (2, 1): 9.0})
        self.assertEqual(cs.scores_1xbet([]), {})

    def test_probas_marche_somment_a_un_et_ordre(self):
        p = cs.probas_marche({(1, 1): 6.0, (1, 0): 8.0, (0, 0): 12.0})
        self.assertAlmostEqual(sum(p.values()), 1.0)
        self.assertGreater(p[(1, 1)], p[(1, 0)])

    def test_modele_poisson_renormalise_et_melange(self):
        scores = [(a, b) for a in range(5) for b in range(5)]
        pm = cs.probas_modele(1.6, 1.1, scores)
        self.assertAlmostEqual(sum(pm.values()), 1.0)
        self.assertGreater(pm[(1, 1)], pm[(4, 4)])
        marche = cs.probas_marche({s: 5 + a + b for s in scores for a, b in [s]})
        mel = cs.melange(marche, pm)
        self.assertAlmostEqual(sum(mel.values()), 1.0)
        self.assertEqual(cs.melange(marche, None), marche)

    def _match(self, scores):
        return [((i, 0), p, 10.0) for i, p in enumerate(scores)]

    def test_construction_des_coupons(self):
        par = {f"M{i}": self._match([0.14 - i * 0.01, 0.12 - i * 0.005, 0.1]) for i in range(6)}
        coupons = cs.construire_coupons(par)
        self.assertEqual(len(coupons), 3)
        for _, jambes in coupons:
            self.assertEqual(len(jambes), 3)
            self.assertEqual(len({j[0] for j in jambes}), 3)       # un pari par match et par coupon
        paris = [(j[0], j[1]) for _, jambes in coupons for j in jambes]
        self.assertEqual(len(paris), len(set(paris)))               # jamais le même pari exact dans 2 coupons
        self.assertEqual({j[0] for j in coupons[0][1]} | {j[0] for j in coupons[1][1]}, set(par))
        self.assertEqual({j[0] for j in coupons[0][1]}, {"M0", "M1", "M2"})

    def test_resume_et_garde_6_matchs(self):
        cote, proba = cs.resume_coupon([("A", (1, 1), 0.1, 6.0), ("B", (1, 0), 0.2, 8.0)])
        self.assertAlmostEqual(cote, 48.0)
        self.assertAlmostEqual(proba, 0.02)
        with self.assertRaises(ValueError):
            cs.construire_coupons({"A": self._match([0.1, 0.1])})


if __name__ == "__main__":
    unittest.main()
