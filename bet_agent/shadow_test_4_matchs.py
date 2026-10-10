"""Test réel budgétisé OddsPapi vs API-Football sur 4 matchs (demande explicite, autorisation
du 10/10/2026) — identifiants déjà validés, AUCUNE nouvelle identification ici.

Budget RÉEL maximum si --executer : 1x /v4/markets (catalogue OddsPapi, une seule fois, mis
en cache) + 4x OddsPapi /v4/odds (capturer_oddspapi_sans_retry, UNE tentative chacun, jamais de
retry) + 4x API-Football /odds (capturer_api_football, UNE tentative chacun) = 9 appels réels
MAXIMUM, jamais dépassé même en cas d'erreur HTTP 429 (aucun appel supplémentaire n'est tenté
après un échec, voir shadow_capture.py).

Mode SHADOW strict : aucune cote ici n'est ni ne sera utilisée pour produire ou modifier un
coupon — ce fichier n'est importé par aucun module de production."""

import argparse
import json

from shadow_capture import capturer_api_football, capturer_oddspapi_sans_retry
from shadow_metriques import associer_matchs, mesurer_ecarts, rapport_complet

MATCHS = [
    {"championnat": "Premier League", "domicile": "Arsenal FC", "exterieur": "Leeds United",
     "fixture_id_oddspapi": "id1000001772221292", "fixture_id_api_football": 1557417},
    {"championnat": "Serie A", "domicile": "Genoa CFC", "exterieur": "ACF Fiorentina",
     "fixture_id_oddspapi": "id1000002371945292", "fixture_id_api_football": 1550140},
    {"championnat": "Bundesliga", "domicile": "TSG Hoffenheim", "exterieur": "Hamburger SV",
     "fixture_id_oddspapi": "id1000003572513224", "fixture_id_api_football": 1575178},
    {"championnat": "Ligue 1", "domicile": "Lille OSC", "exterieur": "Le Havre AC",
     "fixture_id_oddspapi": "id1000003472036206", "fixture_id_api_football": 1552776},
]


def executer():
    requetes_op, requetes_af, cotations_op, cotations_af = [], [], [], []
    correspondance = {}

    for m in MATCHS:
        print(f"\n--- {m['championnat']} : {m['domicile']} vs {m['exterieur']} ---")
        req_op, cotes_op = capturer_oddspapi_sans_retry(
            m["fixture_id_oddspapi"], m["championnat"], m["domicile"], m["exterieur"])
        req_af, cotes_af = capturer_api_football(
            m["fixture_id_api_football"], m["championnat"], m["domicile"], m["exterieur"])
        print(f"   OddsPapi      : statut={req_op.statut_http} erreur={req_op.erreur} "
              f"marchés_bruts={req_op.nb_marches_recus} reçu_le={req_op.recu_le_utc.isoformat()}")
        print(f"   API-Football  : statut={req_af.statut_http} erreur={req_af.erreur} "
              f"marchés_bruts={req_af.nb_marches_recus} reçu_le={req_af.recu_le_utc.isoformat()}")
        requetes_op.append(req_op)
        requetes_af.append(req_af)
        cotations_op.extend(cotes_op)
        cotations_af.extend(cotes_af)
        correspondance[m["fixture_id_oddspapi"]] = m["fixture_id_api_football"]

    paires, non_appariees_op, non_appariees_af = associer_matchs(cotations_op, cotations_af, correspondance)
    mesures = mesurer_ecarts(paires)
    rapport = rapport_complet(mesures, requetes_op, requetes_af,
                              [m["fixture_id_oddspapi"] for m in MATCHS], correspondance)

    print("\n" + "=" * 70)
    print("RAPPORT AGRÉGÉ (JSON)")
    print("=" * 70)
    print(json.dumps(rapport, indent=2, ensure_ascii=False, default=str))

    print(f"\nMarchés OddsPapi SANS correspondance API-Football ({len(non_appariees_op)}) :")
    for c in non_appariees_op:
        print(f"   [{c.championnat}] {c.marche} {c.selection} (ligne {c.ligne}) = {c.cote} "
              f"(brut: \"{c.marche_brut}\")")

    print(f"\nMarchés API-Football SANS correspondance OddsPapi ({len(non_appariees_af)}) :")
    for c in non_appariees_af:
        print(f"   [{c.championnat}] {c.marche} {c.selection} (ligne {c.ligne}) = {c.cote} "
              f"(brut: \"{c.marche_brut}\")")

    print(f"\nMesures détaillées des {len(mesures)} paire(s) comparée(s) :")
    for mes in mesures:
        print(f"   [{mes['championnat']}] {mes['marche']} {mes['selection']} (ligne {mes['ligne']}) : "
              f"OddsPapi={mes['cote_oddspapi']} API-Football={mes['cote_api_football']} "
              f"écart_abs={mes['ecart_absolu']} écart_rel={mes['ecart_relatif']} "
              f"délai={mes['delai_secondes']}s maj_api={mes['maj_api_utc']}")

    return rapport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executer", action="store_true",
                        help="Sans ce drapeau : aucun appel réseau, affiche seulement le plan.")
    args = parser.parse_args()

    print("Plan (budget strict) : 1x /v4/markets (catalogue OddsPapi, une fois) + "
          f"{len(MATCHS)}x OddsPapi /v4/odds + {len(MATCHS)}x API-Football /odds = "
          f"{1 + 2 * len(MATCHS)} appels réels MAXIMUM. Aucun retry automatique.")
    for m in MATCHS:
        print(f"   - [{m['championnat']}] {m['domicile']} vs {m['exterieur']} "
              f"(OddsPapi={m['fixture_id_oddspapi']}, API-Football={m['fixture_id_api_football']})")

    if not args.executer:
        print("\nAucun appel effectué (relancer avec --executer après autorisation explicite).")
        return
    executer()


if __name__ == "__main__":
    main()
