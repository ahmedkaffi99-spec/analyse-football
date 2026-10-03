"""Cotes : probabilité implicite, retrait de la marge du bookmaker, edge.

Edge = probabilité_modèle × cote − 1 (marché binaire). Marché avec remboursement/quart :
edge = espérance de gain par unité misée (modeles.marches.esperance), identique sur un marché
binaire. Un edge positif ne suffit JAMAIS à retenir un pari : voir selection.filtrer.
"""


def proba_implicite(cote):
    return 1 / cote if cote and cote > 1 else None


def sans_marge(cotes_marche):
    """{selection: cote} d'un même marché complet -> {selection: proba sans marge}
    (normalisation multiplicative). Marché incomplet : None (impossible d'estimer la marge)."""
    implicites = {s: proba_implicite(c) for s, c in cotes_marche.items()}
    if len(implicites) < 2 or any(v is None for v in implicites.values()):
        return None
    total = sum(implicites.values())
    return {s: v / total for s, v in implicites.items()}


def marge(cotes_marche):
    implicites = [proba_implicite(c) for c in cotes_marche.values()]
    return sum(implicites) - 1 if implicites and None not in implicites else None


def edge(probabilite, cote):
    return probabilite * cote - 1
