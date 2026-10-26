"""Diagnostic en lecture seule : quels bookmakers API-Football sert-il sur les matchs à venir, et avec quelle
couverture / marge ? Sert à choisir les ~10 meilleurs bookmakers à collecter (demande du 26/10/2026).
Un appel GET /odds?fixture=<id> (sans filtre bookmaker) par match, 8 matchs au plus."""
import os
from collections import defaultdict

import requests

import adaptateur_api_football as adf
import collecte_donnees as cd

NB_MATCHS = int(os.getenv("NB_MATCHS_DIAG") or "8")
H = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY") or ""}


def get(chemin, **params):
    r = requests.get(f"{adf.API_FOOTBALL_BASE}/{chemin}", headers=H, params=params, timeout=30)
    return r.json().get("response") or []


def marge_1x2(bets):
    for b in bets:
        if (b.get("name") or "") == "Match Winner":
            cotes = [float(v["odd"]) for v in b.get("values") or [] if v.get("odd")]
            if len(cotes) == 3:
                return sum(1 / c for c in cotes) - 1
    return None


def main():
    a_venir = [fx for fx in cd.recuperer_fixtures_api_football()
               if ((fx.get("fixture") or {}).get("status") or {}).get("short") == "NS"]
    # Grandes ligues d'abord (là où les bookmakers servent des cotes), puis le reste.
    a_venir.sort(key=lambda fx: ((fx.get("league") or {}).get("id") not in cd.LIGUES_MAJEURES,
                                 (fx.get("fixture") or {}).get("timestamp") or 0))
    fixtures = a_venir[:NB_MATCHS]
    print(f"{len(fixtures)} match(s) à venir sondés")
    nb_matchs = defaultdict(int)
    nb_marches = defaultdict(list)
    marges = defaultdict(list)
    noms = {}
    for fx in fixtures:
        fid = fx["fixture"]["id"]
        print(f"· {fx['teams']['home']['name']} vs {fx['teams']['away']['name']} [{fx['league']['name']}]")
        for e in get("odds", fixture=fid):
            for bk in e.get("bookmakers", []):
                i = bk.get("id")
                noms[i] = bk.get("name")
                nb_matchs[i] += 1
                nb_marches[i].append(len(bk.get("bets", [])))
                m = marge_1x2(bk.get("bets", []))
                if m is not None:
                    marges[i].append(m)
    print(f"\n{len(noms)} bookmaker(s) servis. Classés par couverture puis nombre de marchés :")
    print(f"{'id':>4}  {'bookmaker':<22} {'matchs':>6} {'marchés/match':>14} {'marge 1X2':>10}")
    for i in sorted(noms, key=lambda i: (-nb_matchs[i], -sum(nb_marches[i]) / len(nb_marches[i]))):
        mm = marges[i]
        marge = f"{100 * sum(mm) / len(mm):.1f} %" if mm else "—"
        print(f"{i:>4}  {noms[i]:<22} {nb_matchs[i]:>6} {sum(nb_marches[i]) / len(nb_marches[i]):>14.0f} {marge:>10}")


if __name__ == "__main__":
    main()
