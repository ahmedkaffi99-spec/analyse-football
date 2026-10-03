"""Tests hors-ligne de verifier_resultats.py (aucun appel réseau) :
python -m unittest test_verifier_resultats"""
import unittest
from unittest import mock

import collecte_donnees as cd
import verifier_resultats as vr


def _fixture_af(home, away, statut_court, but_home=None, but_away=None, elapsed=None):
    return {
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "fixture": {"status": {"short": statut_court, "elapsed": elapsed}},
        "goals": {"home": but_home, "away": but_away},
    }


def _bloc_stats(nom_equipe, **stats):
    """stats : clés = noms EXACTS API-Football ("Corner Kicks", "Yellow Cards"...) passés en
    kwargs avec des underscores (Python ne permet pas d'espace dans un nom de kwarg) —
    reconvertis ici."""
    return {"team": {"name": nom_equipe},
            "statistics": [{"type": k.replace("_", " "), "value": v} for k, v in stats.items()]}


class TestTrouverEtatLiveApiFootball(unittest.TestCase):
    """Demande explicite de l'utilisateur (01/10/2026), en plein match réel suivi
    manuellement : "on trouve pas un endpoint sur api football en match live" — API-Football
    expose bien le score ET le statut en direct via /fixtures (même endpoint déjà utilisé pour
    le repli de vérification finale, trouver_score_api_football), inutile d'appeler un autre
    endpoint : seul le filtre de statut change (en cours, pas terminé)."""

    def test_match_en_cours_renvoie_score_minute_et_statut(self):
        fixtures = [_fixture_af("Azerbaijan", "Liechtenstein", "2H", 0, 0, 64)]
        etat = vr.trouver_etat_live_api_football("Azerbaijan", "Liechtenstein", fixtures, cd)
        self.assertEqual(etat, (0, 0, 64, "2H"))

    def test_mi_temps_sans_minute_reste_en_direct(self):
        fixtures = [_fixture_af("Azerbaijan", "Liechtenstein", "HT", 1, 0, None)]
        etat = vr.trouver_etat_live_api_football("Azerbaijan", "Liechtenstein", fixtures, cd)
        self.assertEqual(etat, (1, 0, None, "HT"))

    def test_match_pas_commence_renvoie_none(self):
        fixtures = [_fixture_af("Azerbaijan", "Liechtenstein", "NS")]
        self.assertIsNone(vr.trouver_etat_live_api_football("Azerbaijan", "Liechtenstein", fixtures, cd))

    def test_match_termine_renvoie_none(self):
        # Un match FINI n'est PAS "en direct" — c'est trouver_score_api_football qui le gère
        # (résultat final, persisté), pas cette fonction (informatif, jamais persisté).
        fixtures = [_fixture_af("Azerbaijan", "Liechtenstein", "FT", 3, 0)]
        self.assertIsNone(vr.trouver_etat_live_api_football("Azerbaijan", "Liechtenstein", fixtures, cd))

    def test_aucune_correspondance_fiable_renvoie_none(self):
        fixtures = [_fixture_af("Brazil", "Argentina", "2H", 1, 1, 70)]
        self.assertIsNone(vr.trouver_etat_live_api_football("Azerbaijan", "Liechtenstein", fixtures, cd))

    def test_score_manquant_renvoie_none(self):
        fixtures = [_fixture_af("Azerbaijan", "Liechtenstein", "2H", None, None, 64)]
        self.assertIsNone(vr.trouver_etat_live_api_football("Azerbaijan", "Liechtenstein", fixtures, cd))


class TestStatistiquesFinalesApiFootball(unittest.TestCase):
    """Correctif du 03/10/2026 : OddsPapi /v4/scores ne renvoie que les buts — 442 jambes sur
    809 (55% de la base) étaient "non_verifiable" pour cette seule raison (corners, cartons,
    fautes, tirs, hors-jeux, jamais jugés). API-Football expose ces statistiques finales via
    /fixtures/statistics (même endpoint que les stats PRÉ-match, recuperer_stats_10_derniers_
    matchs) — réutilisé ici pour juger ces marchés au lieu de les abandonner."""

    def test_separe_les_stats_domicile_exterieur_par_nom_d_equipe(self):
        blocs = [_bloc_stats("Real Madrid", Corner_Kicks=7), _bloc_stats("Barcelona", Corner_Kicks=4)]
        with mock.patch.object(cd, "_appel_statistiques_fixture", return_value=blocs):
            bloc_dom, bloc_ext = vr.recuperer_statistiques_finales_api_football(123, "Barcelona")
        self.assertEqual(cd._valeur_stat(bloc_dom, "Corner Kicks"), 4.0)
        self.assertEqual(cd._valeur_stat(bloc_ext, "Corner Kicks"), 7.0)

    def test_erreur_api_football_renvoie_none(self):
        with mock.patch.object(cd, "_appel_statistiques_fixture", side_effect=ValueError("quota")):
            self.assertIsNone(vr.recuperer_statistiques_finales_api_football(123, "Barcelona"))

    def test_nombre_de_blocs_inattendu_renvoie_none(self):
        with mock.patch.object(cd, "_appel_statistiques_fixture", return_value=[_bloc_stats("Solo")]):
            self.assertIsNone(vr.recuperer_statistiques_finales_api_football(123, "Solo"))


class TestGraderPickStat(unittest.TestCase):
    """grader_pick_stat : mêmes règles que grader_pick (juger_total/juger_handicap), mais sur
    une statistique de fin de match au lieu des buts."""

    def test_total_cartons_combine_les_deux_equipes(self):
        self.assertEqual(vr.grader_pick_stat("Total Cartons", 4.5, "Under", 2, 2), "gagne")  # 4 < 4.5
        self.assertEqual(vr.grader_pick_stat("Total Cartons", 4.5, "Under", 3, 2), "perdu")  # 5 > 4.5

    def test_total_cartons_equipe_1_ne_prend_que_le_domicile(self):
        self.assertEqual(vr.grader_pick_stat("Total Cartons Équipe 1", 2.0, "Over", 3, 5), "gagne")
        self.assertEqual(vr.grader_pick_stat("Total Cartons Équipe 1", 2.0, "Over", 1, 5), "perdu")

    def test_total_cartons_equipe_2_ne_prend_que_l_exterieur(self):
        self.assertEqual(vr.grader_pick_stat("Total Cartons Équipe 2", 2.0, "Over", 5, 3), "gagne")
        self.assertEqual(vr.grader_pick_stat("Total Cartons Équipe 2", 2.0, "Over", 5, 1), "perdu")

    def test_handicap_corners_reutilise_juger_handicap(self):
        # Domicile +2 corners fictifs : 5 réels + 2 = 7 > 6 (extérieur) -> gagné.
        self.assertEqual(vr.grader_pick_stat("Handicap Corners", 2.0, "1", 5, 6), "gagne")
        self.assertEqual(vr.grader_pick_stat("Handicap Corners", 1.0, "1", 5, 6), "push")
        self.assertEqual(vr.grader_pick_stat("Handicap Corners", 0.0, "1", 5, 6), "perdu")

    def test_statistique_indisponible_renvoie_none(self):
        self.assertIsNone(vr.grader_pick_stat("Total Cartons", 4.5, "Under", None, 2))
        self.assertIsNone(vr.grader_pick_stat("Total Cartons", 4.5, "Under", 2, None))


if __name__ == "__main__":
    unittest.main()
