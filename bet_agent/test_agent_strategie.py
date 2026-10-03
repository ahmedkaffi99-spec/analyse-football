"""Tests hors-ligne de l'agent stratège IA (IA simulée) : python -m unittest test_agent_strategie"""
import json
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

import agent_strategie as st
import analyser_et_envoyer as ae

PROFILS = [
    {"cle": "profil1", "nom": "🛡️ COUPON 1", "cote_min": 2.0, "cote_max": 4.0, "nb_jambes": 4},
    {"cle": "profil2", "nom": "⚖️ COUPON 2", "cote_min": 4.0, "cote_max": 12.0, "nb_jambes": 4},
]

# La plupart des tests de ce module utilisent des pools factices à cotes volontairement
# petites (1.2-2.0) pour isoler UNE règle précise (diversité, doublon...), sans rapport avec
# le plancher ABSOLU de cote totale ajouté le 01/10/2026 (demande explicite : "interdit les
# cote total moins de 5" — voir st.COTE_TOTALE_MIN). Désactivé par défaut pour tout ce
# fichier ; TestCoteTotaleMinimale le réactive explicitement pour le tester.
def setUpModule():
    global _PATCHEUR_COTE_MIN
    _PATCHEUR_COTE_MIN = mock.patch.object(st, "COTE_TOTALE_MIN", 0.0)
    _PATCHEUR_COTE_MIN.start()


def tearDownModule():
    _PATCHEUR_COTE_MIN.stop()


def _sel(match, categorie, selection, cote):
    return {"match": match, "home_nom": match.split(" vs ")[0], "away_nom": match.split(" vs ")[1],
            "fixture_id_oddspapi": match,
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)", "handicap": 2.5, "selection": selection,
                     "cote": cote, "proba_modele_pct": 75.0, "edge_pct": 6.0, "guide": "g", "onglet": "o",
                     "proba_poisson_pct": 64.0, "proba_marche_pct": 58.0},
            "contexte": {"contexte_web": [], "elo": {}, "buts_attendus": {"domicile": 1.5, "exterieur": 1.0}}}


POOL = {
    "A vs B": [_sel("A vs B", "Total", "Over", 1.6), _sel("A vs B", "BTTS", "Yes", 1.8)],   # P1, P2
    "C vs D": [_sel("C vs D", "Total", "Under", 1.5), _sel("C vs D", "BTTS", "No", 1.9)],   # P3, P4
    "E vs F": [_sel("E vs F", "Total", "Over", 2.0),                                        # P5
               _sel("E vs F", "Handicap Asiatique", "1", 2.0)],                             # P6
}


def _reponse(coupons, analyse=None):
    return json.dumps({"analyse_matchs": analyse or [{"match": "A vs B", "fiabilite": "haute", "avis": "ok"}],
                       "coupons": coupons}, ensure_ascii=False)


