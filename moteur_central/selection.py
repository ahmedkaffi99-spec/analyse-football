"""Composition adaptative du coupon « probabilité maximale » à partir de candidats déjà
scorés (score_central) — 2 à 5 jambes, JAMAIS forcé à 5 (demande explicite : "si 2 jambes sont
meilleures que 5, prendre 2"). Une seule jambe par match : contrainte de diversité ET, de fait,
la seule garantie de corrélation que ce module peut donner aujourd'hui sans les paramètres
Poisson complets de chaque candidat (deux jambes du même match sont TOUJOURS potentiellement
corrélées, voir moteur/selection.py::correlation — ici elles sont simplement interdites plutôt
que mesurées, par prudence).

Recherche EXHAUSTIVE (itertools.combinations) : le pool central, déjà filtré par les seuils de
fiabilité de l'appelant, reste petit. Au-delà de cfg.taille_pool_max candidats, seuls les
meilleurs scores sont conservés avant la recherche (documenté, jamais silencieux) — sinon le
nombre de combinaisons explose (ex: 100 candidats, 5 jambes = 75 millions de combinaisons)."""

import itertools

from moteur_central.score_central import score_central

NB_JAMBES_MIN, NB_JAMBES_MAX, TAILLE_POOL_MAX = 2, 5, 25


def _score_combo(combo):
    scores = [score_central(c)[0] for c in combo]
    cote = 1.0
    for c in combo:
        cote *= c.cote
    return scores, cote


def _diversite_ok(combo):
    matchs = [c.match for c in combo]
    return len(matchs) == len(set(matchs))  # une seule jambe par match


def selectionner(pool, cote_min, cote_max, nb_min=NB_JAMBES_MIN, nb_max=NB_JAMBES_MAX,
                 taille_pool_max=TAILLE_POOL_MAX):
    """pool : [CandidatCentral, ...] déjà filtré par l'appelant (fiabilité minimale). Essaie
    TOUTES les tailles nb_min..nb_max, jamais seulement la plus grande possible — le meilleur
    score moyen l'emporte parmi les combinaisons qui respectent la cote cible ; à défaut, la
    combinaison la plus proche de la cible."""
    if len(pool) < nb_min:
        return {"genere": False, "jambes": [],
                "raison": f"seulement {len(pool)} candidat(s) fiable(s) disponibles, minimum {nb_min}",
                "cote_totale": None, "score_moyen": None, "nb_jambes": 0}

    pool_reduit = sorted(pool, key=lambda c: score_central(c)[0], reverse=True)[:taille_pool_max]

    meilleur, meilleure_cle = None, None
    cible = (cote_min + cote_max) / 2
    for taille in range(nb_min, min(nb_max, len(pool_reduit)) + 1):
        for combo in itertools.combinations(pool_reduit, taille):
            if not _diversite_ok(combo):
                continue
            scores, cote = _score_combo(combo)
            dans_cible = cote_min <= cote <= cote_max
            cle = (dans_cible, -abs(cote - cible) if not dans_cible else 0.0, sum(scores) / len(scores))
            if meilleure_cle is None or cle > meilleure_cle:
                meilleur, meilleure_cle = combo, cle

    if meilleur is None:
        return {"genere": False, "jambes": [], "raison": "aucune combinaison valide (contrainte de diversité)",
                "cote_totale": None, "score_moyen": None, "nb_jambes": 0}

    scores, cote = _score_combo(meilleur)
    return {"genere": True, "jambes": list(meilleur), "cote_totale": round(cote, 3),
            "score_moyen": round(sum(scores) / len(scores), 4), "nb_jambes": len(meilleur), "raison": None}
