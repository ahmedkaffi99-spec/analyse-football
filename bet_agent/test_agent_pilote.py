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

    def test_scenario_complet_collecte_catalogue_propose_redige_envoie(self):
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),
            _msg_outil("proposer_coupon", {"strategie": "s", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("rediger_coupon", {}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=DONNEES_FACTICES), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_FACTICE), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True) as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=True)

        self.assertTrue(resultat["termine"])
        self.assertTrue(resultat["envoye"])
        envoi.assert_called_once()

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
            _msg_outil("rediger_coupon", {}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=DONNEES_FACTICES), \
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
        with mock.patch.object(cd, "collecter_donnees", return_value=DONNEES_FACTICES), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value={}), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]) as appel:
            pilote.executer(mission="test", telegram=False)
        dernier_appel_messages = appel.call_args_list[-1].args[1]
        contenus_outils = [m["content"] for m in dernier_appel_messages if m.get("role") == "tool"]
        self.assertTrue(any("erreur" in c for c in contenus_outils))


if __name__ == "__main__":
    unittest.main()
