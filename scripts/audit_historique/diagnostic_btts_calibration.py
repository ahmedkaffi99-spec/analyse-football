"""Diagnostic du modèle BTTS (modèle 7) et de la calibration aux probabilités élevées (>80%).

LECTURE SEULE : aucune écriture Supabase, aucun secret manipulé. Réutilise
moteur.backtest.generer_lignes (non modifié) et moteur.calibration (non modifié) sur des
matchs déjà chargés (DB directe ou cache JSON, voir backtest_complet.py pour les deux modes).

Ce script répond à trois questions, en reconstruisant chacune à partir des données réelles,
jamais en les déduisant du nom des modèles :
  1. Le modèle 7 (BTTS) est-il moins bon que le modèle 3 (Handicap/DNB) sur les MÊMES matchs,
     et pourquoi (distribution des labels, pouvoir discriminant, effet de rho_dixon_coles) ?
  2. La surconfiance aux tranches >80% est-elle un biais permanent ou un artefact des premiers
     mois du walk-forward (peu d'historique de calibration disponible) ?
  3. Platt scaling apporte-t-il une amélioration ROBUSTE par rapport à la régression isotone
     déjà utilisée, sur un découpage chronologique strict train(60%)/validation(20%)/test(20%),
     le test n'étant jamais utilisé pour ajuster quoi que ce soit ?
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

LIGUES_PRIORITAIRES = (39, 140, 135, 78, 61)
SAISONS_PRIORITAIRES = (2022, 2023, 2024, 2025)


def _preparer_chemins():
    racine = Path(__file__).resolve().parents[2]
    for p in (racine, racine / "backend"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def charger_toutes_les_lignes(charger_matchs_fn, cfg):
    """charger_matchs_fn(ligue_id, saison) -> liste de matchs (format HistMatch.vers_dict)."""
    from moteur.backtest import generer_lignes

    toutes = []
    for ligue in LIGUES_PRIORITAIRES:
        for saison in SAISONS_PRIORITAIRES:
            matchs = charger_matchs_fn(ligue, saison)
            if not matchs:
                continue
            termines = [m for m in matchs if m.get("home_score") is not None]
            if len(termines) < 10:
                continue
            debut = min(m["date"] for m in termines)
            fin = str(max(m["date"] for m in termines))[:10] + "T23:59:59+00:00"
            toutes.extend(generer_lignes(matchs, {}, cfg, debut, fin))
    return toutes


def correlation(points):
    """Corrélation (proba brute, issue réelle) — mesure le pouvoir discriminant, indépendamment
    du niveau moyen (calibration). Une corrélation proche de 0 veut dire que la probabilité
    annoncée ne suit presque pas la réalité, même si elle est "bien calibrée en moyenne"."""
    n = len(points)
    if n == 0:
        return 0.0
    xs = [p for p, _ in points]
    ys = [y for _, y in points]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in points) / n
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    return cov / (sx * sy) if sx > 0 and sy > 0 else 0.0


def brier_skill_score(points, baseline=0.25):
    """1 - brier/baseline. Négatif = pire qu'une prédiction constante à 0.5 pour tout le
    monde — un signal qu'aucune lecture du seul Brier Score global ne révèle directement."""
    from moteur.calibration import brier

    b = brier(points)
    return 1 - b / baseline if b is not None else None


