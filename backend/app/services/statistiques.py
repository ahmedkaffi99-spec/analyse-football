"""Bilan des performances : taux de réussite et rendement (mise fictive de 1 unité par
coupon) par profil, et taux de réussite par type de pari."""

from collections import defaultdict

from sqlalchemy import select

from app.models import Coupon, Jambe


def gain_coupon(coupon):
    """Gain net pour 1 unité misée. Une jambe remboursée (push) compte pour une cote de 1."""
    if coupon.statut == "perdu":
        return -1.0
    if coupon.statut == "gagne":
        cote = 1.0
        for j in coupon.jambes:
            if j.resultat != "push":
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
