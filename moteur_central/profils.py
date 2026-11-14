"""Moteur CENTRAL — trois profils de risque (prudent, équilibré, risque), sans cote cible (07/11/2026).

Différence de méthode avec le moteur déterministe : recherche des combinaisons (taille et bande de cote du profil) par construction gloutonne puis échanges de jambes, optimisant
l'utilité du COUPON ENTIER (probabilité jointe avec correction de corrélation × cote totale, pondérées selon le profil) au lieu d'un choix jambe par jambe.
Probabilité utilisée : la probabilité CALIBRÉE si elle existe, sinon la brute, atténuée vers 0,5 quand l'historique réel du marché est mal calibré
(Brier mesuré > 0,25) — un marché dont le Brier historique est mauvais ne donne pas une confiance entière. Atténuation plafonnée à 20 % ; heuristique à valider par
backtest (moteur/evaluation.py), jamais présentée comme prouvée.

Mêmes règles de cohérence que les autres moteurs (moteur/profils_risque.py) : un pari par match, deux jambes minimum, diversité famille/sens, un match dans un seul
coupon, aucun coupon identique. Une probabilité ou une cote absente écarte le candidat (jamais inventée)."""
import math

from moteur import profils_risque as pr

TAILLE_POOL = 16
POIDS_EQUILIBRE = 1.0     # poids du malus de déséquilibre taille / cote dans l'objectif (heuristique, à valider par backtest)
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


def _ecart_bande(combo, profil):
    """Distance logarithmique de la cote totale à la bande du profil (0 si dans la bande ou sans bande)."""
    cote = pr.cote_totale(combo)
    bas, haut = profil.get("cote_totale_min"), profil.get("cote_totale_max")
    if cote <= 0:
        return float("inf")
    if bas and cote < bas:
        return math.log(bas / cote)
    if haut and cote > haut:
        return math.log(cote / haut)
    return 0.0


def _objectif(niveau, combo, profil):
    # Équilibre nombre de jambes / cote moyenne par jambe (demande du 07/11/2026) : léger malus pour un coupon qui n'est haut que d'un côté.
    return pr.utilite_coupon(niveau, combo) - 10.0 * _ecart_bande(combo, profil) - POIDS_EQUILIBRE * pr.desequilibre(combo, profil)


def _sans_doublon(combo):
    return len({j["match"] for j in combo}) == len(combo)


def meilleure_combinaison(jambes, niveau, taille_pool=TAILLE_POOL, profil=None):
    """Combinaison d'utilité maximale respectant `regles_coupon` (nombre de jambes et bande de cote du profil compris), ou None si aucune n'est trouvée.

    Pour chaque taille autorisée : construction gloutonne (jambe la plus utile compatible avec un pari par match et la diversité famille/sens) puis amélioration
    par échanges (remplacer une jambe par une autre tant que l'objectif progresse). Une recherche exhaustive devient impossible à 5-12 jambes sur un catalogue
    de plusieurs dizaines de marchés ; ce parcours reste déterministe mais n'est PAS garanti optimal. `taille_pool` borne le nombre de jambes examinées."""
    profil = profil or {}
    candidats = sorted(jambes, key=lambda j: pr.utilite_jambe(niveau, j), reverse=True)[:max(taille_pool, 8) * 6]
    bas = profil.get("nb_jambes_min") or pr.NB_JAMBES_MIN
    haut = profil.get("nb_jambes") or pr.TAILLE_MAX[niveau]
    meilleure, meilleur_score = None, float("-inf")
    par_cote = sorted(candidats, key=lambda j: j["cote"], reverse=True)
    for taille in range(bas, min(haut, len({j["match"] for j in candidats})) + 1):
        # Deux points de départ (jambes les plus utiles, puis les mieux cotées) : la recherche locale ne reste pas bloquée hors de la bande de cote.
        for ordre in (candidats, par_cote):
            combo = []
            for j in ordre:
                if len(combo) == taille:
                    break
                if j["match"] not in {x["match"] for x in combo} and pr.combo_admissible(combo + [j], profil):
                    combo.append(j)
            if len(combo) < taille:
                continue
            score = _objectif(niveau, combo, profil)
            ameliore = True
            while ameliore:
                ameliore = False
                for i in range(len(combo)):
                    for j in candidats:
                        if j in combo:
                            continue
                        essai = combo[:i] + [j] + combo[i + 1:]
                        if not _sans_doublon(essai) or not pr.combo_admissible(essai, profil):
                            continue
                        s2 = _objectif(niveau, essai, profil)
                        if s2 > score + 1e-12:
                            combo, score, ameliore = essai, s2, True
            if pr.regles_coupon(combo, niveau, profil):
                continue
            if score > meilleur_score:
                meilleure, meilleur_score = list(combo), score
    return meilleure


def selectionner_profils(pool, profils, taille_pool=TAILLE_POOL):
    """pool : CandidatCentral déjà filtrés par l'appelant. -> [{"profil", "jambes": [CandidatCentral], "cote_totale", "proba_jointe", "raison"}] dans l'ordre de `profils`.
    Les profils sont traités dans l'ordre donné ; les matchs d'un coupon sont retirés pour les suivants (un match dans un seul coupon)."""
    jambes = vers_jambes(pool)
    utilises, sortie, coupons = set(), [], []
    repete = any(p.get("match_repete_autorise") for p in profils)   # 07/11/2026 : un match dans plusieurs coupons, jamais avec le même pari exact
    exacts = set()
    plafond = pr.plafond_coupons_par_match(profils) if repete else None
    par_match = {}
    for profil in profils:
        niveau = profil.get("niveau_risque") or "prudent"
        libres = [j for j in jambes if (pr.pari_exact(j) not in exacts and not (plafond and par_match.get(j["match"], 0) >= plafond)
                                        if repete else j["match"] not in utilises)]
        combo = (meilleure_combinaison(libres, niveau, taille_pool, profil)
                 if len({j["match"] for j in libres}) >= (profil.get("nb_jambes_min") or pr.NB_JAMBES_MIN) else None)
        if combo is None:
            sortie.append({"profil": profil, "jambes": [], "cote_totale": None, "proba_jointe": None,
                           "raison": f"moteur central : aucune combinaison cohérente pour le profil {niveau} ({len(libres)} jambe(s) libre(s))"})
            continue
        utilises.update(j["match"] for j in combo)
        exacts.update(pr.pari_exact(j) for j in combo)
        for m in {j["match"] for j in combo}:
            par_match[m] = par_match.get(m, 0) + 1
        coupons.append(combo)
        sortie.append({"profil": profil, "jambes": [j["_c"] for j in combo], "cote_totale": round(pr.cote_totale(combo), 3),
                       "proba_jointe": round(pr.proba_jointe(combo), 4), "raison": None})
    erreurs = pr.regles_entre_coupons(coupons, repete, plafond)
    if erreurs:
        raise ValueError("moteur central : incohérence entre coupons — " + " ; ".join(erreurs))
    return sortie
