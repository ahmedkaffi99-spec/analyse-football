"""Tests hors-ligne de verifier_resultats.py (aucun appel réseau) :
python -m unittest test_verifier_resultats"""
import unittest

import collecte_donnees as cd
import verifier_resultats as vr


def _fixture_af(home, away, statut_court, but_home=None, but_away=None, elapsed=None):
    return {
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "fixture": {"status": {"short": statut_court, "elapsed": elapsed}},
        "goals": {"home": but_home, "away": but_away},
    }


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


if __name__ == "__main__":
    unittest.main()
