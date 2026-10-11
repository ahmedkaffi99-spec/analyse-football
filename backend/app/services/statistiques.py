"""Bilan des performances : taux de réussite et rendement (mise fictive de 1 unité par
coupon) par profil, et taux de réussite par type de pari."""

from collections import defaultdict

from sqlalchemy import select

from app.models import Coupon, Jambe


def gain_coupon(coupon):
    """Gain net pour 1 unité misée. Une jambe remboursée (push) OU annulée (annule : match
    reporté/annulé/abandonné, correctif du 10/10/2026) compte pour une cote de 1 — dans les
    deux cas, aucune cote réelle n'a été jouée sur cette jambe, jamais incluse dans le produit
    des cotes du combiné."""
    if coupon.statut == "perdu":
        return -1.0
    if coupon.statut == "gagne":
        cote = 1.0
        for j in coupon.jambes:
            if j.resultat not in ("push", "annule"):
                cote *= j.cote
        return cote - 1.0
    return None


def calculer(db):
    coupons = list(db.scalars(select(Coupon)))
    par_profil = defaultdict(lambda: {"coupons": 0, "clos": 0, "gagnes": 0, "gain_net": 0.0})
    for c in coupons:
        p = par_profil[c.profil]
        p["nom"] = c.nom
        p["coupons"] += 1
        gain = gain_coupon(c)
        if gain is not None:
            p["clos"] += 1
            p["gagnes"] += c.statut == "gagne"
            p["gain_net"] += gain

    profils = []
    for cle, p in sorted(par_profil.items()):
        clos = p["clos"]
        profils.append({
            "profil": cle, "nom": p["nom"], "coupons": p["coupons"], "clos": clos, "gagnes": p["gagnes"],
            "taux_reussite_pct": round(100 * p["gagnes"] / clos, 1) if clos else None,
            "gain_net_unites": round(p["gain_net"], 2),
            "rendement_pct": round(100 * p["gain_net"] / clos, 1) if clos else None,
        })

    par_categorie = defaultdict(lambda: {"jugees": 0, "gagnees": 0})
    for j in db.scalars(select(Jambe).where(Jambe.resultat.in_(("gagne", "perdu")))):
        par_categorie[j.categorie]["jugees"] += 1
        par_categorie[j.categorie]["gagnees"] += j.resultat == "gagne"
    categories = [
        {"categorie": cat, **v, "taux_reussite_pct": round(100 * v["gagnees"] / v["jugees"], 1)}
        for cat, v in sorted(par_categorie.items())
    ]
    return {"profils": profils, "categories": categories}


def resume_pour_ia(db, min_jugees=3, max_categories_faibles=6):
    """Résumé textuel court du bilan réel (coupons + catégories), injecté dans la mission de
    l'agent pilote (bet_agent/agent_pilote.py) — demande explicite de l'utilisateur (01/10/2026)
    : "l'IA doit se souvenir du contexte" (des runs précédents, pas seulement du catalogue du
    jour) pour augmenter les chances de gain, pas seulement composer pour atteindre une cote
    cible. Renvoie None si aucun coupon n'est encore clos (rien à résumer)."""
    bilan = calculer(db)
    clos_total = sum(p["clos"] for p in bilan["profils"])
    if not clos_total:
        return None
    gagnes_total = sum(p["gagnes"] for p in bilan["profils"])
    lignes = [f"BILAN RÉEL DES COUPONS PRÉCÉDENTS (à prendre en compte pour mieux choisir aujourd'hui) : "
              f"{gagnes_total}/{clos_total} coupon(s) combiné(s) gagné(s) au total."]
    # Catégories avec un échantillon suffisant (min_jugees) ET un taux de réussite faible
    # (<50%) — celles que l'IA doit éviter d'empiler sans une raison solide aujourd'hui.
    faibles = sorted((c for c in bilan["categories"] if c["jugees"] >= min_jugees and c["taux_reussite_pct"] < 50),
                     key=lambda c: c["taux_reussite_pct"])[:max_categories_faibles]
    if faibles:
        detail = ", ".join(f"{c['categorie']} ({c['gagnees']}/{c['jugees']})" for c in faibles)
        lignes.append(f"Catégories de marché avec un taux de réussite réel FAIBLE jusqu'ici : {detail} — "
                      "méfie-toi d'en empiler plusieurs dans un même coupon aujourd'hui, sauf analyse solide "
                      "propre à CE match qui justifie de le reprendre.")
    forts = sorted((c for c in bilan["categories"] if c["jugees"] >= min_jugees and c["taux_reussite_pct"] >= 70),
                   key=lambda c: -c["taux_reussite_pct"])[:max_categories_faibles]
    if forts:
        detail = ", ".join(f"{c['categorie']} ({c['gagnees']}/{c['jugees']})" for c in forts)
        lignes.append(f"Catégories avec un taux de réussite réel SOLIDE jusqu'ici : {detail}.")
    return "\n".join(lignes)
