"""Tests hors-ligne de l'agent pilote DeepSeek (executer() branché sur collecte/analyse
réelles, moteur piloter() simulé) : python -m unittest test_agent_pilote"""
import json
import os
import unittest
from unittest import mock

import agent_pilote as pilote
import agents_familles
import collecte_donnees as cd
import analyser_et_envoyer as ae
import agent_strategie as st


# Pools factices à cotes volontairement petites (1.6-2.0), sans rapport avec le plancher
# ABSOLU de cote totale ajouté le 01/10/2026 (demande explicite "interdit les cote total moins
# de 5" — voir agent_strategie.COTE_TOTALE_MIN) : désactivé pour tout ce fichier.
def setUpModule():
    global _PATCHEUR_COTE_MIN
    _PATCHEUR_COTE_MIN = mock.patch.object(st, "COTE_TOTALE_MIN", 0.0)
    _PATCHEUR_COTE_MIN.start()


def tearDownModule():
    _PATCHEUR_COTE_MIN.stop()


DONNEES_FACTICES = {"nb_matchs_demandes": 2, "nb_matchs_avec_marches": 2, "nb_marches_total": 6}

POOL_FACTICE = {
    "A vs B": [{"match": "A vs B", "pick": {"categorie": "Total", "marche": "Total (2.5)", "selection": "Over",
                                            "cote": 1.8, "proba_modele_pct": 72.0, "edge_pct": 8.0,
                                            "proba_poisson_pct": 62.0, "proba_marche_pct": 55.0}}],
    "C vs D": [{"match": "C vs D", "pick": {"categorie": "Total", "marche": "Total (2.5)", "selection": "Under",
                                            "cote": 1.9, "proba_modele_pct": 71.0, "edge_pct": 7.0,
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

    def test_voir_catalogue_transmet_le_contexte_par_match(self):
        # Correctif réel (01/10/2026) : voir_catalogue ne renvoyait QUE les lignes de paris,
        # jamais le contexte par match (buts attendus, forme...) alors que le prompt système
        # demande explicitement à l'IA de s'en servir — st._contexte(pool) existait déjà pour
        # le moteur déterministe mais n'était jamais appelé ici.
        pool_avec_contexte = {"A vs B": [{
            "match": "A vs B", "pick": {"categorie": "Total", "marche": "Total (2.5)", "selection": "Over",
                                        "cote": 1.8, "proba_modele_pct": 72.0, "edge_pct": 8.0},
            "contexte": {"buts_attendus": {"domicile": 1.8, "exterieur": 1.1},
                         "forme": {"domicile": {"points_par_match": 2.1, "clean_sheets_sur_10": 4}}},
        }]}
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),
            _msg_outil("abandonner", {"raison": "test"}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool_avec_contexte), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]) as appel:
            pilote.executer(mission="test", telegram=False)
        dernier_appel_messages = appel.call_args_list[-1].args[1]
        contenus_outils = [m["content"] for m in dernier_appel_messages if m.get("role") == "tool"]
        texte_catalogue = next(c for c in contenus_outils if "contexte_par_match" in c)
        self.assertIn("Buts attendus (modèle) : 1.8", texte_catalogue)
        self.assertIn("Forme récente (équipe domicile", texte_catalogue)
        self.assertIn("2.1 point(s)/match", texte_catalogue)
        self.assertIn("4 clean sheet(s) sur 10", texte_catalogue)

    def test_voir_catalogue_transmet_prefere_cote_elevee(self):
        # Correctif explicite (02/10/2026) : "les 5e coupon que je t'ai dit de prendre risque,
        # sache dire les cotes élevées car cote élevée = gain élevé" — un premier run (75)
        # avait rempli ce profil avec des favoris à cote basse (1.33-1.44, mêmes choix que les
        # profils sûrs), ce qui ne matérialisait aucun risque/gain réel. voir_catalogue doit
        # transmettre explicitement la préférence du profil à l'IA.
        profil_risque = {"cle": "risque", "nom": "🎲 RISQUÉ", "cote_min": 1.01, "cote_max": 1000000.0,
                          "nb_jambes_min": 4, "nb_jambes": 5, "prefere_cote_elevee": True}
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),
            _msg_outil("abandonner", {"raison": "test"}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [profil_risque]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_FACTICE), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]) as appel:
            pilote.executer(mission="test", telegram=False)
        dernier_appel_messages = appel.call_args_list[-1].args[1]
        contenus_outils = [m["content"] for m in dernier_appel_messages if m.get("role") == "tool"]
        texte_catalogue = next(c for c in contenus_outils if "catalogue" in c)
        self.assertIn('"prefere_cote_elevee": true', texte_catalogue)

    def test_voir_catalogue_prefere_cote_elevee_false_par_defaut(self):
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),
            _msg_outil("abandonner", {"raison": "test"}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_FACTICE), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]) as appel:
            pilote.executer(mission="test", telegram=False)
        dernier_appel_messages = appel.call_args_list[-1].args[1]
        contenus_outils = [m["content"] for m in dernier_appel_messages if m.get("role") == "tool"]
        texte_catalogue = next(c for c in contenus_outils if "catalogue" in c)
        self.assertIn('"prefere_cote_elevee": false', texte_catalogue)


