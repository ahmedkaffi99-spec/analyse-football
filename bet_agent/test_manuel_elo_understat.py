"""Test manuel, isolé (pas de collecte complète) : vérifie juste si ClubElo et Understat
répondent en ce moment pour quelques grands clubs connus. Beaucoup plus rapide qu'un run
complet — utile pour vérifier un correctif sans attendre 10+ minutes de collecte.
Usage : python test_manuel_elo_understat.py"""
import collecte_donnees as cd

EQUIPES = ["Real Madrid", "Arsenal", "Bayern Munich", "Liverpool", "Paris Saint-Germain"]

print("=== ClubElo ===")
for e in EQUIPES:
    r = cd.trouver_elo(e)
    print(f"{e} : {r}")

print("\n=== Understat ===")
for e in EQUIPES:
    r = cd.trouver_stats_understat(e)
    print(f"{e} : {r}")
