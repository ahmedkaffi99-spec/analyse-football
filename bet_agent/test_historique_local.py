import unittest
from datetime import datetime, timedelta, timezone

import historique_local as hl


def _m(i, jours, h, a, sh, sa, stats=None):
    d = datetime(2026, 10, 1, tzinfo=timezone.utc) - timedelta(days=jours)
    return {"match_id": i, "date": d.isoformat(), "competition_id": 39, "competition": "PL", "saison": 2026,
            "home_id": h, "home": f"E{h}", "away_id": a, "away": f"E{a}", "home_score": sh, "away_score": sa,
            "stats": stats}


class TestHistoriqueLocal(unittest.TestCase):
    def setUp(self):
        hl._cache.clear()
        self.matchs = [_m(i, 10 * i, 1 if i % 2 else 2, 2 if i % 2 else 1, 2, 1,
                          {"home": {"corners": 6, "yellow_cards": 2}, "away": {"corners": 4, "yellow_cards": 1}})
                       for i in range(1, 9)]

    def test_stats_equipe(self):
        s = hl.stats_equipe(1, "E1", 39, datetime(2026, 10, 2, tzinfo=timezone.utc), self.matchs)
        self.assertEqual(s["matchs_joues"], 8)
        self.assertEqual(s["buts_marques_domicile"], 2.0)
        self.assertEqual(s["buts_encaisses_exterieur"], 2.0)

    def test_stats_insuffisantes(self):
        self.assertIsNone(hl.stats_equipe(1, "E1", 39, datetime(2026, 10, 2, tzinfo=timezone.utc), self.matchs[:3]))

    def test_pas_de_fuite_du_futur(self):
        s = hl.stats_detaillees(1, datetime(2026, 9, 15, tzinfo=timezone.utc), self.matchs)
        self.assertEqual(s["matchs_avec_donnees"], 7)

    def test_detaillees_et_h2h(self):
        sd = hl.stats_detaillees(1, datetime(2026, 10, 2, tzinfo=timezone.utc), self.matchs)
        self.assertEqual(sd["corners_pour_moyenne"], 5.0)
        h = hl.head_to_head(1, 2, datetime(2026, 10, 2, tzinfo=timezone.utc), self.matchs)
        self.assertEqual(h["matchs_analyses"], 8)
        self.assertEqual(h["victoires_home"] + h["victoires_away"] + h["nuls"], 8)

    def test_resolution_noms(self):
        hl._cache["equipes"] = {50: ("Manchester City", 39), 33: ("Manchester United", 39),
                                505: ("Inter", 135), 489: ("AC Milan", 135), 163: ("Borussia Mönchengladbach", 78)}
        r = lambda n: (hl.resoudre_equipe(n, []) or (None,))[0]
        self.assertEqual(r("Man City"), 50)
        self.assertEqual(r("Man United"), 33)
        self.assertEqual(r("Inter Milan"), 505)
        self.assertEqual(r("AC Milan"), 489)
        self.assertEqual(r("Gladbach"), 163)
        self.assertIsNone(r("Real Inconnu"))


if __name__ == "__main__":
    unittest.main()