PROFIL_1 = {"cle": "sur", "nom": "🛡️ SÛR", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 1, "nb_jambes": 2}
PROFIL_2 = {"cle": "equilibre", "nom": "⚖️ ÉQUILIBRÉ", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 1, "nb_jambes": 2}
PROFIL_3 = {"cle": "audacieux", "nom": "🔥 AUDACIEUX", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 1, "nb_jambes": 2}


def _pick(categorie, marche, selection, cote, proba_modele_pct=75.0):
    # proba_modele_pct >= SEUIL_PROBA_CATALOGUE (60%) par défaut : depuis le 01/10/2026,
    # construire_catalogue EXCLUT les paris sans probabilité calculée ou en dessous du seuil
    # (demande explicite "réduire les tâches de l'IA, augmenter Python") — ces fixtures
    # simulent des paris déjà modélisés par Python, pas des marchés bruts.
    return {"categorie": categorie, "marche": marche, "handicap": 2.5, "selection": selection, "cote": cote,
            "proba_modele_pct": proba_modele_pct, "edge_pct": 8.0,
            "proba_poisson_pct": proba_modele_pct, "proba_marche_pct": proba_modele_pct}


# 6 matchs, un pick chacun (P1..P6) : assez pour que 3 profils de 2 jambes composent chacun
# des paris DIFFÉRENTS, sans jamais avoir besoin de réutiliser le même pari qu'un profil
# précédent (voir TestTroisProfilsMemeRun ci-dessous).
POOL_SIX_MATCHS = {
    f"M{i} vs A{i}": [{"match": f"M{i} vs A{i}", "pick": _pick("Total", "Total (2.5)", sel, 1.8)}]
    for i, sel in enumerate(["Over", "Under", "Over", "Under", "Over", "Under"], start=1)
}


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
                {"id": "P3", "raison": "r1"}, {"id": "P4", "raison": "r2"}]}),
            _msg_outil("voir_catalogue", {}),  # profil 3/3
            _msg_outil("proposer_coupon", {"strategie": "s3", "jambes": [
                {"id": "P5", "raison": "r1"}, {"id": "P6", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1, PROFIL_2, PROFIL_3]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
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

    def test_meme_pari_refuse_dans_un_profil_suivant(self):
        # Demande explicite du 30/09/2026 : "ne choisis pas au profil suivant ce que le profil
        # précédent a déjà choisi" — Python doit refuser P1/P2 dans le 2e profil puisqu'ils ont
        # déjà été verrouillés dans le 1er, forçant l'IA à proposer autre chose (P3/P4 ici).
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),  # profil 1/3
            _msg_outil("proposer_coupon", {"strategie": "s1", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("voir_catalogue", {}),  # profil 2/3, tentative 1 (refusée)
            _msg_outil("proposer_coupon", {"strategie": "s2", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("proposer_coupon", {"strategie": "s2 corrigé", "jambes": [
                {"id": "P3", "raison": "r1"}, {"id": "P4", "raison": "r2"}]}),
            _msg_outil("voir_catalogue", {}),  # profil 3/3
            _msg_outil("proposer_coupon", {"strategie": "s3", "jambes": [
                {"id": "P5", "raison": "r1"}, {"id": "P6", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1, PROFIL_2, PROFIL_3]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]) as appel:
            resultat = pilote.executer(mission="test", telegram=True)

        self.assertTrue(resultat["termine"])
        self.assertTrue(resultat["envoye"])
        # Le message renvoyé à l'IA après la tentative refusée mentionne bien la vraie cause.
        messages_4e_appel = appel.call_args_list[4].args[1]
        contenus_outils = [m["content"] for m in messages_4e_appel if m.get("role") == "tool"]
        self.assertTrue(any("déjà utilisé dans un autre profil" in c for c in contenus_outils))

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
                {"id": "P3", "raison": "r1"}, {"id": "P4", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1, PROFIL_2, PROFIL_3]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
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

    def test_ticket_affiche_la_cote_totale_et_la_strategie(self):
        # Demande explicite du 30/09/2026 : "il ecrit affiche pas les envoie telegrame les
        # cote total et raisonnement total" — chaque ticket doit reprendre la stratégie donnée
        # par l'IA (paramètre "strategie" de proposer_coupon) et la cote totale combinée.
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),  # profil 1/3
            _msg_outil("proposer_coupon", {"strategie": "double sécurité sur des favoris nets", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}),
            _msg_outil("voir_catalogue", {}),  # profil 2/3
            _msg_outil("proposer_coupon", {"strategie": "s2", "jambes": [
                {"id": "P3", "raison": "r1"}, {"id": "P4", "raison": "r2"}]}),
            _msg_outil("voir_catalogue", {}),  # profil 3/3
            _msg_outil("proposer_coupon", {"strategie": "s3", "jambes": [
                {"id": "P5", "raison": "r1"}, {"id": "P6", "raison": "r2"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1, PROFIL_2, PROFIL_3]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True) as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=True)

        self.assertTrue(resultat["termine"])
        textes_envoyes = envoi.call_args.args[0]
        # La stratégie de l'IA est reprise telle quelle dans le ticket du profil.
        self.assertIn("double sécurité sur des favoris nets", textes_envoyes[0])
        # La cote totale combinée (1.8 * 1.8 = 3.24) est affichée.
        self.assertIn("Cote totale", textes_envoyes[0])
        self.assertIn("3.24", textes_envoyes[0])

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


class TestProfilsPersonnalisesEtDiversiteIgnoree(unittest.TestCase):
    """Demande explicite du 01/10/2026 (run ponctuel) : "je veux 6 coupon [...] je veux que tu
    oublies les profils et leur diversité, travaille comme si c'était le premier profil" —
    executer() accepte un paramètre profils (remplace ae.PROFILS_COUPON pour CE run seulement)
    et ignorer_diversite_croisee (désactive la diversité de catégorie entre profils, jamais
    l'anti-doublon exact)."""

    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": "cle-test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    PROFILS_6 = [
        {"cle": f"p{i}", "nom": f"Profil {i}", "cote_min": 0.0, "cote_max": 1000.0,
         "nb_jambes_min": 1, "nb_jambes": 1}
        for i in range(1, 7)
    ]

    def test_executer_avec_profils_personnalises_ignore_ae_profils_coupon(self):
        # POOL_SIX_MATCHS n'a qu'un seul candidat par match (P1..P6) : chaque profil (1 jambe
        # max) consomme exactement un match différent, sans jamais réutiliser le même pari.
        reponses = [_msg_outil("collecter_donnees", {})]
        for i in range(6):
            reponses.append(_msg_outil("voir_catalogue", {}))
            reponses.append(_msg_outil("proposer_coupon", {"strategie": f"s{i}", "jambes": [
                {"id": f"P{i + 1}", "raison": "r1"}]}))
        reponses.append(_msg_outil("envoyer_telegram", {}))

        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL_SIX_MATCHS), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True) as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=True,
                                       profils=self.PROFILS_6, ignorer_diversite_croisee=True)

        self.assertTrue(resultat["termine"])
        self.assertTrue(resultat["envoye"])
        # 6 profils composés, PAS 1 (ae.PROFILS_COUPON, mocké à un seul profil, est bien ignoré).
        self.assertEqual(len(resultat["resultats_profils"]), 6)
        self.assertEqual([r["profil"]["cle"] for r in resultat["resultats_profils"]],
                         [f"p{i}" for i in range(1, 7)])
        textes_envoyes = envoi.call_args.args[0]
        self.assertEqual(len(textes_envoyes), 6)

    def test_prompt_et_schemas_mentionnent_le_bon_nombre_de_profils(self):
        prompt = pilote.construire_prompt_systeme(self.PROFILS_6)
        self.assertIn("6 coupons", prompt)
        self.assertIn("Profil 1", prompt)
        schemas = pilote.construire_outils_schemas(self.PROFILS_6)
        voir_catalogue = next(s for s in schemas if s["function"]["name"] == "voir_catalogue")
        self.assertIn("parmi les 6", voir_catalogue["function"]["description"])
        envoyer = next(s for s in schemas if s["function"]["name"] == "envoyer_telegram")
        self.assertIn("6 coupons", envoyer["function"]["description"])

    def test_sans_parametre_profils_executer_garde_le_comportement_par_defaut(self):
        # Compatibilité : profils=None (défaut) continue d'utiliser ae.PROFILS_COUPON tel quel,
        # exactement comme avant l'ajout de ce paramètre.
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
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=True)

        self.assertTrue(resultat["termine"])
        self.assertEqual(len(resultat["resultats_profils"]), 1)
        self.assertEqual(resultat["resultats_profils"][0]["profil"]["cle"], "coupon")


class TestContexteSupplementaireEtRegleDeProbabiliteReelle(unittest.TestCase):
    """Demande explicite du 01/10/2026 ("augmente les chances de gagner [...] l'IA doit se
    souvenir du contexte") : le prompt système insiste sur la probabilité réelle plutôt que la
    cote cible à tout prix, et executer() peut prépendre un bilan réel (contexte_supplementaire,
    typiquement backend.app.services.statistiques.resume_pour_ia) à la mission par défaut."""

    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": "cle-test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_prompt_systeme_insiste_sur_la_probabilite_reelle(self):
        prompt = pilote.construire_prompt_systeme([PROFIL])
        # Depuis le 01/10/2026 ("il faut que Python calcule tout, ne donne pas à l'IA à
        # calculer") : la base de décision est la probabilité CALCULÉE PAR PYTHON, pas une
        # estimation de l'IA.
        self.assertIn("PROBABILITÉ PYTHON DU CATALOGUE", prompt)
        self.assertIn("N'EMPILE PAS PLUSIEURS JAMBES FRAGILES", prompt)
        self.assertIn("BILAN RÉEL DES COUPONS PRÉCÉDENTS", prompt)
        # Demande explicite du 01/10/2026 : "au lieu de 4 jambes avec cote +1.5, mieux 9 jambes
        # avec cote -1.5" (clarifié : la cote unitaire décimale, pas la ligne de handicap) —
        # préférer empiler des favoris à cote basse plutôt que peu de jambes à cote élevée.
        self.assertIn("PROBABILITÉ PYTHON ÉLEVÉE", prompt)
        self.assertIn("1.1-1.5", prompt)

    def test_contexte_supplementaire_prepende_a_la_mission_par_defaut(self):
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(pilote, "piloter", return_value={
                    "termine": True, "etapes": 0, "arret": "test", "tokens": 0}) as faux_piloter:
            pilote.executer(telegram=False, profils=[PROFIL],
                           contexte_supplementaire="BILAN RÉEL DES COUPONS PRÉCÉDENTS : 1/2 gagnés.")

        mission_envoyee = faux_piloter.call_args.args[3]
        self.assertTrue(mission_envoyee.startswith("BILAN RÉEL DES COUPONS PRÉCÉDENTS : 1/2 gagnés."))
        self.assertIn("Compose les 1 coupons combinés du jour.", mission_envoyee)

    def test_sans_contexte_supplementaire_mission_par_defaut_inchangee(self):
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(pilote, "piloter", return_value={
                    "termine": True, "etapes": 0, "arret": "test", "tokens": 0}) as faux_piloter:
            pilote.executer(telegram=False, profils=[PROFIL])

        mission_envoyee = faux_piloter.call_args.args[3]
        self.assertEqual(mission_envoyee, "Compose les 1 coupons combinés du jour.")

    def test_mission_explicite_ignore_le_contexte_supplementaire(self):
        # Si l'appelant fournit mission explicitement, c'est lui qui compose le texte complet —
        # contexte_supplementaire n'est utilisé que pour construire la mission PAR DÉFAUT.
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(pilote, "piloter", return_value={
                    "termine": True, "etapes": 0, "arret": "test", "tokens": 0}) as faux_piloter:
            pilote.executer(mission="mission explicite", telegram=False, profils=[PROFIL],
                           contexte_supplementaire="ignoré")

        mission_envoyee = faux_piloter.call_args.args[3]
        self.assertEqual(mission_envoyee, "mission explicite")


if __name__ == "__main__":
    unittest.main()


class TestAgentsFamillesBranchesDansLePilote(unittest.TestCase):
    """20/10/2026, constat réel (run 170) : les agents de famille n'étaient branchés que dans
    composer_coupons, jamais dans le moteur agent — voir_catalogue doit les appliquer."""

    def setUp(self):
        for cle, valeur in (("DEEPSEEK_API_KEY", "cle-test"), ("AGENTS_FAMILLES_ACTIFS", "1")):
            patcher = mock.patch.dict("os.environ", {cle: valeur})
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_voir_catalogue_applique_les_vetos_des_agents_de_famille(self):
        pool = {
            "M1 vs A1": [{"match": "M1 vs A1", "pick": _pick("Total", "Total (2.5)", "Over", 1.8)}],
            "M2 vs A2": [{"match": "M2 vs A2", "pick": dict(_pick("Total", "Total (2.5)", "Under", 1.8),
                                                            edge_pct=45.0)}],  # edge suspect -> veto
        }
        reponses = [
            _msg_outil("collecter_donnees", {}),
            _msg_outil("voir_catalogue", {}),
            _msg_outil("proposer_coupon", {"strategie": "s", "jambes": [{"id": "P1", "raison": "r"}]}),
            _msg_outil("envoyer_telegram", {}),
        ]
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL_1]), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool), \
                mock.patch.object(ae, "budget_ia_epuise", return_value=True), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True), \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]), \
                mock.patch("agents_familles.revoir_catalogue", wraps=agents_familles.revoir_catalogue) as revue:
            pilote.executer(mission="test", telegram=True)

        # P2 (edge suspect) a été écarté par le veto Python avant d'être montré à l'IA pilote.
        self.assertEqual(revue.call_count, 1)
        catalogue_revu = revue.call_args.args[0]
        self.assertEqual(sorted(catalogue_revu), ["P1", "P2"])
        self.assertIsNotNone(agents_familles.veto_python(catalogue_revu["P2"]["pick"]))
        self.assertIsNone(agents_familles.veto_python(catalogue_revu["P1"]["pick"]))


