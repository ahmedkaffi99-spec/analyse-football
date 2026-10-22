"""Backtest walk-forward du BTTS (22/10/2026) : le modèle de production (Poisson indépendant sur les buts
attendus forme + H2H + Elo) n'a AUCUNE valeur prédictive mesurée (Brier 0.2490 contre 0.2500 pour le
hasard, tranche 60-70 % annoncée 63.3 % pour 55.9 % réel). Ce module compare, sur les mêmes matchs et sans
fuite du futur, des variantes qui n'utilisent que des données disponibles en production :

  V0  taux de BTTS de la ligue (constante)                         — plancher de référence
  V1  Poisson de production                                         — l'existant
  V2  Poisson recalibré (isotone, ajusté sur le passé)
  V3  taux de BTTS observé des deux équipes (10 derniers matchs)    — empirique
  V4  mélange Poisson / empirique (w = 0.25, 0.5, 0.75)
  V5  régression logistique sur [logit Poisson, taux BTTS, matchs sans marquer, clean sheets, buts attendus]

Walk-forward : le modèle appris sur le passé prédit le tiers suivant (coupures à 50 %, 67 %, 83 % du temps).
Aucune donnée du match prédit ni du futur n'entre dans ses features.
"""

import math
from collections import defaultdict

import analyser_et_envoyer as ae
import backtest_marches_absents as bt
from moteur import calibration as calib
from moteur.features import Historique, en_datetime, est_termine

NB_MIN = 5
COUPURES = (0.50, 0.67, 0.83)
NOMS_FEATURES = ("logit_poisson", "btts_dom", "btts_ext", "fts_dom", "fts_ext", "cs_dom", "cs_ext", "mu_total")
# V6 : features supplémentaires (lieu, tirs cadrés, Elo, buts attendus séparés, ligue)
NOMS_FEATURES_ETENDUES = NOMS_FEATURES + (
    "btts_dom_a_domicile", "btts_ext_a_exterieur", "sot_pour_dom", "sot_contre_dom", "sot_pour_ext", "sot_contre_ext",
    "mu_dom", "mu_ext", "ecart_mu", "elo_diff", "over25_dom", "over25_ext")


def _taux(vues, test):
    return sum(1 for v in vues if test(v)) / len(vues)


def _moy_stat(vues, cle, champ, defaut):
    valeurs = [v[cle].get(champ) for v in vues if v[cle].get(champ) is not None]
    return sum(valeurs) / len(valeurs) if valeurs else defaut