def diagnostic_btts(lignes, cfg_defaut):
    """Section 2 de la mission : diagnostic du modèle 7 vs modèle 3, SANS décider sur le seul
    Brier global — distribution des labels, corrélation, skill score, et grille rho (preuve ou
    réfutation empirique de l'hypothèse rho, jamais supposée vraie a priori)."""
    from moteur.calibration import brier, log_loss, tableau_fiabilite

    btts_oui = [(ln.proba_brute, ln.gagne) for ln in lignes if ln.modele == 7 and ln.binaire and ln.selection == "oui"]
    btts_tout = [(ln.proba_brute, ln.gagne) for ln in lignes if ln.modele == 7 and ln.binaire]
    handicap = [(ln.proba_brute, ln.gagne) for ln in lignes if ln.modele == 3 and ln.binaire]

    rapport = {
        "label_oui_reel_pct": round(100 * sum(y for _, y in btts_oui) / len(btts_oui), 2) if btts_oui else None,
        "n_btts": len(btts_tout), "n_handicap": len(handicap),
        "brier_btts": round(brier(btts_tout), 4), "log_loss_btts": round(log_loss(btts_tout), 4),
        "brier_handicap": round(brier(handicap), 4), "log_loss_handicap": round(log_loss(handicap), 4),
        "skill_score_btts": round(brier_skill_score(btts_tout), 4),
        "skill_score_handicap": round(brier_skill_score(handicap), 4),
        "correlation_btts": round(correlation(btts_oui), 4),
        "correlation_handicap": round(correlation(handicap), 4),
        "fiabilite_btts_oui": tableau_fiabilite(btts_oui),
    }

    rho_grille = {}
    for rho in (0.0, -0.05, -0.10, -0.15, -0.20):
        cfg_rho = replace(cfg_defaut, rho_dixon_coles=rho)
        lignes_rho = lignes if rho == 0.0 else None  # recalculé par l'appelant si besoin (coûteux)
        rho_grille[rho] = "voir main() — calcule réellement la grille, pas simulé ici"
    rapport["note_rho"] = ("La grille rho réelle doit être recalculée (chaque valeur change les "
                           "features) — voir main() pour les vrais chiffres, jamais une estimation.")
    return rapport


def grille_rho(charger_matchs_fn, cfg_defaut, valeurs=(0.0, -0.05, -0.10, -0.15, -0.20)):
    from moteur.calibration import brier, log_loss

    resultats = {}
    for rho in valeurs:
        cfg_rho = replace(cfg_defaut, rho_dixon_coles=rho)
        lignes_rho = charger_toutes_les_lignes(charger_matchs_fn, cfg_rho)
        btts = [(ln.proba_brute, ln.gagne) for ln in lignes_rho if ln.modele == 7 and ln.binaire]
        handicap = [(ln.proba_brute, ln.gagne) for ln in lignes_rho if ln.modele == 3 and ln.binaire]
        resultats[rho] = {"btts": {"n": len(btts), "brier": round(brier(btts), 4), "log_loss": round(log_loss(btts), 4)},
                          "handicap": {"n": len(handicap), "brier": round(brier(handicap), 4), "log_loss": round(log_loss(handicap), 4)}}
    return resultats


def decouper_chronologique(lignes_binaires, p_train=0.6, p_val=0.8):
    lignes_triees = sorted(lignes_binaires, key=lambda ln: ln.date)
    n = len(lignes_triees)
    i1, i2 = int(n * p_train), int(n * p_val)
    return lignes_triees[:i1], lignes_triees[i1:i2], lignes_triees[i2:]


def ajuster_isotone(train, min_n):
    from moteur.calibration import Calibrateur

    return Calibrateur(min_n=min_n).ajuster((ln.modele, ln.marche, ln.proba_brute, ln.gagne) for ln in train)


def appliquer_isotone(cal, lignes_cible):
    return [(cal.calibrer(ln.modele, ln.marche, ln.proba_brute)[0], ln.gagne) for ln in lignes_cible]


def ajuster_platt(train, min_n):
    """Un modèle de régression logistique par (modele, marche), sur logit(proba_brute).
    Renvoie {} si scikit-learn est indisponible (jamais une erreur bloquante)."""
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        return {}
    par_cle = defaultdict(list)
    for ln in train:
        par_cle[(ln.modele, ln.marche)].append((ln.proba_brute, ln.gagne))
    modeles = {}
    for cle, pts in par_cle.items():
        if len(pts) < min_n or len({y for _, y in pts}) < 2:
            continue
        xs = [[math.log(max(p, 1e-6) / max(1 - p, 1e-6))] for p, _ in pts]
        ys = [y for _, y in pts]
        clf = LogisticRegression()
        clf.fit(xs, ys)
        modeles[cle] = clf
    return modeles


