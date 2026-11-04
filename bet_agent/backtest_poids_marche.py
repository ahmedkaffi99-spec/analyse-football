"""Backtest du POIDS DU MODÈLE dans le mélange marché/modèle (production : 35 % modèle, 65 % marché — POIDS_MARCHE).
Question du 04/11/2026 : les jambes à edge positif (modèle > marché) réussissent bien moins (60 % contre 78 %) — le modèle
apporte-t-il quelque chose au marché, ou faut-il baisser son poids ?

Méthode : matchs terminés des 5 grands championnats sur les 7 derniers jours dont API-Football sert encore les cotes
d'avant-match 1xBet. Pour chaque match : probabilités du marché 1xBet SANS MARGE (1X2, plus/moins 2,5, BTTS) et probabilités
du MODÈLE de production (forme 10 matchs -> H2H -> Elo, Poisson, depuis hist_matchs). On mesure, pour chaque poids de modèle
w (0 = marché seul, 1 = modèle seul), Brier et log-loss contre le résultat réel, et l'écart au poids de production avec son
erreur-type (appariée par match). Lecture seule. Limite : ~80 matchs, donc une différence de moins de ~2 erreurs-types n'est
pas concluante ; l'historique stocké s'arrête à sa dernière mise à jour (affichée)."""
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

POIDS_MODELE = (0.0, 0.15, 0.35, 0.5, 0.75, 1.0)
POIDS_PRODUCTION = 0.35
LIGUES = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}


def melanger(p_marche, p_modele, w):
    """{sélection: proba} : (1 - w) x marché + w x modèle."""
    return {s: (1 - w) * p_marche[s] + w * p_modele[s] for s in p_marche}


def scores(p, gagnante):
    """(Brier, log-loss) d'une distribution {sélection: proba} contre la sélection gagnante."""
    brier = sum((q - (1.0 if s == gagnante else 0.0)) ** 2 for s, q in p.items())
    return brier, -math.log(max(p[gagnante], 1e-9))


def resume(par_poids):
    """par_poids : {w: [(brier, logloss) par match]} -> lignes (w, n, brier moyen, logloss moyen, écart de Brier au poids de
    production, erreur-type de cet écart). Écart > 0 : moins bon que la production."""
    base = par_poids[POIDS_PRODUCTION]
    lignes = []
    for w in sorted(par_poids):
        v = par_poids[w]
        n = len(v)
        diffs = [a[0] - b[0] for a, b in zip(v, base)]
        moy = sum(diffs) / n
        et = math.sqrt(sum((d - moy) ** 2 for d in diffs) / (n - 1) / n) if n > 1 else float("nan")
        lignes.append((w, n, sum(x[0] for x in v) / n, sum(x[1] for x in v) / n, moy, et))
    return lignes


