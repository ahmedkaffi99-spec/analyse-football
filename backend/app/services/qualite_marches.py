"""Qualité RÉELLE de chaque marché, mesurée sur les paris déjà jugés en base (table jambes,
resultat gagne/perdu) — donne à l'IA de vrais chiffres mesurés (taux de réussite réel, edge réel
moyen) pour qu'elle juge elle-même la fiabilité d'un marché par son raisonnement, plutôt qu'une
liste de marchés bannis codée en dur en Python (voir bet_agent.analyser_et_envoyer.
agent35_validation_ia). Un marché mal mesuré ici reste simplement absent du dict renvoyé : on
ne calcule jamais un taux sur trop peu de données (SEUIL_N_MIN)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Coupon, Jambe, Run

SEUIL_N_MIN = 8
FENETRE_JOURS = 60


def qualite_marches(db, fenetre_jours=FENETRE_JOURS, seuil_n_min=SEUIL_N_MIN):
    """{marche: {"n": int, "taux_reussite_pct": float, "edge_moyen_pct": float|None}} — une
    entrée par valeur EXACTE de jambes.marche (déjà "nom + ligne", identique à la clé utilisée
    dans le pool de candidats), uniquement pour les marchés ayant au moins seuil_n_min paris
    gagné/perdu (push et non_verifiable ignorés : ni un succès ni un échec du marché)."""
    limite = datetime.now(timezone.utc) - timedelta(days=fenetre_jours)
    lignes = db.execute(
        select(Jambe.marche, Jambe.resultat, Jambe.edge_pct)
        .join(Coupon, Coupon.id == Jambe.coupon_id)
        .join(Run, Run.id == Coupon.run_id)
        .where(Jambe.resultat.in_(("gagne", "perdu")), Run.lance_le >= limite)
    ).all()

    par_marche = {}
    for marche, resultat, edge_pct in lignes:
        agg = par_marche.setdefault(marche, {"n": 0, "gagnes": 0, "edges": []})
        agg["n"] += 1
        agg["gagnes"] += resultat == "gagne"
        if edge_pct is not None:
            agg["edges"].append(edge_pct)

    return {
        marche: {
            "n": agg["n"],
            "taux_reussite_pct": round(100 * agg["gagnes"] / agg["n"], 1),
            "edge_moyen_pct": round(sum(agg["edges"]) / len(agg["edges"]), 1) if agg["edges"] else None,
        }
        for marche, agg in par_marche.items() if agg["n"] >= seuil_n_min
    }
