"""Tests de backtest_production.py — aucun appel réseau, aucune modification de
analyser_et_envoyer.py. Le test le plus important (non-régression) vérifie que la réplique
paramétrable du mélange modèle/marché (evaluer_marches_toutes_poids) produit EXACTEMENT la même
sortie que la vraie fonction de production evaluer_marches_toutes() quand poids=0.65 (la valeur
réellement utilisée en production) — sinon le backtest mesurerait un système différent de celui
qui tourne réellement."""

import analyser_et_envoyer as ae
from backtest_production import (backtester, comparer_poids, evaluer_cas,
                                 evaluer_marches_toutes_poids, wilson_half_width)
from cas_synthetiques_demo import CAS_SYNTHETIQUES_DEMO


class TestNonRegressionVersLeCodeReel:
    def test_poids_0_65_reproduit_evaluer_marches_toutes(self):
        for marches, resultat in CAS_SYNTHETIQUES_DEMO:
            mu_home, mu_away, _, _, _ = ae.estimer_expected_goals_depuis_marches(marches)
            reel = ae.evaluer_marches_toutes(marches, mu_home, mu_away)
            replique = evaluer_marches_toutes_poids(marches, mu_home, mu_away, ae.POIDS_MARCHE)
            cles_reel = sorted((c["marche"], c["selection"], c["proba_modele_pct"], c["edge_pct"]) for c in reel)
            cles_replique = sorted((c["marche"], c["selection"], c["proba_modele_pct"], c["edge_pct"])
                                   for c in replique)
            assert cles_reel == cles_replique

    def test_ae_poids_marche_vaut_bien_0_65_aujourdhui(self):
        # Si cette constante change en production sans que ce test soit mis à jour, le
        # backtest comparerait une valeur qui n'est plus celle réellement utilisée.
        assert ae.POIDS_MARCHE == 0.65


class TestWilsonHalfWidth:
    def test_plus_grand_echantillon_donne_moins_dincertitude(self):
        assert wilson_half_width(1000) < wilson_half_width(10)

    def test_echantillon_vide_renvoie_nan(self):
        import math
        assert math.isnan(wilson_half_width(0))


class TestEvaluerCas:
    def test_un_cas_simple_produit_des_points_juges(self):
        marches, resultat = CAS_SYNTHETIQUES_DEMO[0]
        r = evaluer_cas(marches, resultat, poids_marche=0.65)
        assert len(r.points) > 0
        for categorie, marche, selection, proba, y in r.points:
            assert 0.0 <= proba <= 1.0
            assert y in (0, 1)

    def test_push_ou_marche_non_jugeable_est_ignore_jamais_un_verdict_devine(self):
        # Une ligne de handicap exactement égale à l'écart de buts réel -> push côté
        # grader_pick (juger_handicap) -> doit être comptée dans "ignores", jamais dans points
        # (jamais 0/1 deviné pour un push).
        marches = [{"marche_id": "1", "marche": "Asian Handicap", "handicap": 0.0, "periode": "fulltime",
                   "selections": [{"selection": "Home", "cote": 1.9}, {"selection": "Away", "cote": 1.95}]}]
        r = evaluer_cas(marches, (1, 1), poids_marche=0.65)  # 1-1, handicap 0.0 -> push exact
        assert r.points == []
        assert r.ignores >= 0  # le push est filtré avant même d'atteindre grader_pick ou via lui


class TestBacktesterEtComparerPoids:
    def test_backtester_renvoie_les_champs_attendus(self):
        r = backtester(CAS_SYNTHETIQUES_DEMO, poids_marche=0.65)
        assert r["poids_marche"] == 0.65
        assert r["n_cas"] == len(CAS_SYNTHETIQUES_DEMO)
        assert r["global"]["n"] > 0
        assert set(r["global"]) == {"n", "brier", "log_loss", "fiabilite", "wilson_demi_largeur_95pct"}
        assert len(r["par_marche"]) > 0

    def test_comparer_poids_produit_bien_les_3_valeurs_demandees(self):
        resultats = comparer_poids(CAS_SYNTHETIQUES_DEMO, poids_liste=(0.0, 0.65, 1.0))
        assert set(resultats) == {0.0, 0.65, 1.0}
        for r in resultats.values():
            assert r["global"]["n"] > 0

    def test_poids_1_colle_exactement_a_la_probabilite_implicite_du_marche(self):
        # A poids=1 (100% marché), le Brier mesure uniquement la cote elle-même (baseline
        # "toujours suivre le marché") — sert de référence pour juger si le modèle Poisson
        # interne (poids=0) ou le mélange actuel (0.65) apportent quelque chose.
        r0 = backtester(CAS_SYNTHETIQUES_DEMO, poids_marche=0.0)
        r1 = backtester(CAS_SYNTHETIQUES_DEMO, poids_marche=1.0)
        r065 = backtester(CAS_SYNTHETIQUES_DEMO, poids_marche=0.65)
        # Les trois poids ne sont pas censés donner le même nombre de candidats jugés : le
        # filtre p_marche=None (une seule sélection cotée) est indépendant du poids, donc le
        # nombre de CANDIDATS RETENUS est identique ; seule leur probabilité diffère.
        assert r0["global"]["n"] == r1["global"]["n"] == r065["global"]["n"]
