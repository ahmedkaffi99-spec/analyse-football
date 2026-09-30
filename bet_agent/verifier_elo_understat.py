"""Test manuel, isolé (pas de collecte complète) : vérifie juste si ClubElo et Understat
répondent en ce moment pour quelques grands clubs connus. Beaucoup plus rapide qu'un run
complet — utile pour vérifier un correctif sans attendre 10+ minutes de collecte.
Usage : python verifier_elo_understat.py

Nommé volontairement SANS le préfixe test_ : ce n'est pas un test unitaire (aucune classe
unittest.TestCase) mais un script qui fait de VRAIS appels réseau — le préfixe test_ le
ferait exécuter par erreur à l'import par `unittest discover`, déclenchant ces appels
réseau pendant la suite de tests hors-ligne (constaté le 30/09/2026 : timeout de la suite
complète, appels réels à clubelo.com/understat.com bloqués par le proxy sandbox)."""
import collecte_donnees as cd

EQUIPES = ["Real Madrid", "Arsenal", "Bayern Munich", "Liverpool", "Paris Saint-Germain"]

if __name__ == "__main__":
    print("=== ClubElo ===")
    for e in EQUIPES:
        r = cd.trouver_elo(e)
        print(f"{e} : {r}")

    print("\n=== Understat ===")
    for e in EQUIPES:
        r = cd.trouver_stats_understat(e)
        print(f"{e} : {r}")
