"""Tests hors-ligne de l'agent pilote DeepSeek (executer() branché sur collecte/analyse
réelles, moteur piloter() simulé) : python -m unittest test_agent_pilote"""
import json
import unittest
from unittest import mock

import agent_pilote as pilote
import collecte_donnees as cd
import analyser_et_envoyer as ae
import agent_strategie as st


DONNEES_FACTICES = {"nb_matchs_demandes": 2, "nb_matchs_avec_marches": 2, "nb_marches_total": 6}

POOL_FACTICE = {
    "A vs B": [{"match": "A vs B", "pick": {"categorie": "Total", "marche": "Total (2.5)", "selection": "Over",
                                            "cote": 1.8, "proba_modele_pct": 62.0, "edge_pct": 8.0,
                                            "proba_poisson_pct": 62.0, "proba_marche_pct": 55.0}}],
    "C vs D": [{"match": "C vs D", "pick": {"categorie": "Total", "marche": "Total (2.5)", "selection": "Under",
                                            "cote": 1.9, "proba_modele_pct": 60.0, "edge_pct": 7.0,
                                            "proba_poisson_pct": 60.0, "proba_marche_pct": 53.0}}],
}

PROFIL = {"cle": "coupon", "nom": "🎯 COUPON", "cote_min": 0.0, "cote_max": 1000.0,
          "nb_jambes_min": 2, "nb_jambes": 2}


def _msg_outil(nom, args, appel_id="1"):
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": appel_id, "function": {"name": nom, "arguments": json.dumps(args)}}
    ]}}], "usage": {"total_tokens": 100}}


class TestExecuterAgentPilote(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": "cle-test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_scenario_complet_collecte_catalogue_propose_envoie(self):
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),
            _msg_outil("proposer_coupon", {"strategie": "s", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_FACTICE), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True) as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=True)

        self.assertTrue(resultat["termine"])
        self.assertTrue(resultat["envoye"])
        envoi.assert_called_once()
        self.assertEqual(len(resultat["resultats_profils"]), 1)
        self.assertEqual(len(resultat["resultats_profils"][0]["selections"]), 2)

    def test_sans_cle_renvoie_non_termine(self):
        with mock.patch.object(pilote.os, "getenv", return_value=None):
            resultat = pilote.executer()
        self.assertFalse(resultat["termine"])
        self.assertIn("clé", resultat["arret"])

    def test_envoi_desactive_enregistre_sans_envoyer(self):
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),
            _msg_outil("proposer_coupon", {"strategie": "s", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_FACTICE), \
                mock.patch.object(ae, "agent5_envoyer_coupons") as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[
                    (r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=False)

        self.assertTrue(resultat["termine"])
        self.assertFalse(resultat["envoye"])
        envoi.assert_not_called()

    def test_abandon_termine_sans_coupon(self):
        reponses = [_msg_outil("abandonner", {"raison": "rien de défendable"})]
        with mock.patch.object(cd, "collecter_donnees", return_value=DONNEES_FACTICES), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=False)
        self.assertTrue(resultat["termine"])
        self.assertFalse(resultat["envoye"])
        self.assertEqual(resultat["raison_abandon"], "rien de défendable")

    def test_catalogue_vide_signale_une_erreur_a_l_ia(self):
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),
            _msg_outil("abandonner", {"raison": "catalogue vide"}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value={}), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]) as appel:
            pilote.executer(mission="test", telegram=False)
        dernier_appel_messages = appel.call_args_list[-1].args[1]
        contenus_outils = [m["content"] for m in dernier_appel_messages if m.get("role") == "tool"]
        self.assertTrue(any("erreur" in c for c in contenus_outils))


PROFIL_1 = {"cle": "sur", "nom": "🛡️ SÛR", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 1, "nb_jambes": 2}
PROFIL_2 = {"cle": "equilibre", "nom": "⚖️ ÉQUILIBRÉ", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 1, "nb_jambes": 2}
PROFIL_3 = {"cle": "audacieux", "nom": "🔥 AUDACIEUX", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 1, "nb_jambes": 2}


class TestTroisProfilsMemeRun(unittest.TestCase):
    """Demande explicite du 30/09/2026 : "3 trois type de coupon sur un seule run et envoie
    telegrame" — un seul pool/catalogue calculé une fois, 3 compositions séquentielles
    (jamais en parallèle), 3 messages Telegram séparés dans le MÊME run."""

    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": "cle-test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_3_profils_composes_sequentiellement_et_envoyes_en_3_messages(self):
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),  # profil 1/3
            _msg_outil("proposer_coupon", {"strategie": "s1", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("voir_catalogue", {}),  # profil 2/3
            _msg_outil("proposer_coupon", {"strategie": "s2", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("voir_catalogue", {}),  # profil 3/3
            _msg_outil("proposer_coupon", {"strategie": "s3", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1, PROFIL_2, PROFIL_3]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_FACTICE), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True) as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=True)

        self.assertTrue(resultat["termine"])
        self.assertTrue(resultat["envoye"])
        # Les 3 profils ont chacun leur coupon, dans l'ordre.
        self.assertEqual([r["profil"]["cle"] for r in resultat["resultats_profils"]],
                         ["sur", "equilibre", "audacieux"])
        # agent5_envoyer_coupons reçoit bien 3 textes séparés (1 message Telegram par profil).
        textes_envoyes = envoi.call_args.args[0]
        self.assertEqual(len(textes_envoyes), 3)
        self.assertIn("SÛR", textes_envoyes[0])
        self.assertIn("ÉQUILIBRÉ", textes_envoyes[1])
        self.assertIn("AUDACIEUX", textes_envoyes[2])

    def test_abstention_sur_un_profil_continue_les_autres(self):
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),  # profil 1/3
            _msg_outil("proposer_coupon", {"strategie": "rien de sûr aujourd'hui", "jambes": []}),
            _msg_outil("voir_catalogue", {}),  # profil 2/3
            _msg_outil("proposer_coupon", {"strategie": "s2", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("voir_catalogue", {}),  # profil 3/3
            _msg_outil("proposer_coupon", {"strategie": "s3", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1, PROFIL_2, PROFIL_3]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_FACTICE), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True) as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=True)

        self.assertTrue(resultat["termine"])
        self.assertTrue(resultat["envoye"])
        # 3 profils traités quand même (le premier juste sans sélection = abstention).
        self.assertEqual(len(resultat["resultats_profils"]), 3)
        self.assertEqual(resultat["resultats_profils"][0]["selections"], [])
        self.assertEqual(len(resultat["resultats_profils"][1]["selections"]), 2)
        textes_envoyes = envoi.call_args.args[0]
        self.assertEqual(len(textes_envoyes), 3)
        self.assertIn("rien de sûr aujourd'hui", textes_envoyes[0])

    def test_envoyer_telegram_refuse_si_profils_restants(self):
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),  # profil 1/3
            _msg_outil("proposer_coupon", {"strategie": "s1", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),  # trop tôt : 2 profils restants
            _msg_outil("abandonner", {"raison": "test arrêté volontairement"}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1, PROFIL_2, PROFIL_3]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_FACTICE), \
                mock.patch.object(ae, "agent5_envoyer_coupons") as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]) as appel:
            pilote.executer(mission="test", telegram=True)
        envoi.assert_not_called()
        dernier_appel_messages = appel.call_args_list[-1].args[1]
        contenus_outils = [m["content"] for m in dernier_appel_messages if m.get("role") == "tool"]
        self.assertTrue(any("sans coupon" in c for c in contenus_outils))


if __name__ == "__main__":
    unittest.main()
