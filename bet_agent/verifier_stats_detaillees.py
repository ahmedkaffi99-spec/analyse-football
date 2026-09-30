"""Test manuel, isolé (pas de collecte complète) : vérifie si l'endpoint API-Football
/fixtures/statistics répond bien et donne les 15 métriques (buts, corners, cartons, fautes,
tirs, possession, hors-jeux, passes, clean sheets, forme) sur quelques grands clubs connus,
sans dépendre d'OddsPapi/Serper/DeepSeek. Beaucoup plus rapide qu'un run complet, et permet de
vérifier l'état réel du compte API-Football (quota, plan, suspension) avant d'activer
STATS_DETAILLEES_ACTIVE en production.
Usage : python verifier_stats_detaillees.py

Nommé volontairement SANS le préfixe test_ (voir verifier_elo_understat.py) : ce n'est pas un
test unitaire mais un script qui fait de VRAIS appels réseau à API-Football."""
import collecte_donnees as cd

# IDs API-Football (v3.football.api-sports.io), stables et documentés.
EQUIPES = [
    (541, "Real Madrid"),
    (42, "Arsenal"),
    (157, "Bayern Munich"),
    (40, "Liverpool"),
    (85, "Paris Saint-Germain"),
]

if __name__ == "__main__":
    if not cd.API_FOOTBALL_KEY:
        print("❌ API_FOOTBALL_KEY absente de envi.local — impossible de tester.")
        raise SystemExit(1)

    print("=== API-Football : /fixtures/statistics (10 derniers matchs, 15 métriques) ===")
    reussites = 0
    for team_id, nom in EQUIPES:
        resultat = cd.recuperer_stats_10_derniers_matchs(team_id, nom)
        if resultat:
            reussites += 1
        else:
            print(f"{nom} : ÉCHEC (voir message ci-dessus)")
    print(f"\n{reussites}/{len(EQUIPES)} équipes avec stats détaillées complètes.")