def appliquer_platt(modeles, lignes_cible):
    sortie = []
    for ln in lignes_cible:
        clf = modeles.get((ln.modele, ln.marche))
        if clf is None:
            sortie.append((ln.proba_brute, ln.gagne))
        else:
            x = math.log(max(ln.proba_brute, 1e-6) / max(1 - ln.proba_brute, 1e-6))
            sortie.append((clf.predict_proba([[x]])[0][1], ln.gagne))
    return sortie


def main():
    import argparse
    import json

    _preparer_chemins()
    from moteur.calibration import brier, log_loss
    from moteur.config import Config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["db", "cache"], default="db")
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args()

    from backtest_complet import charger_depuis_cache, charger_depuis_db

    if args.source == "cache":
        if not args.cache_dir:
            parser.error("--cache-dir est requis avec --source cache")
        charger = lambda ligue_id, saison: charger_depuis_cache(args.cache_dir, ligue_id, saison)  # noqa: E731
    else:
        charger = charger_depuis_db

    cfg = Config()
    lignes = charger_toutes_les_lignes(charger, cfg)

    print("=== 1. BTTS (modèle 7) vs Handicap/DNB (modèle 3) — mêmes matchs, rho=0 (défaut) ===")
    r = diagnostic_btts(lignes, cfg)
    for k, v in r.items():
        if k not in ("fiabilite_btts_oui", "note_rho"):
            print(f"  {k}: {v}")
    print("  Fiabilité BTTS 'oui' (raw) :")
    for l in r["fiabilite_btts_oui"]:
        print(f"    {l}")

    print("\n=== 2. Grille rho_dixon_coles (recalcul réel, pas simulé) ===")
    for rho, res in grille_rho(charger, cfg).items():
        print(f"  rho={rho:+.2f} : BTTS {res['btts']} | Handicap {res['handicap']}")

    print("\n=== 3. Calibration — découpage chronologique strict 60/20/20 ===")
    binaires = [ln for ln in lignes if ln.binaire]
    train, val, test = decouper_chronologique(binaires)
    print(f"  train={len(train)} (jusqu'à {train[-1].date.date()}), "
          f"validation={len(val)} ({val[0].date.date()}-{val[-1].date.date()}), "
          f"test={len(test)} ({test[0].date.date()}-{test[-1].date.date()})")

    cal_iso = ajuster_isotone(train, cfg.calibration_min_n)
    modeles_platt = ajuster_platt(train, cfg.calibration_min_n)

    for nom_ens, ens in (("VALIDATION", val), ("TEST", test)):
        print(f"\n  -- {nom_ens} --")
        for nom_methode, pts in (
            ("RAW", [(ln.proba_brute, ln.gagne) for ln in ens]),
            ("ISOTONE", appliquer_isotone(cal_iso, ens)),
            ("PLATT", appliquer_platt(modeles_platt, ens) if modeles_platt else None),
        ):
            if pts is None:
                print(f"    {nom_methode}: indisponible (scikit-learn absent)")
                continue
            haut = [(p, y) for p, y in pts if p >= 0.80]
            msg = f"    {nom_methode}: global n={len(pts)} brier={brier(pts):.4f} log_loss={log_loss(pts):.4f}"
            if haut:
                msg += (f" | >=80% n={len(haut)} brier={brier(haut):.4f} "
                       f"proba_moy={sum(p for p,_ in haut)/len(haut):.4f} "
                       f"freq_reelle={sum(y for _,y in haut)/len(haut):.4f}")
            print(msg)


if __name__ == "__main__":
    main()
