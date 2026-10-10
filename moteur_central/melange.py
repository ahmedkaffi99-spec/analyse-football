"""Mélange probabilité-modèle / probabilité-marché — extrait tel quel (même formule, aucune
sémantique nouvelle) de bet_agent/analyser_et_envoyer.py:evaluer_marches_toutes (lignes
833-848), qui reste le moteur de référence INCHANGÉ. Ce module ne le remplace pas : il prépare
la convergence vers moteur_central/ en rendant cette formule réutilisable et testable hors du
contexte complet d'un marché OddsPapi (Phase B, lot 1 — demande explicite du 10/10/2026).

Fidélité vérifiée par test de non-régression (voir tests/test_melange.py) contre la vraie
sortie de evaluer_marches_toutes() sur les 40 cas synthétiques de
bet_agent/cas_synthetiques_demo.py, à POIDS_MARCHE=0.65 (la valeur réelle de production,
jamais modifiée ici)."""


def combiner_proba(p_modele, p_marche, poids):
    """p = (1 - poids) * p_modele + poids * p_marche — IDENTIQUE à la ligne
    analyser_et_envoyer.py:844, jamais réécrite ni simplifiée.

    - p_modele, p_marche : probabilités déjà calculées par l'appelant. AUCUNE des deux ne peut
      être None ici — en production, un candidat sans probabilité de marché calculable
      (une seule sélection cotée) est écarté AVANT d'atteindre ce mélange (voir
      evaluer_marches_toutes:838-841, `if p_marche is None: continue`), jamais remplacé par
      une valeur par défaut. Reproduire cette même règle : lève ValueError plutôt que de
      deviner une valeur, pour ne jamais introduire une sémantique absente de la référence.
    - poids : attendu dans [0, 1] par convention (POIDS_MARCHE=0.65 en production), mais
      AUCUNE validation ni clamp n'est appliquée ici — la référence elle-même n'en fait pas
      (poids est une constante module-level, jamais un paramètre contrôlé à l'exécution).
    - AUCUNE normalisation ni plafonnement du résultat à [0, 1] : la référence n'en fait pas
      non plus. Pour les marchés Double Chance, p_marche peut légitimement dépasser 1.0 (la
      somme des 3 sélections qui se recouvrent vise 2.0, pas 1.0 — voir
      analyser_et_envoyer.py:probabilites_sans_marge) ; le résultat du mélange peut donc, par
      construction de la référence, lui aussi dépasser 1.0 pour ce marché. Ne jamais corriger
      ce comportement silencieusement ici : il appartient à la référence, pas à ce module."""
    if p_modele is None or p_marche is None:
        raise ValueError(
            "combiner_proba ne devine jamais une probabilité manquante — l'appelant doit "
            "écarter le candidat avant d'appeler cette fonction (même règle que "
            "evaluer_marches_toutes : `if p_marche is None: continue`)")
    return (1 - poids) * p_modele + poids * p_marche
