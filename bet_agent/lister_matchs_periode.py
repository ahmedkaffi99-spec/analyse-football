"""Liste les matchs des 5 grands championnats (Ligue 1, Premier League, Serie A, Bundesliga,
La Liga) sur une période donnée — utilitaire de consultation, ne collecte ni ne parie sur rien.

Usage : python -m lister_matchs_periode [--jours 16]
Variables : ODDSPAPI_KEY (obligatoire)."""
import os
import sys
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "envi.local"))

from collecte_donnees import (SESSION, ODDSPAPI_KEY, VERIFIER_SSL_ODDSPAPI,
                              contient_indicateur_reserve, est_competition_feminine,
                              FILTRE_LIGUES_UNIQUES)


def _recuperer_tranche(date_from, date_to):
    url = "https://api.oddspapi.io/v4/fixtures"
    params = {"apiKey": ODDSPAPI_KEY, "sportId": 10,
              "from": date_from.strftime("%Y-%m-%dT00:00:00Z"),
              "to": date_to.strftime("%Y-%m-%dT00:00:00Z")}
    r = SESSION.get(url, params=params, timeout=(5, 30), verify=VERIFIER_SSL_ODDSPAPI)
    if r.status_code != 200:
        print(f"❌ OddsPapi HTTP {r.status_code} : {r.text[:300]}")
        sys.exit(1)
    fixtures = r.json()
    return fixtures if isinstance(fixtures, list) else []


def recuperer_fixtures(date_from, date_to):
    # OddsPapi limite 'from'/'to' à 10 jours d'écart max quand seul sportId est fourni —
    # on découpe donc la période en tranches de 9 jours (marge de sécurité) et on fusionne.
    fixtures = []
    curseur = date_from
    while curseur < date_to:
        fin_tranche = min(curseur + timedelta(days=9), date_to)
        fixtures.extend(_recuperer_tranche(curseur, fin_tranche))
        curseur = fin_tranche
    return fixtures


def correspond_a_une_ligue_majeure(fx):
    nom_tournoi = (fx.get("tournamentName") or "").lower()
    pays = (fx.get("categoryName") or "").lower()
    return any(mc in nom_tournoi and p in pays for mc, p in FILTRE_LIGUES_UNIQUES)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jours", type=int, default=16, help="Nombre de jours à partir d'aujourd'hui")
    args = parser.parse_args()

    if not ODDSPAPI_KEY:
        print("❌ ODDSPAPI_KEY manquante")
        sys.exit(1)

    aujourdhui = datetime.now()
    fin = aujourdhui + timedelta(days=args.jours)
    print(f"📅 Recherche des matchs du {aujourdhui:%d/%m/%Y} au {fin:%d/%m/%Y} "
          f"(5 grands championnats)...\n")

    fixtures = recuperer_fixtures(aujourdhui, fin)
    vus, dedupliquees = set(), []
    for fx in fixtures:
        cle = fx.get("id") or (fx.get("participant1Name"), fx.get("participant2Name"), fx.get("startTime"))
        if cle in vus:
            continue
        vus.add(cle)
        dedupliquees.append(fx)
    fixtures = dedupliquees
    print(f"→ {len(fixtures)} fixtures OddsPapi au total sur la période\n")

    par_date = defaultdict(list)
    for fx in fixtures:
        p1, p2 = fx.get("participant1Name", ""), fx.get("participant2Name", "")
        if contient_indicateur_reserve(p1) or contient_indicateur_reserve(p2):
            continue
        if est_competition_feminine(fx.get("tournamentName"), fx.get("categoryName")):
            continue
        if not correspond_a_une_ligue_majeure(fx):
            continue
        date_brute = fx.get("startTime") or ""
        try:
            jour = datetime.fromisoformat(date_brute.replace("Z", "+00:00")).strftime("%Y-%m-%d (%A)")
        except ValueError:
            jour = date_brute or "date inconnue"
        par_date[jour].append(f"{fx.get('tournamentName', '?')} — {p1} vs {p2}")

    if not par_date:
        print("⚠️ Aucun match des 5 grands championnats trouvé sur cette période.")
        return

    total = 0
    for jour in sorted(par_date):
        matchs = par_date[jour]
        total += len(matchs)
        print(f"### {jour} ({len(matchs)} match(s))")
        for m in matchs:
            print(f"   • {m}")
        print()
    print(f"✅ Total : {total} match(s) de grands championnats jusqu'au {fin:%d/%m/%Y}")


if __name__ == "__main__":
    main()
