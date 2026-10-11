"""Pondération H2H (confrontations directes) — extraite tel quel (même formule, mêmes gardes,
aucune sémantique nouvelle) de bet_agent/analyser_et_envoyer.py:_ponderer_avec_h2h (lignes
401-416), qui reste le moteur de référence INCHANGÉ. Phase B, lot H2H — demande explicite du
10/10/2026.

Fidélité vérifiée par comparaison directe avec la vraie _ponderer_avec_h2h sur une grille
étendue de confrontations/données manquantes (voir tests/test_h2h.py).

Cette fonction ne fait AUCUN contrôle temporel : elle reçoit un dict h2h déjà agrégé
(matchs_analyses, buts_home_moyenne, buts_away_moyenne) et ne sait pas quelles confrontations
précises le composent. La seule protection contre une fuite (une confrontation future déjà
programmée) se situe en amont, à la COLLECTE (collecte_donnees.py:recuperer_head_to_head) —
jamais ici. Ne pas supposer que cette fonction protège contre une fuite temporelle."""


def poids_h2h(nb, poids_max=0.4, nb_poids_plein=5):
    """min(nb, nb_poids_plein) / nb_poids_plein * poids_max — IDENTIQUE à
    analyser_et_envoyer.py:410, isolée pour être testable seule. nb est supposé positif (la
    référence ne l'appelle jamais avec nb<=0 — voir le garde `if not nb` dans
    ponderer_h2h/_ponderer_avec_h2h, qui court-circuite avant d'atteindre ce calcul)."""
    return min(nb, nb_poids_plein) / nb_poids_plein * poids_max


def ponderer_h2h(xg_home, xg_away, h2h, poids_max=0.4, nb_poids_plein=5):
    """Reproduit _ponderer_avec_h2h à l'identique :
    - h2h absent/falsy (None, {}), xg_home/xg_away = None, matchs_analyses absent/0, ou
      buts_home_moyenne/buts_away_moyenne = None -> renvoie (xg_home, xg_away) INCHANGÉS,
      jamais une valeur devinée.
    - Sinon : poids proportionnel plafonné à poids_max (jamais dominant), mélange linéaire,
      PLANCHER à 0.15 (jamais un xG nul/négatif), ARRONDI à 2 décimales — les deux comme la
      référence, jamais retirés par souci de "fonction pure sans effet de bord"."""
    if not h2h or xg_home is None or xg_away is None:
        return xg_home, xg_away
    nb = h2h.get("matchs_analyses")
    buts_home_h2h = h2h.get("buts_home_moyenne")
    buts_away_h2h = h2h.get("buts_away_moyenne")
    if not nb or buts_home_h2h is None or buts_away_h2h is None:
        return xg_home, xg_away
    poids = poids_h2h(nb, poids_max, nb_poids_plein)
    xg_home_ajuste = (1 - poids) * xg_home + poids * float(buts_home_h2h)
    xg_away_ajuste = (1 - poids) * xg_away + poids * float(buts_away_h2h)
    return round(max(0.15, xg_home_ajuste), 2), round(max(0.15, xg_away_ajuste), 2)
