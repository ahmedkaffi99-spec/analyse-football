"""Test comparatif ISOLÉ (demande explicite du 09/10/2026) : API-Football peut-il remplacer
OddsPapi pour les cotes ? Ce script ne touche AUCUN module de production (collecte_donnees.py,
analyser_et_envoyer.py...), ne modifie rien, et NE FAIT AUCUN APPEL RÉSEAU tant qu'il n'est pas
exécuté directement avec --executer :

    python diagnostic_odds_api_football.py --executer

Sans --executer, il n'affiche que son plan (0 appel). Avec --executer, il fait EXACTEMENT :
- 1 appel GET /odds/bookmakers (pour trouver l'identifiant 1xBet chez API-Football) ;
- jusqu'à 3 appels GET /odds (un par match ci-dessous).
Soit 4 appels API-Football au total, 0 appel OddsPapi (la référence OddsPapi est déjà connue,
capturée par la production réelle — voir REFERENCE_ODDSPAPI) et 0 pipeline lancé.

Les 3 matchs et leurs cotes OddsPapi de référence sont des cotes RÉELLEMENT capturées en
production (table `cotes`, Supabase, run du 09/10/2026, 1xBet) — jamais fabriquées. Les
marchés absents de cette référence (cartons, tirs) sont marqués "absent côté OddsPapi" parce
qu'ils n'existent PAS dans les cotes réellement collectées pour ces 3 matchs (vérifié par
requête SQL, pas supposé) — rien à comparer pour eux ici, dans un sens ou dans l'autre.
"""

import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv("envi.local")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"  # même base/version que collecte_donnees.py (v3)
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY or ""}

# ============================================================
# RÉFÉRENCE : cotes OddsPapi/1xBet RÉELLEMENT capturées en production (Supabase, 09/10/2026).
# fixture_id_api_football vient de matchs.fixture_id_api_football (même ligne que les cotes).
# ============================================================

MATCHS = [
    {
        "nom": "SC Braga vs Sporting CP", "ligue": "Primeira Liga (Portugal)",
        "fixture_id_api_football": 1575512,
        "cotes_oddspapi": {
            "1X2 (Full Time Result)": {"1": 3.48, "X": 3.69, "2": 2.116},
            "Double Chance": {"1X": 1.774, "12": 1.307, "2X": 1.335},
            "Asian Handicap (ligne 0)": {"1": 2.521, "2": 1.577},
            "European Handicap (ligne +1 côté domicile)": {"1": 1.774, "X": 3.735, "2": 3.6},
            "Over/Under buts (ligne 2.5)": {"Over": 1.88, "Under": 2.004},
            "Buts équipe domicile (ligne 1.5)": {"Over": 2.5, "Under": 1.46},
            "Buts équipe extérieure (ligne 1.5)": {"Over": 1.95, "Under": 1.76},
            "BTTS": {"Yes": 1.666, "No": 2.08},
            "Corners Over/Under (ligne 9.5)": {"Over": 2.17, "Under": 1.58},
            "Cartons (Over/Under)": "absent côté OddsPapi pour ce match (vérifié par requête SQL)",
            "Tirs (Over/Under)": "absent côté OddsPapi pour ce match (vérifié par requête SQL)",
        },
    },
    {
        "nom": "Moghreb Tetouan vs FUS Rabat", "ligue": "Botola Pro (Maroc)",
        "fixture_id_api_football": 1644206,
        "cotes_oddspapi": {
            "1X2 (Full Time Result)": {"1": 2.953, "X": 2.82, "2": 2.42},
            "Double Chance": {"1X": 1.43, "12": 1.32, "2X": 1.3},
            "Asian Handicap (ligne 0)": {"1": 2.0, "2": 1.68},
            "European Handicap (ligne +1 côté domicile)": {"1": 1.43, "X": 3.74, "2": 5.4},
            "Over/Under buts (ligne 2.5)": {"Over": 2.59, "Under": 1.39},
            "Buts équipe domicile (ligne 1.5)": {"Over": 3.24, "Under": 1.27},
            "Buts équipe extérieure (ligne 1.5)": {"Over": 2.82, "Under": 1.35},
            "BTTS": {"Yes": 2.15, "No": 1.611},
            "Corners Over/Under": "absent côté OddsPapi pour ce match (vérifié par requête SQL)",
            "Cartons (Over/Under)": "absent côté OddsPapi pour ce match (vérifié par requête SQL)",
            "Tirs (Over/Under)": "absent côté OddsPapi pour ce match (vérifié par requête SQL)",
        },
    },
    {
        "nom": "União Santarém vs Lusitano Évora 1911", "ligue": "Liga 3 (Portugal)",
        "fixture_id_api_football": 1597783,
        "cotes_oddspapi": {
            "1X2 (Full Time Result)": {"1": 2.992, "X": 2.96, "2": 2.29},
            "Double Chance": {"1X": 1.47, "12": 1.28, "2X": 1.29},
            "Asian Handicap (ligne 0)": {"1": 2.08, "2": 1.63},
            "European Handicap (ligne +1 côté domicile)": {"1": 1.47, "X": 3.78, "2": 5.1},
            "Over/Under buts (ligne 2.5)": {"Over": 2.36, "Under": 1.5},
            "Buts équipe domicile (ligne 1.5)": {"Over": 3.06, "Under": 1.3},
            "Buts équipe extérieure (ligne 1.5)": {"Over": 2.55, "Under": 1.42},
            "BTTS": {"Yes": 1.99, "No": 1.705},
            "Corners Over/Under": "absent côté OddsPapi pour ce match (vérifié par requête SQL)",
            "Cartons (Over/Under)": "absent côté OddsPapi pour ce match (vérifié par requête SQL)",
            "Tirs (Over/Under)": "absent côté OddsPapi pour ce match (vérifié par requête SQL)",
        },
    },
]


