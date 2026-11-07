"""Moteur DÉTERMINISTE (07/11/2026) : trois coupons PRUDENT / ÉQUILIBRÉ / RISQUE composés par des RÈGLES Python, sans IA et sans cote cible.

Même catalogue, mêmes données et mêmes règles de cohérence que les autres moteurs (moteur/profils_risque.py). Algorithme :
  1. candidats = jambes du pool avec probabilité et cote valides (rien n'est inventé), classées selon l'utilité du profil ;
  2. répartition des matchs entre les profils par TOURS (prudent, équilibré, risque, puis on recommence) : chaque profil prend son meilleur match libre, avec
     la contrainte de diversité (famille et sens) ; un match ne figure que dans UN coupon ;
  3. taille de référence par profil (prudent 3, équilibré 4, risque 5 jambes), ramenée au nombre de matchs disponibles, jamais sous 2 ;
  4. chaque coupon final passe `regles_coupon` ; un profil qui ne peut pas être composé s'abstient (aucun coupon forcé).
Aucune cote totale ni individuelle n'est ciblée. Les utilités sont des heuristiques documentées, pas des résultats validés."""
import math
import os
import sys

_RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)

from moteur import profils_risque as pr  # noqa: E402


def jambes_du_pool(pool):
    """Pool de bet_agent {match: [candidat]} -> liste de jambes normalisées (avec le candidat d'origine dans `_c`). Les candidats sans probabilité ou sans cote valide sont écartés."""
    jambes = []
    for match, candidats in pool.items():
        for c in candidats or []:
            pick = c.get("pick") or {}
            proba = pick.get("proba_modele_pct")
            j = {"match": c.get("match") or match, "competition": c.get("competition"), "categorie": pick.get("categorie"),
                 "selection": pick.get("selection"), "p": None if proba is None else proba / 100.0, "cote": pick.get("cote"), "_c": c}
            if pr.valider_jambe(j) is None:
                jambes.append(j)
    return jambes


def composer(pool, profils, taille_reference=None):
    """-> liste [{"profil": profil, "selections": [candidats du pool], "abstention": raison|None}] dans l'ordre de `profils` (même forme que les autres moteurs)."""
    taille_reference = taille_reference or pr.TAILLE_REFERENCE
    jambes = jambes_du_pool(pool)
    niveaux = [p.get("niveau_risque") or "prudent" for p in profils]
    choisies = {i: [] for i in range(len(profils))}
    utilises = set()
    cibles = [taille_reference.get(n, 3) for n in niveaux]
    # Tours de répartition : chaque profil prend à son tour sa meilleure jambe libre (un match = un seul coupon).
    progres = True
    while progres:
        progres = False
        for i, niveau in enumerate(niveaux):
            if len(choisies[i]) >= cibles[i]:
                continue
            libres = [j for j in jambes if j["match"] not in utilises]
            if not libres:
                continue
            # Toutes les jambes des matchs libres, de la plus à la moins utile : si la meilleure jambe d'un match rompt la diversité (famille et sens),
            # une autre jambe du même match ou un autre match est essayé. Un seul pari par match reste garanti par `utilises`.
            candidates = sorted(((pr.utilite_jambe(niveau, j), j) for j in libres), key=lambda x: x[0], reverse=True)
            for u, j in candidates:
                if pr.diversite_ok(choisies[i] + [j]) or len(choisies[i]) < 2:
                    choisies[i].append(j)
                    utilises.add(j["match"])
                    progres = True
                    break
    resultats = []
    for i, profil in enumerate(profils):
        legs = choisies[i]
        problemes = pr.regles_coupon(legs, niveaux[i]) if legs else ["aucune jambe disponible"]
        if problemes:
            resultats.append({"profil": profil, "selections": [], "abstention": "moteur déterministe : " + " ; ".join(problemes)})
        else:
            resultats.append({"profil": profil, "selections": [j["_c"] for j in legs],
                              "strategie": f"déterministe {niveaux[i]} : {len(legs)} jambes, probabilité jointe {pr.proba_jointe(legs):.3f}, cote {pr.cote_totale(legs):.2f}"})
    # Dernier filet commun : cohérence ENTRE coupons (un match dans un seul coupon, coupons distincts).
    erreurs = pr.regles_entre_coupons([[j for j in choisies[i]] for i, r in enumerate(resultats) if r["selections"]])
    if erreurs:
        raise ValueError("moteur déterministe : incohérence entre coupons — " + " ; ".join(erreurs))
    return resultats
