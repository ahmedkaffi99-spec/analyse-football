"""Calculs des marchés hors buts (corners, tirs, fautes) : troncature des sommes et surdispersion
(audit du 21/10/2026)."""

import analyser_et_envoyer as ae


class TestTroncatureDesSommes:
    def test_over_a_la_moyenne_reste_proche_de_la_moitie_pour_les_grands_comptages(self):
        # Avant le correctif : P(Over 25.5 | mu=26) = 0.0 (somme figée à 25) -> « Under » à 100 %.
        for mu in (22, 26, 30):
            assert 0.4 < ae.proba_over(mu - 0.5, mu) < 0.6

    def test_under_sur_une_ligne_haute_n_est_plus_gonfle(self):
        assert ae.proba_over(21.5, 22) > 0.45

    def test_buts_inchanges(self):
        assert abs(ae.proba_over(2.5, 2.7) - 0.5063) < 0.002

    def test_handicap_sur_grands_comptages_est_coherent(self):
        # deux équipes identiques -> handicap 0.5 pour l'une ~ moitié moins la moitié du nul
        p = ae.proba_handicap_couvert(12, 12, 0.5)
        assert 0.5 < p < 0.6
        assert abs(ae.proba_handicap_couvert(12, 12, -0.5) + p - 1) < 0.01

    def test_impair_borne_dans_0_1(self):
        assert 0.45 < ae.proba_total_impair(24) < 0.55


class TestSurdispersion:
    def test_pmf_somme_a_un_et_moyenne_conservee(self):
        probas = [ae._pmf(24, k, 1.34) for k in range(200)]
        assert abs(sum(probas) - 1) < 1e-6
        assert abs(sum(k * p for k, p in enumerate(probas)) - 24) < 0.01

    def test_dispersion_un_equivaut_a_poisson(self):
        assert ae._pmf(5, 3, 1.0) == ae.poisson_p(5, 3)

    def test_queues_plus_epaisses_avec_surdispersion(self):
        # ligne haute : Over plus probable en binomiale négative qu'en Poisson
        assert ae.proba_over(34.5, 26, dispersion=1.34) > ae.proba_over(34.5, 26)
        # ligne basse : Under plus probable aussi
        assert 1 - ae.proba_over(16.5, 26, dispersion=1.34) > 1 - ae.proba_over(16.5, 26)

    def test_categories_mesurees(self):
        assert ae.DISPERSION_PAR_CATEGORIE["Total Tirs"] > ae.DISPERSION_PAR_CATEGORIE["Total Tirs Cadrés"] > 1
        assert "Total" not in ae.DISPERSION_PAR_CATEGORIE and "Total Cartons" not in ae.DISPERSION_PAR_CATEGORIE