def construire_echantillons(matchs_par_competition):
    """[{t, y, p_pois, features{...}}] triés par date — features uniquement du PASSÉ du match."""
    echantillons = []
    for matchs in matchs_par_competition.values():
        hist = Historique(matchs)
        par_paire = defaultdict(list)
        for m in matchs:
            if est_termine(m):
                par_paire[frozenset((m["home_id"], m["away_id"]))].append(m)
        for paire in par_paire.values():
            paire.sort(key=lambda x: en_datetime(x["date"]))
        for m in matchs:
            if not est_termine(m):
                continue
            t = en_datetime(m["date"])
            mu = bt._mu_buts(m, hist, par_paire, t)
            if not mu:
                continue
            vh, va = hist.equipe_avant(m["home_id"], t, n=10), hist.equipe_avant(m["away_id"], t, n=10)
            if len(vh) < NB_MIN or len(va) < NB_MIN:
                continue
            p = min(max(ae.proba_btts(*mu), 1e-4), 1 - 1e-4)
            echantillons.append({
                "t": t, "y": 1 if (m["home_score"] > 0 and m["away_score"] > 0) else 0, "p_pois": p,
                "f": {"logit_poisson": math.log(p / (1 - p)),
                      "btts_dom": _taux(vh, lambda v: v["buts_pour"] > 0 and v["buts_contre"] > 0),
                      "btts_ext": _taux(va, lambda v: v["buts_pour"] > 0 and v["buts_contre"] > 0),
                      "fts_dom": _taux(vh, lambda v: v["buts_pour"] == 0), "fts_ext": _taux(va, lambda v: v["buts_pour"] == 0),
                      "cs_dom": _taux(vh, lambda v: v["buts_contre"] == 0), "cs_ext": _taux(va, lambda v: v["buts_contre"] == 0),
                      "mu_total": mu[0] + mu[1]},
                "ligue": m.get("competition_id")})
            vd = hist.equipe_avant(m["home_id"], t, n=10, domicile=True)
            ve = hist.equipe_avant(m["away_id"], t, n=10, domicile=False)
            f = echantillons[-1]["f"]
            f["btts_dom_a_domicile"] = _taux(vd, lambda v: v["buts_pour"] > 0 and v["buts_contre"] > 0) if len(vd) >= 3 else f["btts_dom"]
            f["btts_ext_a_exterieur"] = _taux(ve, lambda v: v["buts_pour"] > 0 and v["buts_contre"] > 0) if len(ve) >= 3 else f["btts_ext"]
            f["sot_pour_dom"], f["sot_contre_dom"] = _moy_stat(vh, "stats_pour", "shots_on_target", 4.4), _moy_stat(vh, "stats_contre", "shots_on_target", 4.4)
            f["sot_pour_ext"], f["sot_contre_ext"] = _moy_stat(va, "stats_pour", "shots_on_target", 4.4), _moy_stat(va, "stats_contre", "shots_on_target", 4.4)
            f["mu_dom"], f["mu_ext"], f["ecart_mu"] = mu[0], mu[1], mu[0] - mu[1]
            elo_h, elo_a = hist.elo(m)
            f["elo_diff"] = (elo_h - elo_a) / 100
            f["over25_dom"] = _taux(vh, lambda v: v["buts_pour"] + v["buts_contre"] >= 3)
            f["over25_ext"] = _taux(va, lambda v: v["buts_pour"] + v["buts_contre"] >= 3)
    echantillons.sort(key=lambda e: e["t"])
    return echantillons


# ------------------------------------------------------------------ régression logistique (Python pur)
def _sigmoide(z):
    return 1 / (1 + math.exp(-max(min(z, 30), -30)))


def entrainer_logistique(X, y, l2=1.0, iterations=300, lr=0.5):
    """Descente de gradient sur des features standardisées. Renvoie (moyennes, ecarts, poids, biais)."""
    n, d = len(X), len(X[0])
    moy = [sum(x[j] for x in X) / n for j in range(d)]
    ec = [max(math.sqrt(sum((x[j] - moy[j]) ** 2 for x in X) / n), 1e-9) for j in range(d)]
    Z = [[(x[j] - moy[j]) / ec[j] for j in range(d)] for x in X]
    w, b = [0.0] * d, 0.0
    for _ in range(iterations):
        gw, gb = [0.0] * d, 0.0
        for z, yi in zip(Z, y):
            e = _sigmoide(sum(wj * zj for wj, zj in zip(w, z)) + b) - yi
            for j in range(d):
                gw[j] += e * z[j]
            gb += e
        w = [wj - lr * (gwj / n + l2 * wj / n) for wj, gwj in zip(w, gw)]
        b -= lr * gb / n
    return moy, ec, w, b


def predire_logistique(modele, x):
    moy, ec, w, b = modele
    return _sigmoide(sum(wj * (xj - m) / e for wj, xj, m, e in zip(w, x, moy, ec)) + b)


def _vec(e, noms=NOMS_FEATURES):
    return [e["f"][k] for k in noms]


def _vec_ligue(e, ligues):
    return _vec(e, NOMS_FEATURES_ETENDUES) + [1.0 if e.get("ligue") == l else 0.0 for l in ligues]


