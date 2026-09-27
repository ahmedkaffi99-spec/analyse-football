"""Tests hors-ligne de l'agent orchestrateur agentique (IA simulée, aucun appel réseau) :
python -m unittest test_agent_orchestrateur_ia"""
import json
import unittest
from unittest import mock

import agent_orchestrateur_ia as orch
import analyser_et_envoyer as ae


def _sel(match, categorie, selection, cote, edge=6.0):
    return {"match": match, "home_nom": match.split(" vs ")[0], "away_nom": match.split(" vs ")[1],
            "fixture_id_oddspapi": match,
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)", "handicap": 2.5, "selection": selection,
                     "cote": cote, "proba_modele_pct": 60.0, "edge_pct": edge, "guide": "g", "onglet": "o",
                     "proba_poisson_pct": 64.0, "proba_marche_pct": 58.0},
            "contexte": {"contexte_web": [], "elo": {}, "buts_attendus": {"domicile": 1.5, "exterieur": 1.0}}}


POOL = {
    "A vs B": [_sel("A vs B", "Total", "Over", 1.6)],    # P1
    "C vs D": [_sel("C vs D", "Total", "Under", 1.5)],   # P2
    "E vs F": [_sel("E vs F", "Total", "Over", 2.0)],    # P3
}

PROFIL = {"cle": "coupon", "nom": "🎯 COUPON", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 3, "nb_jambes_min": 2}


def _msg_outils(*appels):
    return {"role": "assistant", "tool_calls": [
        {"id": str(i), "function": {"name": nom, "arguments": json.dumps(args)}}
        for i, (nom, args) in enumerate(appels, start=1)
    ]}