class TestStratege(unittest.TestCase):
    def test_catalogue_identifiants_et_chiffres(self):
        catalogue, texte = st.construire_catalogue(POOL)
        self.assertEqual(list(catalogue), ["P1", "P2", "P3", "P4", "P5", "P6"])
        self.assertIn("P5 : Total (2.5) → Over @ 2.0", texte)
        # Depuis le 01/10/2026 : Python affiche sa probabilité/edge calculés à l'IA (demande
        # explicite "il faut que Python calcule tout, ne donne pas à l'IA à calculer").
        self.assertIn("probabilité Python 75.0%, edge 6.0%", texte)

    def test_catalogue_exclut_les_marches_bruts_sans_calcul(self):
        # Depuis le 01/10/2026 ("réduire les tâches de l'IA, augmenter Python") : un marché
        # brut (aucune probabilité calculable) n'est PLUS montré du tout à l'IA — Python ne
        # peut pas le vérifier, donc il ne le propose plus comme matière à décision.
        pool_brut = {"A vs B": [{
            "match": "A vs B", "home_nom": "A", "away_nom": "B", "fixture_id_oddspapi": "A vs B",
            "pick": {"categorie": "Corners", "marche": "Corners (9.5)", "handicap": 9.5, "selection": "Over",
                     "cote": 1.9, "proba_modele_pct": None, "edge_pct": None, "guide": "g", "onglet": "o"},
            "contexte": {},
        }]}
        catalogue, texte = st.construire_catalogue(pool_brut)
        self.assertEqual(catalogue, {})
        self.assertEqual(texte, "")

    def test_catalogue_exclut_les_probabilites_sous_le_seuil(self):
        pool_faible = {"A vs B": [{
            "match": "A vs B", "pick": {"categorie": "Total", "marche": "Total (2.5)", "selection": "Over",
                                        "cote": 1.9, "proba_modele_pct": 52.0, "edge_pct": 3.0},
        }]}
        catalogue, texte = st.construire_catalogue(pool_faible)
        self.assertEqual(catalogue, {})
        self.assertEqual(texte, "")

    def test_catalogue_trie_par_probabilite_decroissante(self):
        pool = {"A vs B": [
            {"match": "A vs B", "pick": {"categorie": "Total", "marche": "Total (2.5)", "selection": "Over",
                                         "cote": 1.6, "proba_modele_pct": 72.0, "edge_pct": 4.0}},
            {"match": "A vs B", "pick": {"categorie": "BTTS", "marche": "BTTS", "selection": "Yes",
                                         "cote": 1.7, "proba_modele_pct": 80.0, "edge_pct": 5.0}},
        ]}
        _, texte = st.construire_catalogue(pool)
        # BTTS (80%) doit apparaître AVANT Total (72%), même si listé en second dans le pool.
        self.assertLess(texte.index("BTTS"), texte.index("Total (2.5)"))

    def test_choix_valide_des_le_premier_tour(self):
        # P1 (Total) + P4 (BTTS) : catégories différentes, pas de souci de dominance (règle du
        # 30/09/2026) ; idem P2 (BTTS) + P3 (Total) + P6 (Handicap) pour profil2.
        reponse = _reponse([
            {"profil": "profil1", "strategie": "Paris solides", "jambes": [{"id": "P1", "raison": "r1"}, {"id": "P4", "raison": "r3"}]},
            {"profil": "profil2", "strategie": "Plus audacieux", "jambes": [
                {"id": "P2", "raison": "r2"}, {"id": "P3", "raison": "r4"}, {"id": "P6", "raison": "r5"}]},
        ])
        appel = mock.Mock(return_value="```json\n" + reponse + "\n```")
        resultat = st.composer_coupons(POOL, PROFILS, appel=appel)
        self.assertEqual(appel.call_count, 1)
        p1 = resultat["coupons"]["profil1"]
        self.assertEqual([s["pick"]["selection"] for s in p1["selections"]], ["Over", "No"])
        self.assertEqual(p1["selections"][0]["raison_ia"], "r1")
        self.assertEqual(p1["strategie"], "Paris solides")

    def test_erreurs_renvoyees_a_l_ia_qui_corrige(self):
        mauvaise = _reponse([
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P99"}]},  # id inventé
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P2"}]},    # 2 paris sur A vs B
        ])
        bonne = _reponse([
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P4"}]},
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P2"}, {"id": "P3"}, {"id": "P6"}]},
        ])
        appel = mock.Mock(side_effect=[mauvaise, bonne])
        resultat = st.composer_coupons(POOL, PROFILS, appel=appel)
        self.assertEqual(appel.call_count, 2)
        second_prompt = appel.call_args_list[1].args[0]
        self.assertIn("identifiant inconnu « P99 »", second_prompt)
        self.assertIn("2 paris sur A vs B (maximum 1)", second_prompt)
        # Cote totale : plus jamais une erreur depuis le 01/10/2026 (indicative uniquement).
        self.assertNotIn("trop basse", second_prompt)
        self.assertNotIn("trop haute", second_prompt)
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

    def test_selection_12_acceptee_comme_n_importe_quel_autre_marche(self):
        # Interdiction retirée le 01/10/2026 (demande explicite : "il peut sélectionner 12 et
        # n'importe quelle cote si le taux de réussite est élevé") — "12" n'a plus de traitement
        # spécial, acceptée comme n'importe quelle autre sélection valide du catalogue.
        pool_avec_12 = dict(POOL, **{
            "C vs D": [_sel("C vs D", "Double Chance", "12", 1.25)],
        })
        catalogue, _ = st.construire_catalogue(pool_avec_12)
        cid_12 = next(cid for cid, c in catalogue.items() if c["pick"]["selection"] == "12")
        proposition = {"coupons": [
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": cid_12}, {"id": "P4"}]},
        ]}
        acceptes, problemes, _ = st.valider(proposition, catalogue, PROFILS)
        self.assertFalse(any("interdite" in p or "12" in p for p in problemes), problemes)
        self.assertIn("profil1", acceptes)

    def test_cote_totale_hors_fourchette_n_est_plus_une_erreur(self):
        # Demande explicite du 01/10/2026 : "ne oblige pas l'IA à atteindre le 50+ et 15-50,
        # mon but c'est tout cote individuel et total qui a la chance de réussite élevée" — la
        # cote totale est désormais purement indicative, jamais une cause de rejet, même très
        # loin de la fourchette du profil (profil1 vise 2.0-4.0, on lui donne un coupon à 1.6).
        catalogue, _ = st.construire_catalogue(POOL)
        proposition = {"coupons": [
            # P2*P3*P6 = 1.8*1.5*2.0 = 5.4, un match et une catégorie différents chacun,
            # largement hors 2.0-4.0.
            {"profil": "profil1", "strategie": "s",
             "jambes": [{"id": "P2"}, {"id": "P3"}, {"id": "P6"}]},
        ]}
        acceptes, problemes, calculs = st.valider(proposition, catalogue, [PROFILS[0]])
        self.assertEqual(problemes, [])
        self.assertIn("profil1", acceptes)
        self.assertTrue(any("cote totale 5.40" in c for c in calculs), calculs)
        self.assertFalse(any("trop basse" in c or "trop haute" in c for c in calculs), calculs)

    def test_abstention_acceptee(self):
        reponse = _reponse([
            {"profil": "profil1", "strategie": "Aucune valeur fiable aujourd'hui", "jambes": []},
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P2"}, {"id": "P3"}, {"id": "P6"}]},
        ])
        resultat = st.composer_coupons(POOL, PROFILS, appel=mock.Mock(return_value=reponse))
        self.assertEqual(resultat["coupons"]["profil1"]["abstention"], "Aucune valeur fiable aujourd'hui")

    def test_ia_inexploitable_repli_automatique(self):
        self.assertIsNone(st.composer_coupons(POOL, PROFILS, appel=mock.Mock(return_value="Je ne sais pas")))

    def test_integration_generer_coupons_plusieurs_profils(self):
        # Vérifie que le pipeline reste générique à N profils (PROFILS_COUPON n'en définit
        # qu'un seul par défaut depuis le 26/09/2026, mais le code doit supporter plusieurs).
        reponse = _reponse([
            {"profil": "profil1", "strategie": "Stratégie sûre", "jambes": [{"id": "P1", "raison": "r"}, {"id": "P4", "raison": "r"}]},
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P2"}, {"id": "P3"}, {"id": "P6"}]},
        ])
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL), \
                mock.patch.object(ae, "PROFILS_COUPON", PROFILS + [
                    {"cle": "profil3", "nom": "🔥 COUPON 3", "cote_min": 50.0, "cote_max": 100.0, "nb_jambes": 8}]), \
                mock.patch.object(ae, "UTILISER_STRATEGE_IA", True), \
                mock.patch.object(ae, "appel_llm", return_value=reponse), mock.patch.object(ae.time, "sleep"):
            resultats = ae.generer_coupons({"matchs": []})
        self.assertEqual(resultats[0]["strategie"], "Stratégie sûre")
        self.assertEqual(len(resultats[0]["selections"]), 2)
        self.assertEqual(len(resultats), 3)  # profil3 absent de la réponse IA → composition automatique

    def test_integration_generer_coupons_un_seul_profil(self):
        # PROFILS_COUPON par défaut depuis le 26/09/2026 : un seul coupon "smart".
        reponse = _reponse([
            {"profil": "coupon", "strategie": "Combiné du jour", "jambes": [{"id": "P2", "raison": "r"}, {"id": "P6", "raison": "r"}]},
        ])
        profil_unique = [{"cle": "coupon", "nom": "🎯 COUPON DU JOUR", "cote_min": 3.0, "cote_max": 50.0, "nb_jambes": 6}]
        with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=POOL), \
                mock.patch.object(ae, "PROFILS_COUPON", profil_unique), \
                mock.patch.object(ae, "UTILISER_STRATEGE_IA", True), \
                mock.patch.object(ae, "appel_llm", return_value=reponse), mock.patch.object(ae.time, "sleep"):
            resultats = ae.generer_coupons({"matchs": []})
        self.assertEqual(len(resultats), 1)
        self.assertEqual(resultats[0]["strategie"], "Combiné du jour")


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

    def test_un_compte_de_buts_n_est_jamais_lu_comme_une_cote(self):
        # Bug réel constaté le 01/10/2026 (run à 9 jambes) : "l'équipe marque à 2 buts" et
        # "plus de 3+ buts" déclenchaient à tort "ta raison cite la cote 2.0/3.0" alors que le
        # pari réel était à 1.43/3.14 — deux cycles de validation perdus pour une raison
        # correcte. Un entier NU (sans décimale) après "à"/"@" est un compte, jamais une cote
        # (toujours affichée avec décimale dans le catalogue).
        for raison, pick in [("l'équipe est favorite et marque à 2 buts d'écart habituellement",
                              {"cote": 1.43, "selection": "Over"}),
                             ("plus de 3+ buts au total (3.5 buts de moyenne sur les confrontations)",
                              {"cote": 3.14, "selection": "Over"}),
                             ("Total Équipe 2 : over 1.5 soutenu par la forme récente",
                              {"cote": 1.631, "selection": "Over"})]:
            self.assertIsNone(st.incoherence_raison(raison, pick), raison)
        # Un VRAI nombre décimal après "à"/"@" reste détecté (comportement inchangé).
        self.assertIn("cite la cote 2.0",
                      st.incoherence_raison("l'équipe marque à 2.0 buts en moyenne",
                                             {"cote": 1.43, "selection": "Over"}))

    def test_la_raison_incoherente_est_corrigee_au_tour_suivant(self):
        mauvaise = _reponse([
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1", "raison": "Under à 1.5"},
                                                             {"id": "P4", "raison": "r3"}]},
            {"profil": "profil2", "strategie": "s", "jambes": [
                {"id": "P2", "raison": "r2"}, {"id": "P3", "raison": "r4"}, {"id": "P6", "raison": "r5"}]}])
        bonne = _reponse([
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1", "raison": "Over à 1.6, buts attendus"},
                                                             {"id": "P4", "raison": "r3"}]}])
        appel = mock.Mock(side_effect=[mauvaise, bonne])
        resultat = st.composer_coupons(POOL, PROFILS, appel=appel)
        self.assertEqual(appel.call_count, 2)
        self.assertIn("P1 : ta raison", appel.call_args_list[1].args[0])  # le problème est renvoyé à l'IA
        p1 = resultat["coupons"]["profil1"]["selections"]
        self.assertEqual(p1[0]["raison_ia"], "Over à 1.6, buts attendus")


