"""Tests hors-ligne des correctifs (aucun appel réseau) : python -m unittest test_correctifs"""
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import analyser_et_envoyer as ae
import collecte_donnees as cd


class TestCorrespondanceEquipes(unittest.TestCase):
    def test_une_seule_equipe_commune_ne_suffit_plus(self):
        # Faux positifs réels relevés dans cron.log (80% et 82% avec l'ancien calcul)
        self.assertLess(cd.score_paire_equipes("SL Benfica", "CF Os Belenenses",
                                               "Estrela", "CF Os Belenenses"), cd.SEUIL_MATCH_ACCEPTABLE)
        self.assertLess(cd.score_paire_equipes("Malmo FF", "Hammarby IF",
                                               "IF Brommapojkarna", "Hammarby FF"), cd.SEUIL_MATCH_ACCEPTABLE)

    def test_vrais_matchs_toujours_trouves(self):
        self.assertGreaterEqual(cd.score_paire_equipes("RC Lens", "Auxerre", "Lens", "Auxerre"),
                                cd.SEUIL_MATCH_ACCEPTABLE)
        self.assertGreaterEqual(cd.score_paire_equipes("FC Vratimov", "MFK Havirov", "Vratimov", "Havířov"),
                                cd.SEUIL_MATCH_ACCEPTABLE)

    def test_trouver_fixture_oddspapi_rejette_le_faux_positif(self):
        fixtures = [{"participant1Name": "Estrela", "participant2Name": "CF Os Belenenses"}]
        fx, _ = cd.trouver_fixture_oddspapi("SL Benfica", "CF Os Belenenses", fixtures)
        self.assertIsNone(fx)


class TestSaison(unittest.TestCase):
    def test_saison_en_cours(self):
        self.assertEqual(cd.saison_en_cours(datetime(2026, 9, 25)), 2026)
        self.assertEqual(cd.saison_en_cours(datetime(2027, 3, 1)), 2026)


class TestXgUnderstat(unittest.TestCase):
    def test_calcul(self):
        home = {"matchs_joues": 5, "xg_moyen_par_match": 2.0, "xga_moyen_par_match": 1.0}
        away = {"matchs_joues": 5, "xg_moyen_par_match": 1.2, "xga_moyen_par_match": 1.6}
        self.assertEqual(ae.calculer_xg_depuis_understat(home, away), (1.8, 1.1))

    def test_echantillon_trop_faible(self):
        home = {"matchs_joues": 2, "xg_moyen_par_match": 2.0, "xga_moyen_par_match": 1.0}
        away = {"matchs_joues": 5, "xg_moyen_par_match": 1.2, "xga_moyen_par_match": 1.6}
        self.assertIsNone(ae.calculer_xg_depuis_understat(home, away))
        self.assertIsNone(ae.calculer_xg_depuis_understat(None, away))


class TestTelegram(unittest.TestCase):
    def test_repli_texte_brut_si_markdown_casse(self):
        erreur = mock.Mock(status_code=400, text='{"description":"Bad Request: can\'t parse entities"}')
        ok = mock.Mock(status_code=200, text="{}")
        envoyes, reponses = [], [erreur, ok]

        def faux_post(url, json, timeout):
            envoyes.append(dict(json))  # copie : le code modifie ensuite le même dict
            return reponses.pop(0)

        with mock.patch.object(ae, "TELEGRAM_TOKEN", "t"), mock.patch.object(ae, "TELEGRAM_CHAT_ID", "c"), \
                mock.patch.object(ae.requests, "post", side_effect=faux_post):
            self.assertTrue(ae.notifier_telegram("texte avec _ non fermé"))
        self.assertEqual(len(envoyes), 2)
        self.assertIn("parse_mode", envoyes[0])
        self.assertNotIn("parse_mode", envoyes[1])


class TestListeManuellePerimee(unittest.TestCase):
    def _collecter(self, date_liste):
        with tempfile.TemporaryDirectory() as d:
            sortie = os.path.join(d, "out.json")
            with mock.patch.object(cd, "SORTIE_JSON", sortie), \
                    mock.patch.object(cd, "SELECTION_MANUELLE_ACTIVE", True), \
                    mock.patch.object(cd, "MATCHS_MANUELS_DATE", date_liste), \
                    mock.patch.object(cd, "MATCHS_MANUELS", []), \
                    mock.patch.object(cd, "verifier_quota_oddspapi", return_value=True), \
                    mock.patch.object(cd, "_telecharger_fixtures_oddspapi", return_value=[]), \
                    mock.patch.object(cd, "recuperer_fixtures_api_football", return_value=[]), \
                    mock.patch.object(cd, "selectionner_matchs_du_jour", return_value=[]) as auto:
                cd.collecter_donnees()
                with open(sortie, encoding="utf-8") as f:
                    return json.load(f), auto

    def test_liste_perimee_ignoree(self):
        _, auto = self._collecter("2026-08-22")
        auto.assert_called_once()

    def test_liste_du_jour_utilisee(self):
        _, auto = self._collecter(datetime.now().strftime("%Y-%m-%d"))
        auto.assert_not_called()