class TestBoucleAgentique(unittest.TestCase):
    def test_scenario_complet_lister_analyser_risque_verifier_corriger_envoyer(self):
        reponses = [
            _msg_outils(("lister_matchs", {})),
            _msg_outils(("analyser_match", {"match": "A vs B"}), ("analyser_match", {"match": "C vs D"})),
            _msg_outils(("consulter_avis_risque", {"id": "P1", "raison": "edge positif, forme correcte"})),
            _msg_outils(("verifier_coupon", {"strategie": "s", "jambes": [{"id": "P1", "raison": "r1"}]})),
            _msg_outils(("envoyer_telegram", {"strategie": "s",
                                              "jambes": [{"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]})),
        ]
        appel = mock.Mock(side_effect=reponses)

        with mock.patch.object(ae, "appel_llm", return_value="Pari défendable, edge cohérent."):
            resultat = orch.composer_coupon_agentique(POOL, PROFIL, appel_outils=appel)

        self.assertEqual(appel.call_count, 5)
        self.assertIsNotNone(resultat)
        self.assertEqual({s["match"] for s in resultat["selections"]}, {"A vs B", "C vs D"})
        self.assertEqual(resultat["strategie"], "s")

        # verifier_coupon (tour 4) doit avoir signalé le manque de jambes (nb_jambes_min=2)
        messages_tool = [m for m in appel.call_args_list[4].args[0] if m.get("role") == "tool"]
        self.assertTrue(any("paris valides" in m["content"] or "il en faut entre" in m["content"]
                            for m in messages_tool))

    def test_texte_analyser_match_contient_les_bons_identifiants(self):
        reponses = [
            _msg_outils(("analyser_match", {"match": "A vs B"})),
            _msg_outils(("envoyer_telegram", {"strategie": "s", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]})),
        ]
        appel = mock.Mock(side_effect=reponses)
        orch.composer_coupon_agentique(POOL, PROFIL, appel_outils=appel)

        messages_apres_analyse = appel.call_args_list[1].args[0]
        contenu_outil = [m["content"] for m in messages_apres_analyse if m.get("role") == "tool"][0]
        self.assertIn("P1", contenu_outil)
        self.assertIn("Total (2.5) → Over @ 1.6", contenu_outil)

    def test_match_inconnu_ne_plante_pas(self):
        reponses = [
            _msg_outils(("analyser_match", {"match": "Inconnu vs Fantome"})),
            _msg_outils(("envoyer_telegram", {"strategie": "s", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]})),
        ]
        appel = mock.Mock(side_effect=reponses)
        resultat = orch.composer_coupon_agentique(POOL, PROFIL, appel_outils=appel)
        self.assertIsNotNone(resultat)  # a quand même pu se rattraper au tour suivant

    def test_reponse_sans_outil_est_relancee(self):
        reponses = [
            {"role": "assistant", "content": "Je réfléchis..."},  # pas d'outil : doit être relancé
            _msg_outils(("envoyer_telegram", {"strategie": "s", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]})),
        ]
        appel = mock.Mock(side_effect=reponses)
        resultat = orch.composer_coupon_agentique(POOL, PROFIL, appel_outils=appel)
        self.assertEqual(appel.call_count, 2)
        self.assertIsNotNone(resultat)

    def test_echec_ia_renvoie_none_pour_repli(self):
        appel = mock.Mock(side_effect=ValueError("DeepSeek indisponible"))
        resultat = orch.composer_coupon_agentique(POOL, PROFIL, appel_outils=appel)
        self.assertIsNone(resultat)

    def test_sans_conclusion_apres_max_tours_renvoie_none(self):
        appel = mock.Mock(return_value=_msg_outils(("lister_matchs", {})))
        resultat = orch.composer_coupon_agentique(POOL, PROFIL, appel_outils=appel)
        self.assertIsNone(resultat)
        self.assertEqual(appel.call_count, orch.MAX_TOURS_AGENT)

    def test_identifiant_invente_est_refuse_par_verifier_coupon(self):
        reponses = [
            _msg_outils(("verifier_coupon", {"strategie": "s", "jambes": [{"id": "P99", "raison": "invente"}]})),
            _msg_outils(("envoyer_telegram", {"strategie": "s", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]})),
        ]
        appel = mock.Mock(side_effect=reponses)
        orch.composer_coupon_agentique(POOL, PROFIL, appel_outils=appel)
        messages_apres = appel.call_args_list[1].args[0]
        contenu_outil = [m["content"] for m in messages_apres if m.get("role") == "tool"][0]
        self.assertIn("identifiant inconnu", contenu_outil)


class TestAgentRisqueUtilisePetitesTaches(unittest.TestCase):
    def test_avis_risque_passe_par_appel_llm_petites_taches_pas_deepseek(self):
        # Demande explicite du 27/09/2026 : le second avis (petite tâche) doit renforcer
        # Groq/Gemini/OpenRouter gratuits, jamais consommer le solde payant de DeepSeek.
        with mock.patch.object(ae, "appel_llm_petites_taches", return_value="Pari défendable.") as petite, \
                mock.patch.object(ae, "appel_llm") as principal:
            avis = orch._agent_risque(POOL["A vs B"][0], "edge positif")
        self.assertEqual(avis, "Pari défendable.")
        petite.assert_called_once()
        principal.assert_not_called()


class TestIntegrationGenererCoupons(unittest.TestCase):
    def test_mode_agentique_utilise_par_generer_coupons(self):
        reponses = [
            _msg_outils(("envoyer_telegram", {"strategie": "choix agentique", "jambes": [
                {"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]})),
        ]
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "MODE_AGENTIC", True), \
                mock.patch.object(ae, "appel_ia_avec_outils", side_effect=reponses):
            resultats = ae.generer_coupons({"matchs": []})
        self.assertEqual(len(resultats), 1)
        self.assertEqual(resultats[0]["strategie"], "choix agentique")
        self.assertEqual(len(resultats[0]["selections"]), 2)

    def test_repli_sur_stratege_classique_si_agentique_echoue(self):
        reponse_classique = json.dumps({"analyse_matchs": [], "coupons": [
            {"profil": "coupon", "strategie": "repli classique",
             "jambes": [{"id": "P1", "raison": "r1"}, {"id": "P2", "raison": "r2"}]}]})
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL), \
                mock.patch.object(ae, "PROFILS_COUPON", [PROFIL]), \
                mock.patch.object(ae, "MODE_AGENTIC", True), \
                mock.patch.object(ae, "appel_ia_avec_outils", side_effect=ValueError("indisponible")), \
                mock.patch.object(ae, "appel_llm", return_value=reponse_classique), mock.patch.object(ae.time, "sleep"):
            resultats = ae.generer_coupons({"matchs": []})
        self.assertEqual(resultats[0]["strategie"], "repli classique")


if __name__ == "__main__":
    unittest.main()