# ------------------------------------------------------------------ variantes
def predictions_walk_forward(echantillons):
    """{variante: [(p_yes, y)]} sur les 2 derniers tiers du temps, modèle toujours appris sur le PASSÉ."""
    n = len(echantillons)
    bornes = [int(n * c) for c in COUPURES] + [n]
    sorties = defaultdict(list)
    for debut, fin in zip(bornes[:-1], bornes[1:]):
        passe, futur = echantillons[:debut], echantillons[debut:fin]
        if len(passe) < 200 or not futur:
            continue
        taux_ligue = sum(e["y"] for e in passe) / len(passe)
        iso = calib.Isotone([(e["p_pois"], e["y"]) for e in passe])
        logi = entrainer_logistique([_vec(e) for e in passe], [e["y"] for e in passe])
        ligues = sorted({e.get("ligue") for e in passe if e.get("ligue") is not None})[:-1]  # une de moins (colinéarité)
        logi2 = entrainer_logistique([_vec_ligue(e, ligues) for e in passe], [e["y"] for e in passe], l2=20.0)
        for e in futur:
            emp = (e["f"]["btts_dom"] + e["f"]["btts_ext"]) / 2
            sorties["V0 taux de ligue"].append((taux_ligue, e["y"]))
            sorties["V1 Poisson (production)"].append((e["p_pois"], e["y"]))
            sorties["V2 Poisson recalibré (isotone)"].append((iso(e["p_pois"]), e["y"]))
            sorties["V3 taux BTTS des deux équipes"].append((emp, e["y"]))
            for w in (0.25, 0.5, 0.75):
                sorties[f"V4 mélange Poisson {w:.2f} / empirique"].append((w * e["p_pois"] + (1 - w) * emp, e["y"]))
            sorties["V5 régression logistique"].append((predire_logistique(logi, _vec(e)), e["y"]))
            sorties["V6 logistique étendue (lieu, tirs cadrés, Elo, ligue)"].append(
                (predire_logistique(logi2, _vec_ligue(e, ligues)), e["y"]))
    return sorties


def metriques(points):
    n = len(points)
    eps = 1e-6
    brier = sum((p - y) ** 2 for p, y in points) / n
    ll = -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in points) / n
    cotes = {}
    for seuil in (0.60, 0.65, 0.70):
        cote_probable = [(max(p, 1 - p), 1 if (y == 1) == (p >= 0.5) else 0) for p, y in points if max(p, 1 - p) >= seuil]
        cotes[seuil] = (len(cote_probable), sum(c for _, c in cote_probable) / len(cote_probable) if cote_probable else None,
                        sum(q for q, _ in cote_probable) / len(cote_probable) if cote_probable else None)
    return {"n": n, "brier": brier, "log_loss": ll, "seuils": cotes}


def imprimer(sorties):
    base = metriques(sorties["V0 taux de ligue"])["brier"]
    print(f"\n{'variante':44s} {'n':>6s} {'Brier':>8s} {'gain/V0':>8s} {'logloss':>8s}   côté probable : n (réel / annoncé)")
    for nom in sorted(sorties):
        m = metriques(sorties[nom])
        s = "   ".join(f">={int(k * 100)}%: {v[0]} ({100 * v[1]:.1f}/{100 * v[2]:.1f})" for k, v in m["seuils"].items() if v[0])
        print(f"{nom:44s} {m['n']:6d} {m['brier']:8.4f} {100 * (base - m['brier']) / base:+7.2f}% {m['log_loss']:8.4f}   {s}")
    meilleur = min(sorties, key=lambda k: metriques(sorties[k])["brier"])
    print(f"\n-> Meilleure variante (Brier) : {meilleur}")
    pts = sorties[meilleur]
    print("\nCalibration de la meilleure variante (côté probable) :")
    for bas, haut in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.7), (0.7, 1.01)):
        dans = [(max(p, 1 - p), 1 if (y == 1) == (p >= 0.5) else 0) for p, y in pts if bas <= max(p, 1 - p) < haut]
        if dans:
            print(f"   {bas:.2f}-{min(haut, 1):.2f}: n={len(dans):5d} annoncé={100 * sum(q for q, _ in dans) / len(dans):5.1f}% "
                  f"réel={100 * sum(c for _, c in dans) / len(dans):5.1f}%")
    return meilleur


if __name__ == "__main__":  # pragma: no cover — lancé par diagnostics.yml (accès base)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app.database import SessionLocal
    from app.services.historique import charger_matchs

    competitions = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
    with SessionLocal() as db:
        donnees = {cid: charger_matchs(db, competition_id=cid) for cid in competitions}
    ech = construire_echantillons(donnees)
    print(f"{len(ech)} matchs utilisables ({', '.join(competitions.values())}).")
    imprimer(predictions_walk_forward(ech))
