"""Qualité RÉELLE de chaque marché, mesurée sur les paris déjà jugés en base (table jambes,
resultat gagne/perdu) — donne à l'IA de vrais chiffres mesurés (taux de réussite réel, edge réel
moyen) pour qu'elle juge elle-même la fiabilité d'un marché par son raisonnement, plutôt qu'une
liste de marchés bannis codée en dur en Python (voir bet_agent.analyser_et_envoyer.
agent35_validation_ia). Un marché mal mesuré ici reste simplement absent du dict renvoyé : on
ne calcule jamais un taux sur trop peu de données (SEUIL_N_MIN).

18/10/2026, bug confirmé en base (audit Agent 2, "Buts Total") : le cron horaire relance le
pipeline tant qu'aucun coupon n'est parti sur Telegram (ticket_deja_produit_aujourdhui) —
chaque tentative, même jamais envoyée, persiste quand même un run/coupon/jambes complet. Une
seule vraie cote perdue (fixture réelle, un seul "Over 3.5" joué) s'est ainsi retrouvée comptée
9 FOIS dans jambes (4 tentatives le 15/10, 5 le 16/10, toutes envoye_telegram=False) — faussant
le taux de réussite "Over" mesuré de -15,4 points (46,0% apparent contre 61,9% réel une fois
dédupliqué par match). Filtrer sur Run.envoye_telegram (seuls les coupons RÉELLEMENT livrés)
élimine cette pollution à la source, sans dédupliquer artificiellement (une tentative jamais
envoyée n'a jamais pu influencer un vrai résultat mesuré)."""

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
        .where(Jambe.resultat.in_(("gagne", "perdu")), Run.lance_le >= limite,
               Run.envoye_telegram.is_(True))
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
