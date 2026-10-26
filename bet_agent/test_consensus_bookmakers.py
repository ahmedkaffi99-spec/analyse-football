import unittest
from unittest import mock

import adaptateur_api_football as adf
import consensus_bookmakers as cb


def _reponse(bookmakers):
    return {"errors": [], "response": [{"update": "2026-10-26T00:00:00+00:00", "bookmakers": bookmakers}]}


def _bm(i, nom, home, draw, away, over=None, under=None):
    bets = [{"id": 1, "name": "Match Winner", "values": [
        {"value": "Home", "odd": str(home)}, {"value": "Draw", "odd": str(draw)}, {"value": "Away", "odd": str(away)}]}]
    if over:
        bets.append({"id": 5, "name": "Goals Over/Under", "values": [
            {"value": "Over 2.5", "odd": str(over)}, {"value": "Under 2.5", "odd": str(under)}]})
    return {"id": i, "name": nom, "bets": bets}


class TestCotesParBookmaker(unittest.TestCase):
    def test_un_marche_par_bookmaker_servi_et_inconnus_ignores(self):
        data = _reponse([_bm(11, "1xBet", 2.0, 3.4, 3.8), _bm(4, "Pinnacle", 2.05, 3.5, 3.9), _bm(999, "Inconnu", 2, 3, 4)])
        sortie = adf.cotes_par_bookmaker(data)
        self.assertEqual(set(sortie), {"1xBet", "Pinnacle"})
        selections = {s["selection"]: s["cote"] for s in sortie["Pinnacle"][0]["selections"]}
        self.assertEqual(sorted(selections.values()), [2.05, 3.5, 3.9])

    def test_reponse_en_erreur_ou_vide(self):
        self.assertEqual(adf.cotes_par_bookmaker({"errors": {"x": "y"}, "response": []}), {})
        self.assertEqual(adf.cotes_par_bookmaker({"errors": [], "response": []}), {})

    def test_les_dix_bookmakers_sont_declares(self):
        self.assertEqual(len(adf.BOOKMAKERS_COLLECTES), 10)
        self.assertEqual(adf.BOOKMAKERS_COLLECTES[11], "1xBet")
        self.assertEqual(adf.BOOKMAKERS_COLLECTES[4], "Pinnacle")

    def test_appel_en_echec_renvoie_none(self):
        with mock.patch("requests.get", side_effect=RuntimeError("réseau")):
            self.assertIsNone(adf.capturer_cotes_tous_bookmakers(123))
        rep = mock.Mock(status_code=429)
        with mock.patch("requests.get", return_value=rep):
            self.assertIsNone(adf.capturer_cotes_tous_bookmakers(123))


class TestConsensus(unittest.TestCase):
    def _cotes(self):
        data = _reponse([_bm(11, "1xBet", 2.10, 3.4, 3.6), _bm(4, "Pinnacle", 2.00, 3.5, 4.0),
                         _bm(8, "Bet365", 2.05, 3.4, 3.8), _bm(2, "Marathonbet", 2.02, 3.5, 3.9)])
        return adf.cotes_par_bookmaker(data)

    def test_probas_sans_marge_somment_a_un(self):
        m = self._cotes()["Pinnacle"][0]
        p = cb.probas_sans_marge(m)
        self.assertAlmostEqual(sum(p.values()), 1.0)

    def test_consensus_pondere_et_ecart_avec_reference(self):
        c = cb.consensus(self._cotes())
        cle = next(k for k in c if k[2] in ("1", "Home", "home"))
        self.assertEqual(c[cle]["nb_bookmakers"], 4)
        self.assertGreater(c[cle]["proba_pct"], c[cle]["proba_ref_pct"])  # 1xBet est la moins chère pour l'issue 1 : cote 2.10
        self.assertAlmostEqual(c[cle]["ecart_pts"], c[cle]["proba_pct"] - c[cle]["proba_ref_pct"], places=1)

    def test_moins_de_trois_bookmakers_ignore(self):
        data = _reponse([_bm(11, "1xBet", 2.1, 3.4, 3.6), _bm(4, "Pinnacle", 2.0, 3.5, 4.0)])
        self.assertEqual(cb.consensus(adf.cotes_par_bookmaker(data)), {})

    def test_marche_incomplet_ignore(self):
        self.assertIsNone(cb.probas_sans_marge({"selections": [{"selection": "Over", "cote": 1.9}]}))


if __name__ == "__main__":
    unittest.main()


class TestBacktestBookmakers(unittest.TestCase):
    def test_issue_reelle(self):
        import backtest_bookmakers as bt
        self.assertEqual(bt.issue_reelle("Full Time Result", None, 2, 0), "1")
        self.assertEqual(bt.issue_reelle("Full Time Result", None, 1, 1), "X")
        self.assertEqual(bt.issue_reelle("Over Under Full Time", 2.5, 2, 1), "Over")
        self.assertEqual(bt.issue_reelle("Over Under Full Time", 2.5, 1, 1), "Under")
        self.assertEqual(bt.issue_reelle("Both Teams To Score", None, 1, 0), "No")
        self.assertIsNone(bt.issue_reelle("Over Under Full Time", 3.5, 2, 1))

    def test_evaluer_accumule_brier_et_consensus(self):
        import backtest_bookmakers as bt
        from collections import defaultdict
        data = _reponse([_bm(11, "1xBet", 2.0, 3.4, 3.8, 1.9, 1.9), _bm(4, "Pinnacle", 2.05, 3.5, 3.9, 1.95, 1.9),
                         _bm(8, "Bet365", 2.1, 3.3, 3.7, 1.9, 1.95)])
        acc = defaultdict(lambda: {"n": 0, "brier": 0.0, "logloss": 0.0, "marge": 0.0, "roi": 0.0})
        bt.evaluer(adf.cotes_par_bookmaker(data), 2, 0, acc)
        self.assertEqual(acc[("Pinnacle", "Full Time Result")]["n"], 1)
        self.assertEqual(acc[("★ Consensus", "Full Time Result")]["n"], 1)
        self.assertGreater(acc[("1xBet", "Full Time Result")]["marge"], 0)
        # Brier d'un 1X2 est dans [0, 2]
        self.assertTrue(0 <= acc[("1xBet", "Full Time Result")]["brier"] <= 2)
