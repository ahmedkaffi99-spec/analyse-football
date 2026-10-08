"""Métriques de performance RÉELLES par moteur (bet_agent / moteur/) et par marché, à partir de
lignes DÉJÀ JUGÉES (résultat réel connu, capturé par hist_cotes puis jugé par
backend/app/services/capture_historique.juger_cotes_en_attente) — jamais un backtest artificiel
avec des cotes actuelles : seulement ce qui a été réellement vu au moment de la prédiction et
réellement jugé après coup.

Réutilise moteur.calibration (brier/log_loss/tableau_fiabilite) et moteur.modeles.marches.profit
— jamais une deuxième implémentation de ces formules (voir moteur/backtest.py, même logique).

Chaque ligne attendue : {"proba_pct": float, "cote": float|None, "resultat": "gagne"|"perdu"|
"push"|"non_verifiable"|None, "marche": str, "competition": str|None, "jour": date|str|None}."""

from collections import defaultdict

from moteur import calibration as calib
from moteur.modeles import marches

RESULTAT_VERS_ISSUE = {"gagne": "gagne", "perdu": "perdu", "push": "rembourse"}
TRANCHES_EDGE = [(-1.0, 0.0), (0.0, 0.03), (0.03, 0.06), (0.06, 0.10), (0.10, 1.0)]


def _issue(resultat):
    return RESULTAT_VERS_ISSUE.get(resultat)


def _jugees(lignes):
    return [l for l in lignes if l.get("resultat") not in (None, "non_verifiable")]


def calculer_metriques(lignes, n_min=8):
    """n_min : échantillon minimal pour faire confiance aux métriques (demande explicite :
    "aucun indicateur ne doit être utilisé s'il n'a pas suffisamment de données") — sous ce
    seuil, {"disponible": False, ...} plutôt qu'un chiffre trompeur sur un petit échantillon."""
    jugees = _jugees(lignes)
    n = len(jugees)
    if n < n_min:
        return {"disponible": False, "n": n, "n_min": n_min, "raison": f"échantillon insuffisant ({n} < {n_min})"}

    binaires = [l for l in jugees if _issue(l["resultat"]) in ("gagne", "perdu")]
    points = [(l["proba_pct"] / 100, 1 if _issue(l["resultat"]) == "gagne" else 0) for l in binaires]
    avec_cote = [l for l in jugees if l.get("cote")]
    profits = [marches.profit(_issue(l["resultat"]), l["cote"]) for l in avec_cote]
    edges = [(l["proba_pct"] / 100) * l["cote"] - 1 for l in avec_cote]

    return {
        "disponible": True, "n": n, "n_paris": len(avec_cote),
        "win_rate": round(sum(y for _, y in points) / len(points), 4) if points else None,
        "brier": round(calib.brier(points), 4) if points else None,
        "log_loss": round(calib.log_loss(points), 4) if points else None,
        "calibration": calib.tableau_fiabilite(points),
        "edge_moyen": round(sum(edges) / len(edges), 4) if edges else None,
        "roi": round(sum(profits) / len(profits), 4) if profits else None,
        "profit_net": round(sum(profits), 4) if profits else None,
    }


def _tranche_proba(p):
    for bas, haut in calib.TRANCHES:
        if bas <= p < haut:
            return f"{int(bas * 100)}-{min(int(haut * 100), 100)}%"
    return "?"


def _tranche_edge(e):
    for bas, haut in TRANCHES_EDGE:
        if bas <= e < haut:
            return f"{bas:+.0%}/{haut:+.0%}"
    return "?"


def par_groupe(lignes, cle, n_min=8):
    groupes = defaultdict(list)
    for l in lignes:
        groupes[cle(l)].append(l)
    return {str(k): calculer_metriques(v, n_min) for k, v in sorted(groupes.items(), key=lambda kv: str(kv[0]))}


def rapport_complet(lignes, n_min=8):
    """Vue complète : globale + par marché + par championnat + par tranche de probabilité +
    par tranche d'edge + dans le temps (par mois) — chaque sous-groupe a son propre seuil
    n_min, indépendant du volume global."""
    jugees = _jugees(lignes)
    avec_cote = [l for l in jugees if l.get("cote")]
    return {
        "global": calculer_metriques(lignes, n_min),
        "par_marche": par_groupe(jugees, lambda l: l.get("marche") or l.get("categorie") or "inconnu", n_min),
        "par_championnat": par_groupe(jugees, lambda l: l.get("competition") or "inconnue", n_min),
        "par_tranche_proba": par_groupe(jugees, lambda l: _tranche_proba(l["proba_pct"] / 100), n_min),
        "par_tranche_edge": par_groupe(avec_cote, lambda l: _tranche_edge((l["proba_pct"] / 100) * l["cote"] - 1), n_min),
        "dans_le_temps": par_groupe(jugees, lambda l: str(l.get("jour") or "")[:7] or "inconnu", n_min),
    }
