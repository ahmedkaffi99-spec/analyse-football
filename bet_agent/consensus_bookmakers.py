"""Consensus de probabilités entre bookmakers (demande du 26/10/2026 : collecter les cotes des 10 meilleurs
bookmakers). Pour chaque sélection, la cote de chaque bookmaker est ramenée à une probabilité SANS MARGE
(normalisation du marché complet), puis moyennée avec un poids plus fort pour Pinnacle (référence du marché).
Calcul pur : aucun réseau ; n'influence PAS la sélection des coupons (information seulement)."""

import os

POIDS_BOOKMAKER = {"Pinnacle": 3.0}   # tous les autres : 1.0
BOOKMAKERS_EXCLUS = {"Dafabet"}       # n'a servi qu'un marché sur le diagnostic du 26/10/2026
NB_BOOKMAKERS_MIN = 3


def probas_sans_marge(marche):
    """{selection: proba sans marge} d'un marché complet d'un bookmaker, ou None s'il manque des cotes."""
    cotes = {s["selection"]: s["cote"] for s in marche.get("selections", []) if s.get("cote") and s["cote"] > 1.0}
    if len(cotes) < 2:
        return None
    somme = sum(1 / c for c in cotes.values())
    return {sel: (1 / c) / somme for sel, c in cotes.items()}


def consensus(cotes_bookmakers, nom_reference="1xBet"):
    """cotes_bookmakers : {bookmaker: [marché au format OddsPapi]}. Renvoie
    {(marche, handicap, selection): {"proba_pct", "nb_bookmakers", "proba_ref_pct", "ecart_pts"}}.
    Un marché à une seule issue (ou incomplet) est ignoré ; moins de NB_BOOKMAKERS_MIN bookmakers -> ignoré.
    ecart_pts = consensus - proba sans marge du bookmaker de référence (positif : la référence sous-estime)."""
    par_cle = {}   # (marche, handicap) -> {bookmaker: {selection: proba}}
    for bm, marches in cotes_bookmakers.items():
        if bm in BOOKMAKERS_EXCLUS:
            continue
        for m in marches:
            p = probas_sans_marge(m)
            if p:
                par_cle.setdefault((m["marche"], m.get("handicap")), {})[bm] = p
    sortie = {}
    for (marche, handicap), par_bm in par_cle.items():
        if len(par_bm) < NB_BOOKMAKERS_MIN:
            continue
        selections = set.intersection(*(set(p) for p in par_bm.values()))
        for sel in selections:
            poids = {bm: POIDS_BOOKMAKER.get(bm, 1.0) for bm in par_bm}
            proba = sum(poids[bm] * par_bm[bm][sel] for bm in par_bm) / sum(poids.values())
            ref = par_bm.get(nom_reference, {}).get(sel)
            sortie[(marche, handicap, sel)] = {
                "proba_pct": round(100 * proba, 2), "nb_bookmakers": len(par_bm),
                "proba_ref_pct": round(100 * ref, 2) if ref is not None else None,
                "ecart_pts": round(100 * (proba - ref), 2) if ref is not None else None}
    return sortie


SEUIL_GARDE_FOU_PTS = float(os.getenv("SEUIL_GARDE_FOU_CONSENSUS_PTS") or "4")


def annoter_candidats(candidats, cotes_bookmakers):
    """Ajoute à chaque pick dont le marché est couvert par ≥ NB_BOOKMAKERS_MIN bookmakers :
    consensus_pct, consensus_nb_bookmakers et ecart_consensus_pts (consensus - proba sans marge de 1xBet ;
    négatif = 1xBet est plus optimiste que le marché). Un pick non couvert n'est pas modifié. Renvoie le
    nombre de picks annotés."""
    if not cotes_bookmakers:
        return 0
    cons = consensus(cotes_bookmakers)
    nb = 0
    for c in candidats:
        v = cons.get((c.get("marche_brut"), c.get("handicap"), c.get("selection")))
        if v and v["ecart_pts"] is not None:
            c["consensus_pct"] = v["proba_pct"]
            c["consensus_nb_bookmakers"] = v["nb_bookmakers"]
            c["ecart_consensus_pts"] = v["ecart_pts"]
            nb += 1
    return nb


def garde_fou(pick):
    """Raison du veto si 1xBet est plus optimiste que le consensus d'au moins SEUIL_GARDE_FOU_PTS points
    (cote probablement erronée ou ligne mal alignée), sinon None. Ne s'applique qu'aux picks annotés."""
    ecart = pick.get("ecart_consensus_pts")
    if ecart is not None and ecart <= -SEUIL_GARDE_FOU_PTS:
        return (f"cote 1xBet trop favorable face au consensus des bookmakers ({ecart:+g} pts, "
                f"{pick.get('consensus_nb_bookmakers')} bookmakers)")
    return None
