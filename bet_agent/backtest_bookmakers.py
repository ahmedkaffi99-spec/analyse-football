"""Backtest, bookmaker par bookmaker, des cotes servies par API-Football (demande du 26/10/2026).
Pour chaque match TERMINÉ des grandes ligues dont l'API sert encore les cotes d'avant-match, on ramène les
cotes de chaque bookmaker à des probabilités sans marge (1X2, Over/Under 2.5, BTTS) et on mesure contre le
résultat réel : Brier, log-loss, marge moyenne et rendement d'un pari « à l'aveugle » sur chaque issue.
Lecture seule : aucun écriture en base. Limite connue : API-Football ne garde les cotes d'avant-match que
quelques jours — l'échantillon dépend de ce qu'il en reste ; sinon le script le dit et ne conclut rien."""
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

import adaptateur_api_football as adf
import collecte_donnees as cd
import consensus_bookmakers as cb

NB_JOURS = int(os.getenv("BACKTEST_NB_JOURS") or "7")
NB_MATCHS_MAX = int(os.getenv("BACKTEST_NB_MATCHS") or "80")
H = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY") or ""}


def get(chemin, **params):
    r = requests.get(f"{adf.API_FOOTBALL_BASE}/{chemin}", headers=H, params=params, timeout=30)
    return r.json().get("response") or []


def issue_reelle(marche, handicap, buts_dom, buts_ext):
    """Sélection gagnante du marché pour le score final, ou None si le marché n'est pas évalué ici."""
    if marche == "Full Time Result":
        return "1" if buts_dom > buts_ext else ("2" if buts_ext > buts_dom else "X")
    if marche == "Over Under Full Time" and handicap == 2.5:
        return "Over" if buts_dom + buts_ext > 2.5 else "Under"
    if marche == "Both Teams To Score":
        return "Yes" if buts_dom > 0 and buts_ext > 0 else "No"
    return None


def evaluer(cotes_bookmakers, buts_dom, buts_ext, acc):
    """Ajoute à acc[(bookmaker, marché)] les mesures de ce match. 'Consensus' est ajouté comme bookmaker."""
    cons = cb.consensus(cotes_bookmakers)
    par_marche = defaultdict(dict)   # (marché, ligne) -> {sel: proba consensus}
    for (marche, ligne, sel), v in cons.items():
        par_marche[(marche, ligne)][sel] = v["proba_pct"] / 100
    sources = dict(cotes_bookmakers)
    for bm, marches in sources.items():
        for m in marches:
            nom, ligne = m["marche"], m.get("handicap")
            gagnante = issue_reelle(nom, ligne, buts_dom, buts_ext)
            if gagnante is None:
                continue
            probas = cb.probas_sans_marge(m)
            cotes = {s["selection"]: s["cote"] for s in m["selections"]}
            if not probas or gagnante not in probas:
                continue
            enr = acc[(bm, nom if ligne is None else f"{nom} {ligne}")]
            enr["n"] += 1
            enr["brier"] += sum((p - (1.0 if s == gagnante else 0.0)) ** 2 for s, p in probas.items())
            enr["logloss"] += -math.log(max(probas[gagnante], 1e-9))
            enr["marge"] += sum(1 / c for c in cotes.values()) - 1
            enr["roi"] += sum((c if s == gagnante else 0.0) - 1 for s, c in cotes.items()) / len(cotes)
    for (nom, ligne), probas in par_marche.items():
        gagnante = issue_reelle(nom, ligne, buts_dom, buts_ext)
        if gagnante is None or gagnante not in probas:
            continue
        enr = acc[("★ Consensus", nom if ligne is None else f"{nom} {ligne}")]
        enr["n"] += 1
        enr["brier"] += sum((p - (1.0 if s == gagnante else 0.0)) ** 2 for s, p in probas.items())
        enr["logloss"] += -math.log(max(probas[gagnante], 1e-9))


def main():
    aujourd_hui = datetime.now(timezone.utc).date()
    termines = []
    for i in range(1, NB_JOURS + 1):
        jour = (aujourd_hui - timedelta(days=i)).isoformat()
        for fx in get("fixtures", date=jour, status="FT"):
            if (fx.get("league") or {}).get("id") in cd.LIGUES_MAJEURES:
                termines.append(fx)
    print(f"{len(termines)} match(s) terminés des grandes ligues sur {NB_JOURS} jours")
    acc = defaultdict(lambda: {"n": 0, "brier": 0.0, "logloss": 0.0, "marge": 0.0, "roi": 0.0})
    avec_cotes = 0
    for fx in termines[:NB_MATCHS_MAX]:
        buts = fx.get("goals") or {}
        if buts.get("home") is None or buts.get("away") is None:
            continue
        reponse = get("odds", fixture=fx["fixture"]["id"])
        time.sleep(0.25)
        if not reponse:
            continue
        cotes = adf.cotes_par_bookmaker({"errors": [], "response": reponse})
        if not cotes:
            continue
        avec_cotes += 1
        evaluer(cotes, buts["home"], buts["away"], acc)
    print(f"{avec_cotes} match(s) avec des cotes d'avant-match encore servies")
    if not avec_cotes:
        print("→ Aucune cote d'avant-match disponible pour les matchs terminés : API-Football ne les garde pas assez "
              "longtemps. Le backtest ne peut se faire que sur des cotes enregistrées avant le match (collecte "
              "prospective), à juger ensuite.")
        return
    for marche in sorted({m for (_, m) in acc}):
        print(f"\n=== {marche} ===")
        print(f"{'bookmaker':<14} {'n':>4} {'Brier':>7} {'logloss':>8} {'marge':>7} {'ROI aveugle':>12}")
        lignes = [(bm, v) for (bm, m), v in acc.items() if m == marche and v["n"]]
        for bm, v in sorted(lignes, key=lambda x: x[1]["brier"] / x[1]["n"]):
            n = v["n"]
            marge = f"{100 * v['marge'] / n:5.1f} %" if v["marge"] else "    —"
            roi = f"{100 * v['roi'] / n:+6.1f} %" if v["marge"] else "    —"
            print(f"{bm:<14} {n:>4} {v['brier'] / n:>7.4f} {v['logloss'] / n:>8.4f} {marge:>7} {roi:>12}")


if __name__ == "__main__":
    main()