class TestFraicheurNePasEffacerSurErreurApi(unittest.TestCase):
    def test_statut_non_200_garde_les_matchs_au_lieu_de_les_effacer(self):
        # Run 16 (2026-09-26) : OddsPapi a répondu autre chose que 200 lors de la
        # revérification, et le code traitait ça comme "aucun match n'existe" — 5 matchs
        # avec de vraies cotes ont été jetés d'un coup, tous marqués "introuvable".
        matchs = [{"oddspapi": {"fixture_id": "id1"}, "match_demande": {"home": "A", "away": "B"}}]
        reponse_en_panne = mock.Mock(status_code=429, text="Too Many Requests")
        with mock.patch.object(ae.requests, "get", return_value=reponse_en_panne):
            self.assertEqual(ae.verifier_fraicheur_matchs(matchs), matchs)


class TestFraicheurSansAppelSiCollecteRecente(unittest.TestCase):
    """Demande explicite du 03/10/2026 ("utilisation d'OddsPapi diminuée") : juste après la
    collecte, l'heure de coup d'envoi déjà connue suffit — aucun appel OddsPapi."""

    def _match(self, depart):
        return {"oddspapi": {"fixture_id": "id1", "start_time": depart}, "match_demande": {"home": "A", "away": "B"}}

    def test_collecte_recente_aucun_appel_et_match_a_venir_garde(self):
        matchs = [self._match("2099-01-01T15:00:00Z")]
        recente = datetime.now(timezone.utc).isoformat()
        with mock.patch.object(ae.requests, "get") as appel:
            self.assertEqual(ae.verifier_fraicheur_matchs(matchs, recente), matchs)
        appel.assert_not_called()

    def test_collecte_recente_match_deja_commence_retire(self):
        matchs = [self._match("2000-01-01T15:00:00Z")]
        recente = datetime.now(timezone.utc).isoformat()
        with mock.patch.object(ae.requests, "get") as appel:
            self.assertEqual(ae.verifier_fraicheur_matchs(matchs, recente), [])
        appel.assert_not_called()

    def test_collecte_ancienne_revérifie_chez_oddspapi(self):
        matchs = [self._match("2099-01-01T15:00:00Z")]
        ancienne = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        reponse = mock.Mock(status_code=429, text="quota")
        with mock.patch.object(ae.requests, "get", return_value=reponse) as appel:
            ae.verifier_fraicheur_matchs(matchs, ancienne)
        appel.assert_called_once()


