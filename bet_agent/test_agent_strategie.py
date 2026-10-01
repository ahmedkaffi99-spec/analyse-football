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
        # Depuis le 30/09/2026 : cotes brutes uniquement, aucune probabilité/edge affichée à
        # l'IA (demande explicite "ne calcule pas les odds pour l'IA").
        self.assertNotIn("probabilité", texte)
        self.assertNotIn("edge", texte)

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
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P99"}]},        # id inventé
            {"profil": "profil2", "strategie": "s", "jambes": [{"id": "P1"}, {"id": "P2"}]},         # cote 2.88 < 4
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

    def test_selection_12_toujours_refusee_meme_presente_dans_le_catalogue(self):
        # Garde-fou en profondeur (01/10/2026, suite au bug réel du run à 6 profils où "12"
        # avait fuité dans le catalogue via le marché brut) : valider() refuse la sélection
        # "12" même si elle apparaît dans le catalogue par un chemin imprévu — jamais acceptée.
        pool_avec_12 = dict(POOL, **{
            "C vs D": [_sel("C vs D", "Double Chance", "12", 1.25)],
        })
        catalogue, _ = st.construire_catalogue(pool_avec_12)
        cid_12 = next(cid for cid, c in catalogue.items() if c["pick"]["selection"] == "12")
        proposition = {"coupons": [
            {"profil": "profil1", "strategie": "s", "jambes": [{"id": cid_12}, {"id": "P4"}]},
        ]}
        acceptes, problemes, _ = st.valider(proposition, catalogue, PROFILS)
        self.assertNotIn("profil1", acceptes)
        self.assertTrue(any("interdite" in p for p in problemes), problemes)

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


class TestCoupEnvoi(unittest.TestCase):
    def test_match_qui_commence_bientot_ecarte_a_la_reprise(self):
        from datetime import datetime, timezone
        maintenant = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
        self.assertFalse(ae.coup_envoi_assez_loin("2026-09-26T13:30:00Z", maintenant))
        self.assertFalse(ae.coup_envoi_assez_loin("2026-09-26T12:00:00Z", maintenant))
        self.assertTrue(ae.coup_envoi_assez_loin("2026-09-26T18:45:00Z", maintenant))
        self.assertTrue(ae.coup_envoi_assez_loin(None, maintenant))


if __name__ == "__main__":
    unittest.main()
