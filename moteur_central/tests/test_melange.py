"""Tests de moteur_central/melange.py — aucun appel réseau. Le test le plus important
(non-régression) compare combiner_proba() à la vraie sortie de
bet_agent/analyser_et_envoyer.py:evaluer_marches_toutes() (le moteur de référence, jamais
modifié) sur les 40 cas synthétiques de bet_agent/cas_synthetiques_demo.py, à POIDS_MARCHE=0.65
(valeur réelle de production, inchangée)."""

import os
import sys

import pytest

from moteur_central.melange import combiner_proba

_RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BET_AGENT = os.path.join(_RACINE, "bet_agent")
if _BET_AGENT not in sys.path:
    sys.path.insert(0, _BET_AGENT)

import analyser_et_envoyer as ae  # noqa: E402 — après l'ajustement de sys.path ci-dessus
from cas_synthetiques_demo import CAS_SYNTHETIQUES_DEMO  # noqa: E402


class TestCombinerProbaCasLimites:
    def test_poids_0_renvoie_le_modele_pur(self):
        assert combiner_proba(0.7, 0.3, 0.0) == 0.7

    def test_poids_1_renvoie_le_marche_pur(self):
        assert combiner_proba(0.7, 0.3, 1.0) == 0.3

    def test_poids_0_65_formule_exacte(self):
        p_modele, p_marche, poids = 0.6, 0.5, 0.65
        attendu = (1 - poids) * p_modele + poids * p_marche
        assert combiner_proba(p_modele, p_marche, poids) == attendu

    def test_p_modele_none_leve_value_error_jamais_devine(self):
        with pytest.raises(ValueError):
            combiner_proba(None, 0.5, 0.65)

    def test_p_marche_none_leve_value_error_jamais_devine(self):
        with pytest.raises(ValueError):
            combiner_proba(0.5, None, 0.65)

    def test_p_marche_superieur_a_1_jamais_plafonne(self):
        # Double Chance : p_marche peut légitimement dépasser 1.0 (voir
        # analyser_et_envoyer.probabilites_sans_marge, somme_cible=2.0) — le mélange ne doit
        # JAMAIS plafonner ce résultat, la référence ne le fait pas non plus.
        resultat = combiner_proba(0.5, 1.2, 1.0)
        assert resultat == 1.2

    def test_valeurs_limites_0_et_1(self):
        assert combiner_proba(0.0, 1.0, 0.5) == 0.5
        assert combiner_proba(1.0, 0.0, 0.5) == 0.5
        assert combiner_proba(0.0, 0.0, 0.65) == 0.0
        assert combiner_proba(1.0, 1.0, 0.65) == 1.0

    def test_poids_hors_0_1_jamais_valide_ni_clampe(self):
        # La référence (POIDS_MARCHE, constante module-level) n'est jamais hors [0,1] en
        # production, mais cette fonction pure ne doit ajouter aucune validation absente de
        # la référence — un poids hors intervalle est simplement appliqué tel quel.
        assert combiner_proba(0.5, 0.5, 2.0) == 0.5  # (1-2)*0.5 + 2*0.5 = -0.5+1.0 = 0.5
        assert combiner_proba(1.0, 0.0, -1.0) == 2.0  # (1-(-1))*1.0 + (-1)*0.0 = 2.0


def _evaluer_marches_toutes_via_combiner_proba(marches, mu_home, mu_away, poids_marche):
    """Même pipeline que ae.evaluer_marches_toutes, SAUF l'étape de mélange qui appelle
    combiner_proba() au lieu d'inliner la formule — pour prouver que l'extraction est fidèle."""
    marche_sans_marge = ae.probabilites_sans_marge(marches)
    retenus = []
    for c in ae._evaluer_marches_brut(marches, mu_home, mu_away):
        if c["categorie"] in ae.CATEGORIES_EXCLUES or c["cote"] < ae.COTE_MIN_JAMBE:
            continue
        p_marche = marche_sans_marge.get((c["marche"], c["selection"]))
        if p_marche is None:
            continue
        p_modele = c["proba_modele_pct"] / 100
        p = combiner_proba(p_modele, p_marche, poids_marche)
        edge = ae.calc_edge(p, c["cote"])
        c.update(proba_modele_pct=round(p * 100, 1), edge_pct=round(edge, 1) if edge is not None else None,
                 proba_poisson_pct=round(p_modele * 100, 1), proba_marche_pct=round(p_marche * 100, 1))
        retenus.append(c)
    return sorted(retenus, key=lambda c: (c["edge_pct"] if c["edge_pct"] is not None else -999), reverse=True)


class TestNonRegressionVersLaReference:
    def test_combiner_proba_reproduit_evaluer_marches_toutes_sur_les_40_cas(self):
        assert ae.POIDS_MARCHE == 0.65, "la référence a changé — ce test compare à une valeur obsolète"
        total_candidats = 0
        for marches, _resultat in CAS_SYNTHETIQUES_DEMO:
            mu_home, mu_away, _, _, _ = ae.estimer_expected_goals_depuis_marches(marches)
            reel = ae.evaluer_marches_toutes(marches, mu_home, mu_away)
            via_combiner = _evaluer_marches_toutes_via_combiner_proba(marches, mu_home, mu_away, ae.POIDS_MARCHE)
            cles_reel = sorted((c["marche"], c["selection"], c["proba_modele_pct"], c["edge_pct"]) for c in reel)
            cles_via = sorted((c["marche"], c["selection"], c["proba_modele_pct"], c["edge_pct"])
                              for c in via_combiner)
            assert cles_reel == cles_via
            total_candidats += len(reel)
        assert total_candidats > 0  # vérifie qu'on a bien comparé quelque chose, pas 40 cas vides
