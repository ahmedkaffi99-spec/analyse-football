"""Règles du 28/10/2026 (bilan du jour) : déséquilibre, plafond de coupons par match, plancher de cote adaptatif."""
import unittest

import agent_strategie as st
import agents_familles as af
import desequilibre as dq


def _1x2(c1, cx, c2):
    return [{"marche": "Full Time Result", "selections": [
        {"selection": "1", "cote": c1}, {"selection": "X", "cote": cx}, {"selection": "2", "cote": c2}]}]


class TestDesequilibre(unittest.TestCase):
    def test_favori_et_annotation(self):
        cote, proba = dq.favori(_1x2(1.10, 9.0, 20.0))
        self.assertEqual(cote, "1")
        self.assertGreater(proba, 80)
        self.assertEqual(dq.favori(_1x2(3.0, 3.2, 2.4))[0], "2")
        self.assertEqual(dq.favori([]), (None, None))
        picks = [{"categorie": "Total"}]
        self.assertEqual(dq.annoter_favori(picks, _1x2(1.10, 9.0, 20.0)), 1)
        self.assertEqual(picks[0]["favori"], "1")

    def _pick(self, categorie, selection, fav="1", proba=85):
        return {"categorie": categorie, "selection": selection, "favori": fav, "proba_favori_pct": proba}

    def test_veto_sur_match_desequilibre(self):
        self.assertIn("déséquilibré", dq.veto(self._pick("Total", "Under")))
        self.assertIn("favori", dq.veto(self._pick("Total Équipe 1", "Under")))
        self.assertIn("outsider", dq.veto(self._pick("Handicap", "2")))
        self.assertIn("outsider", dq.veto(self._pick("Double Chance", "X2")))
        self.assertIsNotNone(dq.veto(self._pick("Total Équipe 2", "Under", fav="2")))
        self.assertIsNotNone(dq.veto(self._pick("Double Chance", "1X", fav="2")))

    def test_pas_de_veto_hors_cas(self):
        self.assertIsNone(dq.veto(self._pick("Total", "Over")))
        self.assertIsNone(dq.veto(self._pick("Handicap", "1")))                 # handicap du favori
        self.assertIsNone(dq.veto(self._pick("Total Équipe 2", "Under")))       # Under de l'outsider
        self.assertIsNone(dq.veto(self._pick("Total", "Under", proba=60)))     # match équilibré
        self.assertIsNone(dq.veto({"categorie": "Total", "selection": "Under"}))  # non annoté

    def test_branche_dans_le_veto_python_des_agents_familles(self):
        self.assertIn("déséquilibré", af.veto_python({"categorie": "Total", "selection": "Under", "edge_pct": 1.0,
                                                      "favori": "1", "proba_favori_pct": 90}))


def _cat(n_matchs):
    cat = {}
    for i in range(n_matchs):
        cat[f"P{i}"] = {"match": f"M{i}", "pick": {"categorie": "Total", "marche": "Over Under", "selection": "Over",
                                                    "handicap": 1.5, "cote": 1.3, "proba_modele_pct": 74.0,
                                                    "edge_pct": 1.0, "marche_affichage": "Total"}}
    return cat


class TestPlafondCouponsParMatch(unittest.TestCase):
    def _profil(self):
        return {"cle": "c", "nb_jambes_min": 1, "nb_jambes": 8, "cote_totale_min": 1.0, "jambes_max_par_match": 1,
                "match_repete_autorise": True, "max_coupons_par_match": 2, "proba_min_pct": 60}

    def _precedentes(self, catalogue, matchs_par_coupon):
        return [dict(catalogue[f"P{i}"], pick=dict(catalogue[f"P{i}"]["pick"], handicap=h))
                for h in (0.5, 2.5) for i in matchs_par_coupon]

    def test_troisieme_coupon_refuse_sur_un_match_deja_dans_deux(self):
        cat = _cat(10)
        prec = self._precedentes(cat, [0])
        _, problemes, _ = st.valider({"coupons": [{"profil": "c", "strategie": "x",
                                                   "jambes": [{"id": "P0", "raison": "r"}]}]},
                                     cat, [self._profil()], selections_precedentes=prec)
        self.assertTrue(any("maximum 2 par match" in p for p in problemes), problemes)

    def test_plafond_inactif_avec_peu_de_matchs(self):
        cat = _cat(5)
        prec = self._precedentes(cat, [0])
        _, problemes, _ = st.valider({"coupons": [{"profil": "c", "strategie": "x",
                                                   "jambes": [{"id": "P0", "raison": "r"}]}]},
                                     cat, [self._profil()], selections_precedentes=prec)
        self.assertFalse(any("maximum 2 par match" in p for p in problemes), problemes)


if __name__ == "__main__":
    unittest.main()
