"""Tests hors-ligne de l'agent stratège IA (IA simulée) : python -m unittest test_agent_strategie"""
import json
import unittest
from unittest import mock

import agent_strategie as st
import analyser_et_envoyer as ae

PROFILS = [
    {"cle": "profil1", "nom": "🛡️ COUPON 1", "cote_min": 2.0, "cote_max": 4.0, "nb_jambes": 4},
    {"cle": "profil2", "nom": "⚖️ COUPON 2", "cote_min": 4.0, "cote_max": 12.0, "nb_jambes": 4},
]


def _sel(match, categorie, selection, cote):
    return {"match": match, "home_nom": match.split(" vs ")[0], "away_nom": match.split(" vs ")[1],
            "fixture_id_oddspapi": match,
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)", "handicap": 2.5, "selection": selection,
                     "cote": cote, "proba_modele_pct": 60.0, "edge_pct": 6.0, "guide": "g", "onglet": "o",
                     "proba_poisson_pct": 64.0, "proba_marche_pct": 58.0},
            "contexte": {"contexte_web": [], "elo": {}, "buts_attendus": {"domicile": 1.5, "exterieur": 1.0}}}


POOL = {
    "A vs B": [_sel("A vs B", "Total", "Over", 1.6), _sel("A vs B", "BTTS", "Yes", 1.8)],   # P1, P2
    "C vs D": [_sel("C vs D", "Total", "Under", 1.5), _sel("C vs D", "BTTS", "No", 1.9)],   # P3, P4
    "E vs F": [_sel("E vs F", "Total", "Over", 2.0)],                                       # P5
}


def _reponse(coupons, analyse=None):
    return json.dumps({"analyse_matchs": analyse or [{"match": "A vs B", "fiabilite": "haute", "avis": "ok"}],
                       "coupons": coupons}, ensure_ascii=False)


class TestStratege(unittest.TestCase):
    def test_catalogue_identifiants_et_chiffres(self):
        catalogue, texte = st.construire_catalogue(POOL)
        self.assertEqual(list(catalogue), ["P1", "P2", "P3", "P4", "P5"])
        self.assertIn("P5 : Total (2.5) → Over @ 2.0", texte)
        self.assertIn("modèle 64.0%, marché 58.0%", texte)

    def test_choix_valide_des_le_premier_tour(self):
        reponse = _reponse([
            {"profil": "profil1", "strategie": "Paris solides", "jambes": [{"id": "P1", "raison": "r1"}, {"id": "P3", "raison": "r3"}]},
            {"profil": "profil2", "strategie": "Plus audacieux", "jambes": [
                {"id": "P2", "raison": "r2"}, {"id": "P4", "raison": "r4"}, {"id": "P5", "raison": "r5"}]},
        ])
        appel = mock.Mock(return_value="```json\n" + reponse + "\n```")
        resultat = st.composer_coupons(POOL, PROFILS, appel=appel)
        self.assertEqual(appel.call_count, 1)
        p1 = resultat["coupons"]["profil1"]
        self.assertEqual([s["pick"]["selection"] for s in p1["selections"]], ["Over", "Under"])
        self.assertEqual(p1["selections"][0]["raison_ia"], "r1")
        self.assertEqual(p1["strategie"], "Paris solides")

    def test_erreurs_renvoyees_a_l_ia_qui_corrige(self):
        mauvaise = _reponse([
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P99"}]},        # id inventé
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P2"}]},         # cote 2.88 < 4
        ])
        bonne = _reponse([
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P3"}]},
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P2"}, {"id": "P4"}, {"id": "P5"}]},
        ])
        appel = mock.Mock(side_effect=[mauvaise, bonne])
        resultat = st.composer_coupons(POOL, PROFILS, appel=appel)
        self.assertEqual(appel.call_count, 2)
        second_prompt = appel.call_args_list[1].args[0]
        self.assertIn("identifiant inconnu « P99 »", second_prompt)
        self.assertIn("cote totale 2.88 trop basse", second_prompt)
        self.assertEqual(set(resultat["coupons"]), {"profil1", "profil2"})

    def test_regles_python_imposees(self):
        catalogue, _ = st.construire_catalogue(POOL)
        proposition = {"coupons": [
            {"profil": "profil1", "jambes": [{"id": "P1"}, {"id": "P1"}]},                          # doublon
            {"profil": "profil2", "jambes": [{"id": "P1"}, {"id": "P2"}, {"id": "P1"}, {"id": "P5"}]},
        ]}
        acceptes, problemes, _ = st.valider(proposition, catalogue, PROFILS)
        self.assertEqual(acceptes, {})
        self.assertTrue(any("P1 choisi deux fois" in p for p in problemes))

    def test_abstention_acceptee(self):
        reponse = _reponse([
            {"profil": "profil1", "strategie": "Aucune valeur fiable aujourd'hui", "jambes": []},
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P2"}, {"id": "P4"}, {"id": "P5"}]},
        ])
        resultat = st.composer_coupons(POOL, PROFILS, appel=mock.Mock(return_value=reponse))
        self.assertEqual(resultat["coupons"]["profil1"]["abstention"], "Aucune valeur fiable aujourd'hui")

    def test_ia_inexploitable_repli_automatique(self):
        self.assertIsNone(st.composer_coupons(POOL, PROFILS, appel=mock.Mock(return_value="Je ne sais pas")))

    def test_integration_generer_trois_coupons(self):
        reponse = _reponse([
            {"profil": "profil1", "strategie": "Stratégie sûre", "jambes": [{"id": "P1", "raison": "r"}, {"id": "P3", "raison": "r"}]},
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P2"}, {"id": "P4"}, {"id": "P5"}]},
        ])
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL), \
                mock.patch.object(ae, "PROFILS_COUPON", PROFILS + [
                    {"cle": "profil3", "nom": "🔥 COUPON 3", "cote_min": 50.0, "cote_max": 100.0, "nb_jambes": 8}]), \
                mock.patch.object(ae, "appel_llm", return_value=reponse), mock.patch.object(ae.time, "sleep"):
            resultats = ae.generer_trois_coupons({"matchs": []})
        self.assertEqual(resultats[0]["strategie"], "Stratégie sûre")
        self.assertEqual(len(resultats[0]["selections"]), 2)
        self.assertEqual(len(resultats), 3)  # profil3 absent de la réponse IA → composition automatique


