"""Moteur CENTRAL — trois profils de risque (prudent, équilibré, risque), sans cote cible (07/11/2026).

Différence de méthode avec le moteur déterministe : recherche EXHAUSTIVE des combinaisons (2 à TAILLE_MAX jambes) parmi les meilleures jambes du profil, optimisant
l'utilité du COUPON ENTIER (probabilité jointe avec correction de corrélation × cote totale, pondérées selon le profil) au lieu d'un choix jambe par jambe.
Probabilité utilisée : la probabilité CALIBRÉE si elle existe, sinon la brute, atténuée vers 0,5 quand l'historique réel du marché est mal calibré
(Brier mesuré > 0,25) — un marché dont le Brier historique est mauvais ne donne pas une confiance entière. Atténuation plafonnée à 20 % ; heuristique à valider par
backtest (moteur/evaluation.py), jamais présentée comme prouvée.

Mêmes règles de cohérence que les autres moteurs (moteur/profils_risque.py) : un pari par match, deux jambes minimum, diversité famille/sens, un match dans un seul
coupon, aucun coupon identique. Une probabilité ou une cote absente écarte le candidat (jamais inventée)."""
import itertools

from moteur import profils_risque as pr

TAILLE_POOL = 16
BRIER_NEUTRE = 0.25      # Brier d'une prévision constante à 0,5 : au-delà, l'historique du marché n'apporte pas d'information


def proba_effective(c):
    """Probabilité (0-1) utilisée par le moteur central pour un CandidatCentral, ou None si aucune probabilité exploitable."""
    brute = c.proba_calibree_pct if c.proba_calibree_pct else c.proba_pct
    if not brute:
        return None
    p = brute / 100.0
    hist = c.historique_marche
    if hist and hist.get("disponible") and hist.get("brier") is not None and hist["brier"] > BRIER_NEUTRE:
        attenuation = min(0.2, (hist["brier"] - BRIER_NEUTRE) * 2)
        p = 0.5 + (p - 0.5) * (1.0 - attenuation)
    return p


def vers_jambes(pool):
    """CandidatCentral -> jambes normalisées ; les candidats sans probabilité ou cote valides sont écartés."""
    jambes = []
    for c in pool:
        j = {"match": c.match, "competition": c.competition, "categorie": c.categorie, "selection": c.selection,
             "p": proba_effective(c), "cote": c.cote, "_c": c}
        if pr.valider_jambe(j) is None:
            jambes.append(j)
    return jambes


def meilleure_combinaison(jambes, niveau, taille_pool=TAILLE_POOL):
    """Combinaison d'utilité maximale (recherche exhaustive sur les `taille_pool` meilleures jambes du profil). None si aucune combinaison cohérente."""
    candidats = sorted(jambes, key=lambda j: pr.utilite_jambe(niveau, j), reverse=True)[:taille_pool]
    meilleure, meilleur_score = None, float("-inf")
    for taille in range(pr.NB_JAMBES_MIN, min(pr.TAILLE_MAX[niveau], len(candidats)) + 1):
        for combo in itertools.combinations(candidats, taille):
            if len({j["match"] for j in combo}) != taille:
                continue
            if pr.regles_coupon(list(combo), niveau):
                continue
            score = pr.utilite_coupon(niveau, combo)
            if score > meilleur_score:
                meilleure, meilleur_score = list(combo), score
    return meilleure


def selectionner_profils(pool, profils, taille_pool=TAILLE_POOL):
    """pool : CandidatCentral déjà filtrés par l'appelant. -> [{"profil", "jambes": [CandidatCentral], "cote_totale", "proba_jointe", "raison"}] dans l'ordre de `profils`.
    Les profils sont traités dans l'ordre donné ; les matchs d'un coupon sont retirés pour les suivants (un match dans un seul coupon)."""
    jambes = vers_jambes(pool)
    utilises, sortie, coupons = set(), [], []
    for profil in profils:
        niveau = profil.get("niveau_risque") or "prudent"
        libres = [j for j in jambes if j["match"] not in utilises]
        combo = meilleure_combinaison(libres, niveau, taille_pool) if len(libres) >= pr.NB_JAMBES_MIN else None
        if combo is None:
            sortie.append({"profil": profil, "jambes": [], "cote_totale": None, "proba_jointe": None,
                           "raison": f"moteur central : aucune combinaison cohérente pour le profil {niveau} ({len(libres)} jambe(s) libre(s))"})
            continue
        utilises.update(j["match"] for j in combo)
        coupons.append(combo)
        sortie.append({"profil": profil, "jambes": [j["_c"] for j in combo], "cote_totale": round(pr.cote_totale(combo), 3),
                       "proba_jointe": round(pr.proba_jointe(combo), 4), "raison": None})
    erreurs = pr.regles_entre_coupons(coupons)
    if erreurs:
        raise ValueError("moteur central : incohérence entre coupons — " + " ; ".join(erreurs))
    return sortie