class TestDiversiteDesMarches(unittest.TestCase):
    """Demande explicite du 26/09/2026 : un coupon presque entièrement composé de paris
    Under/No (biais du modèle Poisson) est refusé par Python quand une alternative existe,
    même si le prompt le déconseille déjà — la règle 5 seule n'avait pas suffi en pratique
    (l'IA a justifié un coupon 100% Under/No comme "stratégie délibérée de faible variance")."""

    def test_trop_de_under_no_refuse_si_une_alternative_existe(self):
        pool = {
            "A vs B": [_sel("A vs B", "Total", "Under", 1.5)],                                    # P1 — pas d'alternative
            "C vs D": [_sel("C vs D", "Total", "Under", 1.5)],                                    # P2 — pas d'alternative
            "E vs F": [_sel("E vs F", "Total", "Under", 1.5)],                                    # P3 — pas d'alternative
            "G vs H": [_sel("G vs H", "Total", "Under", 1.5), _sel("G vs H", "Total", "Over", 1.5)],  # P4, P5 — alternative dispo
        }
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 4, "nb_jambes_min": 4}
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P2"}, {"id": "P3"}, {"id": "P4"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(acceptes, {})
        self.assertTrue(any("Under/No" in p and "G vs H" in p for p in problemes), problemes)

    def test_accepte_si_aucune_alternative_nulle_part(self):
        # Les 4 matchs n'offrent QUE du Under : impossible de varier, donc pas d'erreur.
        pool = {m: [_sel(m, "Total", "Under", 1.5)] for m in ("A vs B", "C vs D", "E vs F", "G vs H")}
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 4, "nb_jambes_min": 4}
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P2"}, {"id": "P3"}, {"id": "P4"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(problemes, [])
        self.assertIn("coupon", acceptes)

    def test_4_sur_5_conservateurs_refuse_regression_30_09(self):
        # Reproduit exactement le coupon réel envoyé le 30/09/2026 (5 jambes, catégories
        # TOUTES différentes — Total, Handicap Asiatique, Cartons, BTTS, Total Équipe 2 — mais
        # 4/5 en Under/No quand même) : avec l'ancien seuil (math.ceil(5*0.7)=4), 4 n'est
        # jamais > 4, donc AUCUNE règle ne s'appliquait (la règle par-catégorie ne voit rien,
        # chaque catégorie n'apparaît qu'une fois ; la règle Under/No globale passait pile au
        # plafond). Avec floor(5*0.7)=3, 4 > 3 doit refuser.
        pool = {
            "A vs B": [_sel("A vs B", "Total", "Under", 2.3), _sel("A vs B", "Total", "Over", 1.6)],
            "C vs D": [_sel("C vs D", "Handicap Asiatique", "2", 2.3)],
            "E vs F": [_sel("E vs F", "Total Cartons", "Under", 1.46), _sel("E vs F", "Total Cartons", "Over", 2.6)],
            "G vs H": [_sel("G vs H", "BTTS", "No", 1.42), _sel("G vs H", "BTTS", "Yes", 2.7)],
            "I vs J": [_sel("I vs J", "Total Équipe 2", "Under", 2.2), _sel("I vs J", "Total Équipe 2", "Over", 1.6)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 5, "nb_jambes_min": 1}
        # A/Under, C/2 (handicap, pas conservateur), E/Under, G/No, I/Under = 4 conservateurs/5
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P3"}, {"id": "P4"}, {"id": "P6"}, {"id": "P8"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(acceptes, {})
        self.assertTrue(any("Under/No" in p for p in problemes), problemes)


def _sel_ligne(match, categorie, selection, cote, handicap):
    """Comme _sel, mais avec une ligne (handicap) explicite — pour tester la diversité
    direction+ligne au sein d'une même catégorie (ex: Corners Under 9.5 vs Over 8.5)."""
    c = _sel(match, categorie, selection, cote)
    c["pick"]["handicap"] = handicap
    c["pick"]["marche"] = f"{categorie} ({handicap})"
    return c


class TestDiversiteMemeCategorie(unittest.TestCase):
    """Demande explicite du 30/09/2026 : « oblige l'IA à choisir la diversité sur les marchés,
    même marché — si elle choisit un pari corner Under, un autre Over, et un autre but 3.5, un
    autre 2.5 » — généralise TestDiversiteDesMarches (Under/No) à N'IMPORTE QUELLE catégorie
    répétée, en exigeant soit une direction différente, soit une ligne différente."""

    def test_meme_categorie_meme_ligne_refuse_si_alternative_existe(self):
        pool = {
            "A vs B": [_sel_ligne("A vs B", "Total Corners", "Under", 1.5, 9.5)],
            "C vs D": [_sel_ligne("C vs D", "Total Corners", "Under", 1.5, 9.5),
                       _sel_ligne("C vs D", "Total Corners", "Over", 1.5, 9.5)],  # alternative dispo
        }
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2}
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P2"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(acceptes, {})
        self.assertTrue(any("Total Corners" in p and "C vs D" in p for p in problemes), problemes)

    def test_direction_differente_suffit_a_varier(self):
        pool = {
            "A vs B": [_sel_ligne("A vs B", "Total Corners", "Under", 1.5, 9.5)],
            "C vs D": [_sel_ligne("C vs D", "Total Corners", "Over", 1.5, 9.5)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2}
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P2"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(problemes, [])
        self.assertIn("coupon", acceptes)

    def test_ligne_differente_suffit_a_varier(self):
        pool = {
            "A vs B": [_sel_ligne("A vs B", "Total", "Over", 1.5, 2.5)],
            "C vs D": [_sel_ligne("C vs D", "Total", "Over", 1.5, 3.5)],  # même direction, ligne différente
        }
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2}
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P2"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(problemes, [])
        self.assertIn("coupon", acceptes)

    def test_aucune_alternative_nulle_part_accepte(self):
        # Les 2 matchs n'offrent QUE Corners Under 9.5 : impossible de varier, donc pas d'erreur.
        pool = {m: [_sel_ligne(m, "Total Corners", "Under", 1.5, 9.5)] for m in ("A vs B", "C vs D")}
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2}
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P2"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(problemes, [])
        self.assertIn("coupon", acceptes)

    def test_categories_differentes_pas_concernees(self):
        # Total Corners Under et BTTS No : catégories différentes, la règle par-catégorie ne
        # s'applique qu'à l'intérieur d'une MÊME catégorie (couvert par TestDiversiteDesMarches).
        pool = {
            "A vs B": [_sel_ligne("A vs B", "Total Corners", "Under", 1.5, 9.5)],
            "C vs D": [_sel("C vs D", "BTTS", "No", 1.5)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2}
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P2"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        # Peut être refusé par la règle Under/No générale (2/2 conservateurs, pas d'alternative
        # BTTS/Corners dans le catalogue ici) ou accepté — seul importe qu'aucun message ne cite
        # une exigence de variation "Total Corners" par-catégorie (un seul pari de cette
        # catégorie, rien à varier).
        self.assertFalse(any("Total Corners" in p and "varie" in p for p in problemes), problemes)


class TestCategorieDominante(unittest.TestCase):
    """Reproduit exactement le coupon réel envoyé le 30/09/2026 (5 jambes, 3 en "Double Chance"
    — 2X, 2X, 1X) : _categories_peu_variees ne le voit pas (directions différentes = "déjà
    varié" à ses yeux), alors que la CATÉGORIE domine le coupon. _categories_dominantes regarde
    la répétition de la catégorie seule, peu importe la direction retenue à l'intérieur."""

    def _pool_double_chance_dominant(self):
        return {
            "A vs B": [_sel("A vs B", "Double Chance", "2X", 1.33), _sel("A vs B", "Total", "Over", 1.9)],
            "C vs D": [_sel("C vs D", "Double Chance", "2X", 1.37), _sel("C vs D", "BTTS", "Yes", 1.8)],
            "E vs F": [_sel("E vs F", "Double Chance", "1X", 1.79), _sel("E vs F", "Total", "Under", 1.6)],
            "G vs H": [_sel("G vs H", "Handicap Asiatique", "1", 1.62)],
            "I vs J": [_sel("I vs J", "Total Équipe 2", "Under", 1.25)],
        }

    def test_double_chance_dominant_refuse_si_alternative_existe(self):
        pool = self._pool_double_chance_dominant()
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 5, "nb_jambes_min": 1}
        # P1 (A/2X), P3 (C/2X), P5 (E/1X), P7 (G/Handicap), P8 (I/Total Équipe 2) — 3/5 Double Chance
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P3"}, {"id": "P5"}, {"id": "P7"}, {"id": "P8"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(acceptes, {})
        self.assertTrue(any("Double Chance" in p and "dominant" in p for p in problemes), problemes)

    def test_meme_repartition_acceptee_si_aucune_alternative(self):
        # Mêmes 3 Double Chance, mais AUCUNE autre catégorie disponible sur ces 3 matchs :
        # impossible de varier, donc pas d'erreur (seuls G/H et I/J ont une alternative, non
        # concernés par la surreprésentation).
        pool = {
            "A vs B": [_sel("A vs B", "Double Chance", "2X", 1.33)],
            "C vs D": [_sel("C vs D", "Double Chance", "2X", 1.37)],
            "E vs F": [_sel("E vs F", "Double Chance", "1X", 1.79)],
            "G vs H": [_sel("G vs H", "Handicap Asiatique", "1", 1.62)],
            "I vs J": [_sel("I vs J", "Total Équipe 2", "Under", 1.25)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "coupon", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 5, "nb_jambes_min": 1}
        proposition = {"coupons": [{"profil": "coupon", "strategie": "s",
                                    "jambes": [{"id": "P1"}, {"id": "P2"}, {"id": "P3"}, {"id": "P4"}, {"id": "P5"}]}]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])

        self.assertEqual(problemes, [])
        self.assertIn("coupon", acceptes)