if __name__ == "__main__":
    unittest.main()


class TestCoherenceDesRaisons(unittest.TestCase):
    def test_raison_d_un_autre_pari_renvoyee_a_l_ia(self):
        # Run 11 : raison « Under 2 à 1.65 » écrite pour un Over @ 3.16
        self.assertIn("cite la cote 1.65", st.incoherence_raison("Under 2 à 1.65, forte probabilité",
                                                                 {"cote": 3.16, "selection": "Over"}))
        self.assertIn("« no »", st.incoherence_raison("Aucune équipe ne marque : No au BTTS",
                                                      {"cote": 1.8, "selection": "Yes"}))
        for raison, pick in [("Over 1.5 à 1.9, attractif", {"cote": 1.9, "selection": "Over"}),
                             ("probabilité estimée à 31.5 % et cote @ 3.65", {"cote": 3.65, "selection": "Yes"}),
                             ("Double Chance 2X à 1.491", {"cote": 1.491, "selection": "2X"})]:
            self.assertIsNone(st.incoherence_raison(raison, pick), raison)

    def test_la_raison_incoherente_est_corrigee_au_tour_suivant(self):
        mauvaise = _reponse([
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1", "raison": "Under à 1.5"},
                                                             {"id": "P3", "raison": "r3"}]},
            {"profil": "profil2", "strategie": "s", "jambes": [
                {"id": "P2", "raison": "r2"}, {"id": "P4", "raison": "r4"}, {"id": "P5", "raison": "r5"}]}])
        bonne = _reponse([
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1", "raison": "Over à 1.6, buts attendus"},
                                                             {"id": "P3", "raison": "r3"}]}])
        appel = mock.Mock(side_effect=[mauvaise, bonne])
        resultat = st.composer_coupons(POOL, PROFILS, appel=appel)
        self.assertEqual(appel.call_count, 2)
        self.assertIn("P1 : ta raison", appel.call_args_list[1].args[0])  # le problème est renvoyé à l'IA
        p1 = resultat["coupons"]["profil1"]["selections"]
        self.assertEqual(p1[0]["raison_ia"], "Over à 1.6, buts attendus")


class TestCoupEnvoi(unittest.TestCase):
    def test_match_qui_commence_bientot_ecarte_a_la_reprise(self):
        from datetime import datetime, timezone
        maintenant = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
        self.assertFalse(ae.coup_envoi_assez_loin("2026-09-26T13:30:00Z", maintenant))
        self.assertFalse(ae.coup_envoi_assez_loin("2026-09-26T12:00:00Z", maintenant))
        self.assertTrue(ae.coup_envoi_assez_loin("2026-09-26T18:45:00Z", maintenant))
        self.assertTrue(ae.coup_envoi_assez_loin(None, maintenant))