class TestMinimumDeJambesAdaptatifEtAbstentionSansTelegram(unittest.TestCase):
    """21/10/2026 : (1) un jour à peu de matchs ne doit pas condamner le profil 12-15 jambes à
    l'abstention ; (2) une abstention n'envoie plus de message Telegram."""

    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": "cle-test", "AGENTS_FAMILLES_ACTIFS": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _pool(self, n):
        return {f"M{i} vs A{i}": [{"match": f"M{i} vs A{i}", "pick": _pick("Total", "Total (2.5)", "Over", 1.5)}]
                for i in range(n)}

    def _executer(self, pool, reponses, profil):
        with mock.patch.object(cd, "collecter_donnees", return_value=None), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(DONNEES_FACTICES))), \
                mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool), \
                mock.patch.object(ae, "agent5_envoyer_coupons", return_value=True) as envoi, \
                mock.patch.object(pilote, "_appel_api", side_effect=[(r, 65536) for r in reponses]):
            resultat = pilote.executer(mission="test", telegram=True, profils=[profil])
        return resultat, envoi

    def test_minimum_ramene_au_nombre_de_matchs_du_jour(self):
        profil = {"cle": "jour", "nom": "J", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 12, "nb_jambes": 15}
        jambes = [{"id": f"P{i}", "raison": "r"} for i in range(1, 9)]
        reponses = [_msg_outil("collecter_donnees", {}), _msg_outil("voir_catalogue", {}),
                    _msg_outil("proposer_coupon", {"strategie": "s", "jambes": jambes}),
                    _msg_outil("envoyer_telegram", {})]
        resultat, envoi = self._executer(self._pool(8), reponses, profil)
        self.assertEqual(len(resultat["resultats_profils"][0]["selections"]), 8)  # 8 matchs -> 8 jambes
        envoi.assert_called_once()

    def test_sous_le_plancher_absolu_le_minimum_n_est_pas_abaisse(self):
        profil = {"cle": "jour", "nom": "J", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 12, "nb_jambes": 15}
        jambes = [{"id": f"P{i}", "raison": "r"} for i in range(1, 4)]
        reponses = [_msg_outil("collecter_donnees", {}), _msg_outil("voir_catalogue", {}),
                    _msg_outil("proposer_coupon", {"strategie": "s", "jambes": jambes}),
                    _msg_outil("abandonner", {"raison": "trop peu de matchs"})]
        resultat, envoi = self._executer(self._pool(3), reponses, profil)
        self.assertEqual(resultat["resultats_profils"], [])  # 3 matchs < 6 : le coupon de 3 jambes est refusé

    def test_abstention_n_envoie_aucun_message_telegram(self):
        profil = {"cle": "jour", "nom": "J", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes_min": 2, "nb_jambes": 5}
        reponses = [_msg_outil("collecter_donnees", {}), _msg_outil("voir_catalogue", {}),
                    _msg_outil("proposer_coupon", {"strategie": "rien de défendable", "jambes": []}),
                    _msg_outil("envoyer_telegram", {})]
        resultat, envoi = self._executer(self._pool(3), reponses, profil)
        envoi.assert_not_called()
        self.assertFalse(resultat["envoye"])


class TestSecoursGratuit(unittest.TestCase):
    """22/10/2026 : DeepSeek 402 « Insufficient Balance » arrêtait tout le run — bascule sur Groq/Gemini/OpenRouter."""

    def setUp(self):
        pilote._secours.update(actif=False, choix=None)
        self.env = mock.patch.dict(os.environ, {"GROQ_API_KEY": "g", "GEMINI_API_KEY": "", "OPENROUTER_API_KEY": "o",
                                                "UTILISER_OPENROUTER": "1",
                                                "GROQ_MODELES": "openai/gpt-oss-120b",
                                                "OPENROUTER_MODELES": "gratuit/modele:free"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(lambda: pilote._secours.update(actif=False, choix=None))

    @staticmethod
    def _reponse(code, corps=None):
        r = mock.Mock(status_code=code, content=b"x", text=json.dumps(corps or {}))
        r.json.return_value = corps or {}
        return r

    def test_402_deepseek_bascule_sur_groq(self):
        ok = {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"total_tokens": 5}}
        appels = []

        def poster(url, **kw):
            appels.append((url, kw["json"]))
            if "deepseek" in url:
                return self._reponse(402, {"error": {"message": "Insufficient Balance"}})
            return self._reponse(200, ok)

        messages = [{"role": "assistant", "content": "", "reasoning_content": "pensée DeepSeek"}]
        data, _ = pilote._appel_api("cle", messages, 65536, poster=poster, pause=lambda s: None)
        self.assertEqual(data, ok)
        self.assertTrue(pilote._secours["actif"])
        url_secours, charge = appels[-1]
        self.assertIn("openrouter", url_secours)                              # OpenRouter/DeepSeek d'abord
        self.assertEqual(charge["model"], "deepseek/deepseek-v4.1-flash")
        self.assertNotIn("reasoning_content", charge["messages"][0])        # champ propre à DeepSeek retiré
        self.assertEqual(charge["max_tokens"], pilote.MAX_TOKENS_SECOURS)    # plafonné pour les gratuits
        # Étape suivante : DeepSeek n'est plus réessayé
        appels.clear()
        pilote._appel_api("cle", messages, 65536, poster=poster, pause=lambda s: None)
        self.assertTrue(all("deepseek" not in u for u, _ in appels))

    def test_fournisseur_suivant_quand_le_premier_echoue(self):
        ok = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

        def poster(url, **kw):
            if "openrouter" in url:
                return self._reponse(429, {})
            return self._reponse(200, ok)

        data, _ = pilote._appel_secours([{"role": "user", "content": "x"}], 4096, poster=poster)
        self.assertEqual(data, ok)
        self.assertIn("groq", pilote._secours["choix"][1])    # OpenRouter en 429 -> fournisseur suivant

    def test_openrouter_desactive_par_defaut_et_deepseek_plateforme_principal(self):
        # 25/10/2026 : « IA principale = plateforme DeepSeek, oublie OpenRouter »
        self.assertEqual(pilote.FOURNISSEUR_PRINCIPAL, "deepseek")
        with mock.patch.dict(os.environ, {"UTILISER_OPENROUTER": ""}):
            self.assertIsNone(pilote._cle_openrouter())
            noms = [c[0] for c in pilote._fournisseurs_secours()]
            self.assertNotIn("OpenRouter", noms)
            self.assertFalse(pilote._secours_d_emblee())
        with mock.patch.dict(os.environ, {"UTILISER_OPENROUTER": "1"}):
            self.assertEqual(pilote._cle_openrouter(), "o")

    def test_openrouter_deepseek_par_defaut_des_le_debut_du_run(self):
        with mock.patch.object(pilote, "FOURNISSEUR_PRINCIPAL", "openrouter"):
            self.assertTrue(pilote._secours_d_emblee())
        with mock.patch.object(pilote, "FOURNISSEUR_PRINCIPAL", "deepseek"):
            self.assertFalse(pilote._secours_d_emblee())
        with mock.patch.object(pilote, "FOURNISSEUR_PRINCIPAL", "openrouter"), \
                mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            self.assertFalse(pilote._secours_d_emblee())   # sans clé OpenRouter : DeepSeek officiel d'abord

    def test_openrouter_deepseek_est_en_tete_de_liste(self):
        premier = pilote._fournisseurs_secours()[0]
        self.assertEqual((premier[0], premier[3]), ("OpenRouter", "deepseek/deepseek-v4.1-flash"))

    def test_sans_cle_deepseek_direct_sur_le_secours(self):
        ok = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        data, _ = pilote._appel_api(None, [{"role": "user", "content": "x"}], 4096,
                                    poster=lambda url, **kw: self._reponse(200, ok))
        self.assertEqual(data, ok)

    def test_erreur_deepseek_remontee_sans_secours_configure(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENROUTER_API_KEY": "", "GEMINI_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                pilote._appel_api("cle", [], 4096, pause=lambda s: None,
                                  poster=lambda url, **kw: self._reponse(402, {"error": {"message": "Insufficient Balance"}}))

    def test_tous_les_secours_en_echec_leve_une_erreur_claire(self):
        with self.assertRaises(RuntimeError) as ctx:
            pilote._appel_secours([], 4096, poster=lambda url, **kw: self._reponse(500, {}))
        self.assertIn("Aucun fournisseur de secours", str(ctx.exception))