if __name__ == "__main__":
    unittest.main()


def _fixture(p1, p2, tournoi, pays, depart="2026-09-26T15:00:00Z"):
    return {"participant1Name": p1, "participant2Name": p2, "tournamentName": tournoi, "categoryName": pays,
            "hasOdds": True, "statusName": "Pre-Game", "startTime": depart}


class TestSelectionTreveInternationale(unittest.TestCase):
    def test_feminin_exclu_et_secours_pendant_la_treve(self):
        fixtures = [
            _fixture("Juventus Turin", "SSD Napoli", "Serie A Women", "Italy"),
            _fixture("France", "Italie", "UEFA Nations League", "International"),
            _fixture("Espagne", "Portugal", "UEFA Nations League", "International"),
            _fixture("Obscur FC", "Autre FC", "Division 5", "Nowhere"),
        ]
        matchs = cd.selectionner_matchs_du_jour(fixtures)
        self.assertEqual(sorted(matchs), [("Espagne", "Portugal"), ("France", "Italie")])

    def test_grands_championnats_suffisants_pas_de_secours(self):
        fixtures = [_fixture(f"Club {i}", f"Adv {i}", "Premier League", "England") for i in range(8)]
        fixtures.append(_fixture("France", "Italie", "UEFA Nations League", "International"))
        matchs = cd.selectionner_matchs_du_jour(fixtures)
        self.assertEqual(len(matchs), 8)
        self.assertNotIn(("France", "Italie"), matchs)

    def test_equipe_feminine_api_football(self):
        self.assertTrue(cd.est_equipe_feminine_api_football("Juventus W"))
        self.assertFalse(cd.est_equipe_feminine_api_football("Wolves"))


def _selection(match, categorie, selection, cote, edge=8.0):
    return {"match": match, "home_nom": match.split(" vs ")[0], "away_nom": match.split(" vs ")[1],
            "fixture_id_oddspapi": match,
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)", "handicap": 2.5, "selection": selection,
                     "cote": cote, "proba_modele_pct": 70.0, "edge_pct": edge, "guide": "guide", "onglet": "onglet"}}


class TestCouponsJoursCreux(unittest.TestCase):
    def test_pas_plus_de_deux_paris_par_match_ni_coupons_identiques(self):
        pool = {m: [_selection(m, c, "Over", 1.3 + 0.1 * i) for i, c in enumerate(("Total", "BTTS", "Total Équipe 1"))]
                for m in ("A vs B", "C vs D", "E vs F")}
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool):
            resultats = ae.generer_trois_coupons({"matchs": []})
        signatures = []
        for item in resultats:
            sel = item["selections"]
            if not sel:
                continue
            self.assertEqual(len(sel), 6)  # 3 matchs × 2 paris max, au lieu de 8
            par_match = {}
            for s in sel:
                par_match[s["match"]] = par_match.get(s["match"], 0) + 1
            self.assertLessEqual(max(par_match.values()), 2)
            signatures.append(frozenset((s["match"], s["pick"]["marche"]) for s in sel))
        self.assertEqual(len(signatures), len(set(signatures)))


class TestRedactionSansIA(unittest.TestCase):
    def test_panne_de_tous_les_llm_ne_fait_plus_perdre_le_ticket(self):
        selections = [_selection("A vs B", "Total", "Over", 1.5, edge=12.0), _selection("C vs D", "BTTS", "Yes", 1.8, edge=25.0)]
        with mock.patch.object(ae, "appel_llm", side_effect=ValueError("Tous les modèles ont échoué")), \
                mock.patch.object(ae.time, "sleep"):
            texte = ae.agent4_ia_analyse_pronostic_redaction(selections)
        self.assertEqual(texte.count("⚽"), 2)
        self.assertIn("Confiance : Moyen", texte)
        self.assertIn("Confiance : Élevé", texte)
        self.assertIn("📍 Où parier : onglet", texte)

    def test_erreur_gemini_en_liste_lisible(self):
        reponse = mock.Mock(status_code=429, json=lambda: [{"error": {"message": "Quota exceeded"}}])
        with self.assertRaisesRegex(ValueError, "Gemini HTTP 429 : Quota exceeded"):
            ae._contenu_reponse("Gemini", reponse)
