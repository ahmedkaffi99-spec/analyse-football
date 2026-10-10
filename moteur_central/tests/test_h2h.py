"""Tests de moteur_central/h2h.py — aucun appel réseau. Comparaison directe et systématique
avec la vraie bet_agent/analyser_et_envoyer.py:_ponderer_avec_h2h (jamais modifiée) sur une
grille étendue de confrontations et de données manquantes."""

import os
import sys

from moteur_central.h2h import poids_h2h, ponderer_h2h

_RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BET_AGENT = os.path.join(_RACINE, "bet_agent")
if _BET_AGENT not in sys.path:
    sys.path.insert(0, _BET_AGENT)

import analyser_et_envoyer as ae  # noqa: E402


class TestPoidsH2hSeul:
    def test_proportionnel_sous_le_seuil(self):
        assert poids_h2h(2) == 2 / 5 * 0.4

    def test_plafonne_au_dela_du_seuil(self):
        assert poids_h2h(50) == 0.4
        assert poids_h2h(6) == 0.4
        assert poids_h2h(5) == 0.4

    def test_un_seul_match(self):
        assert poids_h2h(1) == 1 / 5 * 0.4


class TestReproduitLaReferenceCasExistants:
    """Les 4 cas de bet_agent/test_correctifs.py::TestPondererAvecH2h, comparés directement
    à ae._ponderer_avec_h2h (pas seulement recalculés à la main)."""

    def test_h2h_tire_le_xg_vers_la_domination_historique(self):
        h2h = {"matchs_analyses": 2, "buts_home_moyenne": 3.0, "buts_away_moyenne": 0.5}
        assert ponderer_h2h(1.5, 1.55, h2h) == ae._ponderer_avec_h2h(1.5, 1.55, h2h)

    def test_h2h_absent_ne_change_rien(self):
        assert ponderer_h2h(1.5, 1.55, None) == ae._ponderer_avec_h2h(1.5, 1.55, None) == (1.5, 1.55)
        h2h_vide = {"matchs_analyses": 0}
        assert ponderer_h2h(1.5, 1.55, h2h_vide) == ae._ponderer_avec_h2h(1.5, 1.55, h2h_vide) == (1.5, 1.55)
        h2h = {"matchs_analyses": 2, "buts_home_moyenne": 3.0, "buts_away_moyenne": 0.5}
        assert ponderer_h2h(None, 1.55, h2h) == ae._ponderer_avec_h2h(None, 1.55, h2h) == (None, 1.55)

    def test_poids_plafonne_a_h2h_poids_max_meme_avec_beaucoup_de_confrontations(self):
        h2h = {"matchs_analyses": 50, "buts_home_moyenne": 5.0, "buts_away_moyenne": 0.0}
        assert ponderer_h2h(1.0, 1.0, h2h) == ae._ponderer_avec_h2h(1.0, 1.0, h2h)


class TestGrilleEtendueContreLaReference:
    """Grille systématique : nb de confrontations x champs manquants x valeurs de xG limites —
    chaque combinaison comparée DIRECTEMENT à la vraie _ponderer_avec_h2h. Si un écart existe,
    ce test échoue (pas de logique silencieusement différente)."""

    NB_CONFRONTATIONS = (0, 1, 2, 3, 4, 5, 6, 10, 50)
    XG_PAIRES = ((1.5, 1.55), (0.0, 0.0), (10.0, 0.01), (0.15, 0.15), (5.0, 5.0))

    def _h2h_complet(self, nb, buts_home=2.0, buts_away=1.0):
        return {"matchs_analyses": nb, "buts_home_moyenne": buts_home, "buts_away_moyenne": buts_away}

    def test_grille_nb_confrontations_x_paires_xg(self):
        for nb in self.NB_CONFRONTATIONS:
            h2h = self._h2h_complet(nb)
            for xg_home, xg_away in self.XG_PAIRES:
                attendu = ae._ponderer_avec_h2h(xg_home, xg_away, h2h)
                obtenu = ponderer_h2h(xg_home, xg_away, h2h)
                assert obtenu == attendu, f"nb={nb} xg=({xg_home},{xg_away}) : {obtenu} != {attendu}"

    def test_champ_matchs_analyses_manquant(self):
        h2h = {"buts_home_moyenne": 2.0, "buts_away_moyenne": 1.0}
        assert ponderer_h2h(1.5, 1.55, h2h) == ae._ponderer_avec_h2h(1.5, 1.55, h2h) == (1.5, 1.55)

    def test_champ_buts_home_moyenne_manquant(self):
        h2h = {"matchs_analyses": 3, "buts_away_moyenne": 1.0}
        assert ponderer_h2h(1.5, 1.55, h2h) == ae._ponderer_avec_h2h(1.5, 1.55, h2h) == (1.5, 1.55)

    def test_champ_buts_away_moyenne_manquant(self):
        h2h = {"matchs_analyses": 3, "buts_home_moyenne": 2.0}
        assert ponderer_h2h(1.5, 1.55, h2h) == ae._ponderer_avec_h2h(1.5, 1.55, h2h) == (1.5, 1.55)

    def test_xg_home_none(self):
        h2h = self._h2h_complet(3)
        assert ponderer_h2h(None, 1.55, h2h) == ae._ponderer_avec_h2h(None, 1.55, h2h) == (None, 1.55)

    def test_xg_away_none(self):
        h2h = self._h2h_complet(3)
        assert ponderer_h2h(1.5, None, h2h) == ae._ponderer_avec_h2h(1.5, None, h2h) == (1.5, None)

    def test_xg_nul_des_les_deux_cotes(self):
        h2h = self._h2h_complet(5, buts_home=0.0, buts_away=0.0)
        assert ponderer_h2h(0.0, 0.0, h2h) == ae._ponderer_avec_h2h(0.0, 0.0, h2h)

    def test_xg_tres_eleve(self):
        h2h = self._h2h_complet(5, buts_home=20.0, buts_away=15.0)
        assert ponderer_h2h(50.0, 40.0, h2h) == ae._ponderer_avec_h2h(50.0, 40.0, h2h)

    def test_h2h_vide_dict(self):
        assert ponderer_h2h(1.5, 1.55, {}) == ae._ponderer_avec_h2h(1.5, 1.55, {}) == (1.5, 1.55)


class TestPlancherEtArrondi:
    def test_plancher_0_15_applique_quand_resultat_descendrait_sous_ce_seuil(self):
        # Les deux xG réels et le H2H sont proches de 0 -> le mélange doit être tiré vers 0.15,
        # jamais plus bas, exactement comme la référence.
        h2h = {"matchs_analyses": 5, "buts_home_moyenne": 0.0, "buts_away_moyenne": 0.0}
        attendu = ae._ponderer_avec_h2h(0.05, 0.05, h2h)
        obtenu = ponderer_h2h(0.05, 0.05, h2h)
        assert obtenu == attendu == (0.15, 0.15)

    def test_arrondi_a_deux_decimales(self):
        h2h = {"matchs_analyses": 3, "buts_home_moyenne": 2.333333, "buts_away_moyenne": 1.111111}
        attendu = ae._ponderer_avec_h2h(1.456789, 1.654321, h2h)
        obtenu = ponderer_h2h(1.456789, 1.654321, h2h)
        assert obtenu == attendu
        # Les deux valeurs ont bien au plus 2 décimales (reproduit round(..., 2)).
        assert obtenu[0] == round(obtenu[0], 2)
        assert obtenu[1] == round(obtenu[1], 2)