class TestDiversiteEtDoublonsEntreProfils(unittest.TestCase):
    """Demande explicite du 30/09/2026 : "ne choisis pas au profil suivant ce que le profil
    précédent a déjà choisi" + diversité de catégorie à l'échelle du run entier, pas profil par
    profil isolément. valider() traite les profils d'une même proposition dans l'ordre et
    verrouille les sélections d'un profil accepté avant de passer au suivant ; selections_
    precedentes permet d'injecter le même historique quand chaque profil vient d'un appel
    valider() séparé (agent pilote, un profil à la fois)."""

    def _pool_six_matchs(self):
        # 6 matchs, une seule catégorie "Total" chacun (P1 Over, P2 Under, P3 Over, P4 Under,
        # P5 Over, P6 Under) : aucune alternative de catégorie nulle part, donc les règles de
        # diversité par catégorie ne se déclenchent jamais ici — isole le test sur la seule
        # règle testée (refus du pari exactement identique entre profils).
        return {
            f"M{i} vs A{i}": [_sel(f"M{i} vs A{i}", "Total", sel, 1.8)]
            for i, sel in enumerate(["Over", "Under", "Over", "Under", "Over", "Under"], start=1)
        }

    def test_meme_pari_exact_refuse_dans_le_profil_suivant(self):
        pool = self._pool_six_matchs()
        catalogue, _ = st.construire_catalogue(pool)
        profils = [{"cle": "p1", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2},
                   {"cle": "p2", "nom": "y", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2}]
        proposition = {"coupons": [
            {"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P2"}]},
            # P1 réutilisé (même match, même marché, même sélection) — doit être refusé.
            {"profil": "p2", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P3"}]},
        ]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, profils)

        self.assertIn("p1", acceptes)
        self.assertNotIn("p2", acceptes)
        self.assertTrue(any("déjà choisi dans un autre profil" in p for p in problemes), problemes)

    def test_meme_match_autre_marche_accepte_dans_le_profil_suivant(self):
        # A vs B propose Total ET BTTS (P1, P2) : réutiliser le MATCH avec un pari DIFFÉRENT
        # (P2 au lieu de P1) dans un autre profil reste autorisé.
        pool = {
            "A vs B": [_sel("A vs B", "Total", "Over", 1.8), _sel("A vs B", "BTTS", "Yes", 1.7)],
            "C vs D": [_sel("C vs D", "Total", "Over", 1.8)],
            "E vs F": [_sel("E vs F", "Total", "Over", 1.8)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        profils = [{"cle": "p1", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 1, "nb_jambes_min": 1},
                   {"cle": "p2", "nom": "y", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 1, "nb_jambes_min": 1}]
        proposition = {"coupons": [
            {"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}]},  # A vs B, Total Over
            {"profil": "p2", "strategie": "s", "jambes": [{"id": "P2"}]},  # A vs B, BTTS Yes — match repris, pari différent
        ]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, profils)

        self.assertEqual(problemes, [])
        self.assertIn("p1", acceptes)
        self.assertIn("p2", acceptes)

    def test_categorie_dominante_a_l_echelle_du_run_entier(self):
        # profil1 : 1 seul pari "Double Chance" (P1) + 1 BTTS (P4) — pas dominant à lui seul
        # (1/2, sous le seuil). profil2 ajoute un 2e Double Chance (P5) sur un autre match :
        # à l'échelle du run, 2 Double Chance sur 3 paris (67%) dépasse le seuil de 40%, mais
        # seulement visible en comptant le profil précédent (deja_presents).
        pool = {
            "A vs B": [_sel("A vs B", "Double Chance", "2X", 1.33), _sel("A vs B", "Total", "Over", 1.9)],
            "C vs D": [_sel("C vs D", "Double Chance", "1X", 1.37), _sel("C vs D", "BTTS", "Yes", 1.8)],
            "E vs F": [_sel("E vs F", "Double Chance", "2X", 1.6), _sel("E vs F", "Total", "Under", 1.5)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        profils = [{"cle": "p1", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2},
                   {"cle": "p2", "nom": "y", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 1, "nb_jambes_min": 1}]
        proposition = {"coupons": [
            {"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P4"}]},  # A/2X, C/BTTS
            {"profil": "p2", "strategie": "s", "jambes": [{"id": "P5"}]},  # E/2X — 2e Double Chance du run
        ]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, profils)

        self.assertIn("p1", acceptes)
        self.assertNotIn("p2", acceptes)
        self.assertTrue(any("Double Chance" in p and "dominant" in p for p in problemes), problemes)

    def test_fonctions_diversite_acceptent_deja_presents_vide_par_defaut(self):
        # Compatibilité : les appels existants sans deja_presents continuent de fonctionner
        # exactement comme avant (aucune régression pour les appelants qui l'ignorent).
        selections = [_sel("A vs B", "Total", "Over", 1.8), _sel("C vs D", "Total", "Over", 1.8)]
        catalogue, _ = st.construire_catalogue({"A vs B": [selections[0]], "C vs D": [selections[1]]})
        self.assertEqual(st._categories_peu_variees(selections, catalogue), [])
        self.assertEqual(st._categories_dominantes(selections, catalogue), [])

    def test_ignorer_diversite_croisee_traite_chaque_profil_comme_le_premier(self):
        # Demande explicite du 01/10/2026 (run ponctuel à 6 profils) : "je veux que tu oublies
        # les profils et leur diversité, travaille comme si c'était le premier profil" — même
        # scénario que test_categorie_dominante_a_l_echelle_du_run_entier (2e Double Chance
        # rejeté à l'échelle du run), mais ignorer_diversite_croisee=True doit l'accepter : la
        # diversité de catégorie n'est plus mesurée au-delà du profil en cours.
        pool = {
            "A vs B": [_sel("A vs B", "Double Chance", "2X", 1.33), _sel("A vs B", "Total", "Over", 1.9)],
            "C vs D": [_sel("C vs D", "Double Chance", "1X", 1.37), _sel("C vs D", "BTTS", "Yes", 1.8)],
            "E vs F": [_sel("E vs F", "Double Chance", "2X", 1.6), _sel("E vs F", "Total", "Under", 1.5)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        profils = [{"cle": "p1", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2},
                   {"cle": "p2", "nom": "y", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 1, "nb_jambes_min": 1}]
        proposition = {"coupons": [
            {"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P4"}]},  # A/2X, C/BTTS
            {"profil": "p2", "strategie": "s", "jambes": [{"id": "P5"}]},  # E/2X — accepté cette fois
        ]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, profils, ignorer_diversite_croisee=True)

        self.assertEqual(problemes, [])
        self.assertIn("p1", acceptes)
        self.assertIn("p2", acceptes)

    def test_ignorer_diversite_croisee_garde_quand_meme_le_refus_du_doublon_exact(self):
        # Le refus du pari EXACTEMENT identique entre profils n'est JAMAIS désactivable, même
        # avec ignorer_diversite_croisee=True (demande explicite : seule la diversité de
        # catégorie doit sauter, pas l'anti-doublon pur et simple).
        pool = self._pool_six_matchs()
        catalogue, _ = st.construire_catalogue(pool)
        profils = [{"cle": "p1", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2},
                   {"cle": "p2", "nom": "y", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2, "nb_jambes_min": 2}]
        proposition = {"coupons": [
            {"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P2"}]},
            {"profil": "p2", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P3"}]},  # P1 réutilisé à l'identique
        ]}

        acceptes, problemes, _ = st.valider(proposition, catalogue, profils, ignorer_diversite_croisee=True)

        self.assertIn("p1", acceptes)
        self.assertNotIn("p2", acceptes)
        self.assertTrue(any("déjà choisi dans un autre profil" in p for p in problemes), problemes)


class TestCoteTotaleMinimale(unittest.TestCase):
    """Demande explicite du 01/10/2026 : "interdit les cote total moins de 5" — plancher
    ABSOLU (st.COTE_TOTALE_MIN), quel que soit le profil (cote_min/cote_max du profil restent
    purement indicatifs par ailleurs, voir TestDiversiteEtDoublonsEntreProfils). Pas de
    plafond haut en contrepartie."""

    def test_cote_sous_le_plancher_rejetee(self):
        pool = {"A vs B": [_sel("A vs B", "Total", "Over", 1.5)]}
        catalogue, _ = st.construire_catalogue(pool)
        profil = {"cle": "p1", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 1, "nb_jambes_min": 1}
        with mock.patch.object(st, "COTE_TOTALE_MIN", 5.0):
            proposition = {"coupons": [{"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}]}]}
            acceptes, problemes, calculs = st.valider(proposition, catalogue, [profil])
        self.assertNotIn("p1", acceptes)
        self.assertTrue(any("trop basse (minimum 5" in p for p in problemes), problemes)
        self.assertTrue(any("cote totale 1.50" in c for c in calculs), calculs)

    def test_plancher_diversifie_par_profil_via_cote_totale_min(self):
        # Demande explicite du 02/10/2026 : le plancher PAR DÉFAUT (st.COTE_TOTALE_MIN) peut
        # être relevé pour UN profil précis via profil["cote_totale_min"], sans toucher aux
        # autres — constaté sur le run #84, les 4 coupons sûrs tombaient tous entre 5.0 et 5.25
        # au même plancher unique de 5 ; un plancher plus haut sur certains force l'IA à
        # accepter des cotes individuelles plus hautes pour l'atteindre, et donc à diversifier.
        pool = {
            "A vs B": [_sel("A vs B", "Total", "Over", 3.0)],
            "C vs D": [_sel("C vs D", "Total", "Over", 2.0)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        # cote totale réelle 3.0*2.0 = 6.0 : sous le plancher DU PROFIL (8.0) bien qu'au-dessus
        # du plancher par défaut (5.0, qui ne s'applique plus puisque le profil précise le sien).
        profil = {"cle": "p1", "nom": "x", "cote_min": 0.0, "cote_max": 1000.0, "nb_jambes": 2,
                  "nb_jambes_min": 2, "cote_totale_min": 8.0}
        with mock.patch.object(st, "COTE_TOTALE_MIN", 5.0):
            proposition = {"coupons": [{"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P2"}]}]}
            acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])
        self.assertNotIn("p1", acceptes)
        self.assertTrue(any("trop basse (minimum 8 pour ce profil)" in p for p in problemes), problemes)

    def test_cote_au_dessus_du_plancher_acceptee_sans_plafond_haut(self):
        pool = {
            "A vs B": [_sel("A vs B", "Total", "Over", 3.0)],
            "C vs D": [_sel("C vs D", "Total", "Over", 2.0)],
        }
        catalogue, _ = st.construire_catalogue(pool)
        # cote totale 3.0*2.0 = 6.0 : au-dessus du plancher, acceptée même si cote_max du
        # profil (4.0) est largement dépassée — aucun plafond haut n'est vérifié.
        profil = {"cle": "p1", "nom": "x", "cote_min": 0.0, "cote_max": 4.0, "nb_jambes": 2, "nb_jambes_min": 2}
        with mock.patch.object(st, "COTE_TOTALE_MIN", 5.0):
            proposition = {"coupons": [{"profil": "p1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P2"}]}]}
            acceptes, problemes, _ = st.valider(proposition, catalogue, [profil])
        self.assertEqual(problemes, [])
        self.assertIn("p1", acceptes)


class TestCoupEnvoi(unittest.TestCase):
    def test_match_deja_commence_ecarte_a_la_reprise(self):
        # Demande explicite du 03/10/2026 ("retire cet 45 min") : seul un match DÉJÀ commencé
        # est encore écarté ici — un match qui démarre bientôt (même dans 1 minute) reste
        # valable, "Pre-Game"/"hasOdds" (verifier_fraicheur_matchs) suffisent à écarter un
        # match réellement plus pariable.
        from datetime import datetime, timezone
        maintenant = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
        self.assertFalse(ae.coup_envoi_assez_loin("2026-09-26T12:00:00Z", maintenant))  # déjà commencé
        self.assertTrue(ae.coup_envoi_assez_loin("2026-09-26T13:01:00Z", maintenant))  # dans 1 min
        self.assertTrue(ae.coup_envoi_assez_loin("2026-09-26T13:30:00Z", maintenant))
        self.assertTrue(ae.coup_envoi_assez_loin("2026-09-26T18:45:00Z", maintenant))
        self.assertTrue(ae.coup_envoi_assez_loin(None, maintenant))


if __name__ == "__main__":
    unittest.main()
