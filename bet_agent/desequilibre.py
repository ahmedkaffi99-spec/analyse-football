"""Matchs déséquilibrés (bilan du 28/10/2026 : Bayern-Magdeburg 6-1 a fait tomber la plupart des coupons du jour ;
Monza-Napoli 1-4, Bournemouth-Aston Villa 3-0). Quand un favori est très net, les paris « peu de buts » et ceux qui
couvrent l'outsider cachent un risque de score fleuve que la probabilité Poisson sous-estime. Calcul pur."""
import os

SEUIL_DESEQUILIBRE_PCT = float(os.getenv("SEUIL_DESEQUILIBRE_PCT") or 70)


def favori(marches):
    """(côté, proba %) du favori d'après le 1X2 (probabilités sans marge), ou (None, None) si le 1X2 est absent."""
    for m in marches or []:
        if m.get("marche") != "Full Time Result":
            continue
        cotes = {s["selection"]: s["cote"] for s in m.get("selections", []) if s.get("cote") and s["cote"] > 1.0}
        if {"1", "X", "2"} <= set(cotes):
            somme = sum(1 / cotes[k] for k in ("1", "X", "2"))
            p1, p2 = (1 / cotes["1"]) / somme, (1 / cotes["2"]) / somme
            return ("1", round(100 * p1, 1)) if p1 >= p2 else ("2", round(100 * p2, 1))
    return None, None


def annoter_favori(candidats, marches):
    """Ajoute favori_cote ('1'/'2') et proba_favori_pct à chaque pick du match. Renvoie le nombre de picks annotés."""
    cote, proba = favori(marches)
    if cote is None:
        return 0
    for c in candidats:
        c["favori"], c["proba_favori_pct"] = cote, proba
    return len(candidats)


def veto(pick):
    """Raison du veto si le match est très déséquilibré (favori >= SEUIL_DESEQUILIBRE_PCT) et que le pari est :
    Under (total du match, ou total de l'équipe favorite), handicap sur l'outsider, ou double chance couvrant
    l'outsider. None sinon (pick non annoté, match équilibré, pari sans risque de score fleuve)."""
    proba, fav = pick.get("proba_favori_pct"), pick.get("favori")
    if proba is None or fav is None or proba < SEUIL_DESEQUILIBRE_PCT:
        return None
    cat, sel = pick.get("categorie"), str(pick.get("selection"))
    sel_norm = sel.replace(" ", "").upper()
    outsider = "2" if fav == "1" else "1"
    raison = None
    if cat == "Total" and sel.lower() == "under":
        raison = "moins de buts"
    elif cat == "Total Équipe " + fav and sel.lower() == "under":
        raison = "moins de buts du favori"
    elif cat in ("Handicap", "Handicap Asiatique", "Handicap Européen") and sel == outsider:
        raison = "handicap de l'outsider"
    elif cat == "Double Chance" and ((fav == "1" and sel_norm in ("X2", "2X")) or (fav == "2" and sel_norm == "1X")):
        raison = "double chance couvrant l'outsider"
    if raison:
        return (f"match déséquilibré (favori à {proba:g} % ≥ {SEUIL_DESEQUILIBRE_PCT:g} %) : {raison}, "
                "risque de score fleuve")
    return None
