"""Tests hors-ligne de l'agent pilote DeepSeek (executer() branché sur collecte/analyse
réelles, moteur piloter() simulé) : python -m unittest test_agent_pilote"""
import json
import unittest
from unittest import mock

import agent_pilote as pilote
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


def _pick(categorie, marche, selection, cote):
    return {"categorie": categorie, "marche": marche, "handicap": 2.5, "selection": selection, "cote": cote,
            "proba_modele_pct": None, "edge_pct": None, "proba_poisson_pct": None, "proba_marche_pct": None}


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
        self.assertTrue(any("déjà choisi dans un autre profil" in c for c in contenus_outils))

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
        self.assertIn("PROBABILITÉ RÉELLE DE GAIN", prompt)
        self.assertIn("N'EMPILE PAS PLUSIEURS JAMBES FRAGILES", prompt)
        self.assertIn("BILAN RÉEL DES COUPONS PRÉCÉDENTS", prompt)
        # Demande explicite du 01/10/2026 : "au lieu de 4 jambes avec cote +1.5, mieux 9 jambes
        # avec cote -1.5" (clarifié : la cote unitaire décimale, pas la ligne de handicap) —
        # préférer empiler des favoris à cote basse plutôt que peu de jambes à cote élevée.
        self.assertIn("COTE INDIVIDUELLE BASSE", prompt)
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