def main():
    racine = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(racine / "backend"))
    sys.path.insert(0, str(racine))
    import analyser_et_envoyer as ae
    import adaptateur_api_football as adf
    import consensus_bookmakers as cb
    from app.database import SessionLocal
    from app.services.historique import charger_matchs
    from backtest_bookmakers import NB_JOURS, NB_MATCHS_MAX, get, issue_reelle
    from backtest_marches_absents import _mu_buts
    from moteur.features import Historique, en_datetime, est_termine

    hist_par_ligue = {}
    with SessionLocal() as db:
        for lid in LIGUES:
            matchs = charger_matchs(db, competition_id=lid)
            par_paire = defaultdict(list)
            for m in matchs:
                if est_termine(m):
                    par_paire[frozenset((m["home_id"], m["away_id"]))].append(m)
            for p in par_paire.values():
                p.sort(key=lambda x: en_datetime(x["date"]))
            derniere = max((m["date"] for m in matchs if est_termine(m)), default="—")
            hist_par_ligue[lid] = (Historique(matchs), par_paire)
            print(f"{LIGUES[lid]} : {len(matchs)} matchs stockés, dernier match joué {str(derniere)[:10]}")

    aujourd_hui = datetime.now(timezone.utc).date()
    termines = []
    for i in range(1, NB_JOURS + 1):
        jour = (aujourd_hui - timedelta(days=i)).isoformat()
        termines += [fx for fx in get("fixtures", date=jour, status="FT") if (fx.get("league") or {}).get("id") in LIGUES]
    print(f"\n{len(termines)} match(s) terminés des 5 grands championnats sur {NB_JOURS} jours")

    acc = defaultdict(lambda: defaultdict(list))   # marché -> poids -> [(brier, logloss)]
    utilises = 0
    for fx in termines[:NB_MATCHS_MAX]:
        buts = fx.get("goals") or {}
        if buts.get("home") is None or buts.get("away") is None:
            continue
        reponse = get("odds", fixture=fx["fixture"]["id"])
        time.sleep(0.25)
        cotes = adf.cotes_par_bookmaker({"errors": [], "response": reponse}) if reponse else None
        marches_1x = (cotes or {}).get("1xBet")
        if not marches_1x:
            continue
        hist, par_paire = hist_par_ligue[fx["league"]["id"]]
        t = en_datetime(fx["fixture"]["date"])
        stub = {"match_id": -1, "date": fx["fixture"]["date"], "home_id": fx["teams"]["home"]["id"],
                "away_id": fx["teams"]["away"]["id"]}
        mu = _mu_buts(stub, hist, par_paire, t)
        if not mu:
            continue
        mu_h, mu_a = mu
        h, d, a = ae.proba_1x2(mu_h, mu_a)
        over = ae.proba_over(2.5, mu_h + mu_a)
        btts = ae.proba_btts(mu_h, mu_a)
        modeles = {("Full Time Result", None): {"1": h, "X": d, "2": a},
                   ("Over Under Full Time", 2.5): {"Over": over, "Under": 1 - over},
                   ("Both Teams To Score", None): {"Yes": btts, "No": 1 - btts}}
        ajoute = False
        for m in marches_1x:
            cle = (m["marche"], m.get("handicap") if m["marche"] == "Over Under Full Time" else None)
            if cle not in modeles:
                continue
            p_marche = cb.probas_sans_marge(m)
            p_modele = modeles[cle]
            gagnante = issue_reelle(m["marche"], m.get("handicap"), buts["home"], buts["away"])
            if not p_marche or set(p_marche) != set(p_modele) or gagnante not in p_marche:
                continue
            nom = {"Full Time Result": "1X2", "Over Under Full Time": "Plus/moins 2.5",
                   "Both Teams To Score": "BTTS"}[m["marche"]]
            for w in POIDS_MODELE:
                acc[nom][w].append(scores(melanger(p_marche, p_modele, w), gagnante))
            ajoute = True
        utilises += ajoute
    print(f"{utilises} match(s) utilisables (cotes 1xBet + modèle disponible)")
    if not utilises:
        print("→ Aucun match exploitable : rien à conclure.")
        return
    for nom in sorted(acc):
        print(f"\n=== {nom} (poids du modèle : 0 = marché seul, 1 = modèle seul ; production = {POIDS_PRODUCTION}) ===")
        print(f"{'w modèle':>9} {'n':>4} {'Brier':>7} {'logloss':>8} {'écart Brier / prod':>19} {'err-type':>9}")
        for w, n, brier, ll, ecart, et in resume(acc[nom]):
            marque = " ◄ production" if w == POIDS_PRODUCTION else ""
            print(f"{w:>9.2f} {n:>4} {brier:>7.4f} {ll:>8.4f} {ecart:>+19.4f} {et:>9.4f}{marque}")
    print("\nLecture : un écart négatif = meilleur que la production ; il n'est concluant que s'il dépasse ~2 erreurs-types.")


if __name__ == "__main__":  # pragma: no cover — lancé par diagnostics.yml (accès base + API-Football)
    main()