def recuperer_bookmakers_api_football():
    """1 appel GET /odds/bookmakers — cherche un bookmaker dont le nom contient '1xbet'
    (aucune hypothèse sur son identifiant : jamais vu dans le code ni la documentation
    publique consultée pendant l'audit)."""
    r = requests.get(f"{BASE_URL}/odds/bookmakers", headers=HEADERS, timeout=15)
    data = r.json()
    if data.get("errors"):
        return None, r.status_code, data["errors"]
    bookmakers = data.get("response", [])
    trouve = next((b for b in bookmakers if "1xbet" in (b.get("name") or "").lower()), None)
    return trouve, r.status_code, bookmakers


def recuperer_odds_api_football(fixture_id, bookmaker_id=None):
    """1 appel GET /odds?fixture=...&bookmaker=... — bookmaker_id omis si 1xBet n'a pas été
    trouvé à l'étape précédente (renvoie alors TOUS les bookmakers disponibles pour ce match,
    toujours utile pour voir si 1xBet y figure sous un autre nom)."""
    params = {"fixture": fixture_id}
    if bookmaker_id:
        params["bookmaker"] = bookmaker_id
    r = requests.get(f"{BASE_URL}/odds", headers=HEADERS, params=params, timeout=20)
    data = r.json()
    return data, r.status_code


def extraire_marches_af_bookmaker(reponse_odds, nom_bookmaker):
    """reponse_odds : un élément de data['response'] (1 fixture). Renvoie {nom_pari EXACT:
    {valeur: cote}} pour le SEUL bookmaker demandé — aucune traduction/mapping vers le
    vocabulaire OddsPapi ici (fait à la main dans le rapport, pour ne jamais masquer une
    différence de granularité entre les deux fournisseurs)."""
    if not nom_bookmaker:
        return {}
    for bm in reponse_odds.get("bookmakers", []):
        if bm.get("name") == nom_bookmaker:
            return {bet.get("name"): {v.get("value"): v.get("odd") for v in bet.get("values", [])}
                   for bet in bm.get("bets", [])}
    return {}


def executer_comparaison():
    print("=" * 70)
    print("ÉTAPE 1/2 — recherche du bookmaker 1xBet chez API-Football (1 appel)")
    print("=" * 70)
    bookmaker_1xbet, statut, brut = recuperer_bookmakers_api_football()
    print(f"   statut HTTP = {statut}")
    if bookmaker_1xbet:
        print(f"   ✓ 1xBet trouvé : id={bookmaker_1xbet['id']}, nom=\"{bookmaker_1xbet['name']}\"")
    else:
        print("   ⚠️ Aucun bookmaker contenant '1xbet' dans la liste renvoyée par API-Football.")
        noms = [b.get("name") for b in brut] if isinstance(brut, list) else brut
        print(f"   → Bookmakers disponibles (ou erreur) : {noms}")
    bookmaker_id = bookmaker_1xbet["id"] if bookmaker_1xbet else None

    print("\n" + "=" * 70)
    print("ÉTAPE 2/2 — cotes API-Football par match (jusqu'à 3 appels)")
    print("=" * 70)
    for m in MATCHS:
        print(f"\n--- {m['nom']} ({m['ligue']}) — fixture API-Football {m['fixture_id_api_football']} ---")
        data, statut = recuperer_odds_api_football(m["fixture_id_api_football"], bookmaker_id)
        print(f"   statut HTTP = {statut}")
        if data.get("errors"):
            print(f"   ❌ Erreur API-Football : {data['errors']}")
            continue
        reponses = data.get("response", [])
        if not reponses:
            print("   ⚠️ Aucune cote renvoyée par API-Football pour ce fixture (plan insuffisant, "
                  "match trop éloigné, ou aucune cote suivie pour cette rencontre).")
            continue
        for rep in reponses:
            marches_af = extraire_marches_af_bookmaker(rep, bookmaker_1xbet["name"] if bookmaker_1xbet else None)
            print(f"   Mise à jour API-Football (\"update\") : {rep.get('update')}")
            print(f"   {len(marches_af)} marché(s) 1xBet renvoyés par API-Football, noms EXACTS :")
            for nom_pari, valeurs in sorted(marches_af.items()):
                print(f"      \"{nom_pari}\" : {valeurs}")

        print("   --- Référence OddsPapi/1xBet (déjà capturée en production) ---")
        for marche, valeurs in m["cotes_oddspapi"].items():
            print(f"      {marche} : {valeurs}")
        print("   ⚠️ Comparaison marché-par-marché à faire manuellement sur la sortie brute "
              "ci-dessus (voir rapport) — ce script affiche les deux côtés, ne décide rien seul.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executer", action="store_true",
                        help="Sans ce drapeau : aucun appel réseau, affiche seulement le plan.")
    args = parser.parse_args()

    print(f"Plan : 1 appel /odds/bookmakers + jusqu'à {len(MATCHS)} appel(s) /odds "
          f"= {1 + len(MATCHS)} appels API-Football au total. 0 appel OddsPapi (référence déjà connue).")
    for m in MATCHS:
        print(f"   - {m['nom']} ({m['ligue']}) — fixture {m['fixture_id_api_football']}")

    if not args.executer:
        print("\nAucun appel effectué (relancer avec --executer pour exécuter réellement ces "
              f"{1 + len(MATCHS)} appels, après autorisation explicite).")
        return
    if not API_FOOTBALL_KEY:
        print("\n❌ API_FOOTBALL_KEY absente de envi.local — impossible d'exécuter.")
        return
    executer_comparaison()


if __name__ == "__main__":
    main()
