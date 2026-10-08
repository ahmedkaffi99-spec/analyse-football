"""Mode SHADOW (demande explicite du 10/10/2026) : calcule les 3 coupons (bet_agent seul,
moteur seul, moteur central) à partir des MÊMES candidats, sans jamais rien envoyer ni modifier
le coupon Telegram réel — purement fonctionnel, indépendant de toute base de données ; c'est
backend/app/services/decision_centrale.py qui fournit les candidats réels (hist_cotes,
comparaison_moteurs) et journalise le résultat."""

from moteur_central.selection import selectionner


def construire_pool_central(candidats_moteur, candidats_bet_agent, choix_par_marche):
    """Pour CHAQUE marché, ne garde que les candidats du moteur jugé le plus fiable sur ce
    marché (choix_moteur.choisir_par_marche) ; garde LES DEUX moteurs quand la décision est
    "egalite"/"indisponible" (jamais un choix arbitraire sans donnée suffisante)."""
    pool = []
    choix_par_marche = choix_par_marche or {}
    for c in candidats_moteur + candidats_bet_agent:
        decision = choix_par_marche.get(c.marche, {}).get("decision", "indisponible")
        if decision in ("indisponible", "egalite") or decision == c.moteur_responsable:
            pool.append(c)
    return pool


def calculer_shadow(candidats_moteur, candidats_bet_agent, choix_par_marche, cote_min, cote_max):
    """Renvoie {"bet_agent": combo, "moteur": combo, "central": combo, "pool_central_taille": int}
    — chaque combo au format moteur_central.selection.selectionner()."""
    pool_central = construire_pool_central(candidats_moteur, candidats_bet_agent, choix_par_marche)
    return {
        "bet_agent": selectionner(candidats_bet_agent, cote_min, cote_max),
        "moteur": selectionner(candidats_moteur, cote_min, cote_max),
        "central": selectionner(pool_central, cote_min, cote_max),
        "pool_central_taille": len(pool_central),
    }
