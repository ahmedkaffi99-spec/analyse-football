"""Base COMMUNE des trois moteurs (agent, central, déterministe) pour les trois profils de risque : prudent, équilibré, risque (07/11/2026).

Code pur (aucun réseau, aucune base). Il fournit : les règles de cohérence d'un coupon appliquées de la même façon par les trois moteurs (un pari par match,
deux jambes minimum, diversité des familles et des sens), un correctif de corrélation approché, la probabilité jointe et les fonctions d'utilité par profil.

AUCUNE cote totale ni cote individuelle n'est imposée. Les utilités ci-dessous sont des heuristiques de décision documentées, PAS des résultats validés :
leur valeur sera jugée sur des résultats réglés (voir moteur/evaluation.py) et jamais affirmée meilleure d'avance.

Une « jambe » est un dict : {"match", "competition", "categorie", "selection", "p" (0-1), "cote" (>1)} ; une jambe sans probabilité ou sans cote valide est
refusée (rien n'est inventé)."""

import math
import os


def _lire(nom, defaut):
    try:
        return max(0.0, float(os.getenv(nom) or defaut))
    except ValueError:
        return defaut


NIVEAUX = ("prudent", "equilibre", "risque")
NB_JAMBES_MIN = 2
TAILLE_REFERENCE = {"prudent": 3, "equilibre": 4, "risque": 5}      # nombre de jambes visé par le moteur déterministe (borné par les matchs disponibles)
TAILLE_MAX = {"prudent": 4, "equilibre": 5, "risque": 6}            # plafond de jambes de la recherche exhaustive du moteur central
PART_MAX_MEME_FAMILLE_SENS = 0.5                                    # au plus la moitié des jambes (minimum 2) dans la même famille ET le même sens
CORRELATION_PAIRE = 0.04                                            # perte relative de probabilité jointe par paire « même compétition, même famille et sens » (proxy)
PROBA_JOINTE_MIN = {"prudent": 0.0, "equilibre": 0.0, "risque": 0.02}   # plancher de SÉCURITÉ sur la probabilité jointe (pas une cote cible)

# Planchers de RÉMUNÉRATION, identiques à ceux de l'agent (agent_strategie.COTE_MIN_JAMBE_AGENT et COTE_TOTALE_MIN_COUPON, mêmes variables d'environnement) : aucun moteur ne
# produit un coupon à 1.04 qui gagne presque toujours mais ne rapporte rien. Planchers de sécurité, PAS des cibles (aucun plafond) ; 0 = désactivé.
COTE_MIN_JAMBE = _lire("COTE_MIN_JAMBE_AGENT", 1.20)
COTE_TOTALE_MIN_COUPON = _lire("COTE_TOTALE_MIN_COUPON", 1.60)

_SENS_MOTS = (("over", ("over", "plus")), ("under", ("under", "moins")), ("yes", ("yes", "oui")), ("no", ("no", "non")))


def famille(categorie):
    """Famille de marché : 'buts', 'btts', 'resultat', 'corners', 'cartons', 'tirs', 'fautes', 'hors_jeux', 'handicap' ou 'autre'."""
    c = (categorie or "").lower()
    for cle, mots in (("corners", ("corner",)), ("cartons", ("carton",)), ("tirs", ("tir",)), ("fautes", ("faute",)), ("hors_jeux", ("hors",)),
                      ("btts", ("btts", "both teams")), ("handicap", ("handicap",)),
                      ("resultat", ("double chance", "full time result", "draw no bet", "résultat")), ("buts", ("total", "over under", "buts", "pair"))):
        if any(m in c for m in mots):
            return cle
    return "autre"


def sens(selection):
    s = str(selection or "").lower()
    for nom, mots in _SENS_MOTS:
        if any(m in s for m in mots):
            return nom
    return "autre"


def valider_jambe(j):
    """Renvoie une raison de refus ou None. Jamais de probabilité ni de cote devinée."""
    p, cote = j.get("p"), j.get("cote")
    if p is None or not isinstance(p, (int, float)) or not 0.0 < p < 1.0 + 1e-9:
        return "probabilité absente ou hors de (0, 1]"
    if cote is None or not isinstance(cote, (int, float)) or cote <= 1.0:
        return "cote absente ou invalide"
    if COTE_MIN_JAMBE and cote < COTE_MIN_JAMBE:
        return f"cote {cote} sous le plancher technique {COTE_MIN_JAMBE:g}"
    if not j.get("match"):
        return "match absent"
    return None


def cle_famille_sens(j):
    return (famille(j.get("categorie")), sens(j.get("selection")))


def diversite_ok(jambes, part_max=PART_MAX_MEME_FAMILLE_SENS):
    """Au plus max(2, part_max × n) jambes dans une même (famille, sens) : évite d'empiler vingt « Over » corrélés."""
    n = len(jambes)
    if n < 3:
        return True
    plafond = max(2, math.floor(part_max * n + 1e-9))
    comptes = {}
    for j in jambes:
        k = cle_famille_sens(j)
        comptes[k] = comptes.get(k, 0) + 1
    return max(comptes.values()) <= plafond


def nb_paires_correlees(jambes):
    """Paires de jambes (matchs différents) de la même compétition, de la même famille et du même sens : dépendance probable (météo, arbitrage, rythme)."""
    n = 0
    for i, a in enumerate(jambes):
        for b in jambes[i + 1:]:
            if a.get("competition") and a.get("competition") == b.get("competition") and cle_famille_sens(a) == cle_famille_sens(b):
                n += 1
    return n


def proba_jointe(jambes, corriger_correlation=True):
    """Produit des probabilités (matchs indépendants), réduit de CORRELATION_PAIRE par paire corrélée : approximation prudente, jamais présentée comme mesurée."""
    p = math.prod(j["p"] for j in jambes) if jambes else 0.0
    if corriger_correlation:
        p *= (1.0 - CORRELATION_PAIRE) ** nb_paires_correlees(jambes)
    return p


def cote_totale(jambes):
    return math.prod(j["cote"] for j in jambes) if jambes else 0.0


def utilite_jambe(niveau, j):
    """Utilité d'UNE jambe selon le profil. prudent : probabilité ; équilibré : valeur espérée p×cote ; risque : ln(cote × √p) (gain visé, probabilité atténuée)."""
    p, cote = j["p"], j["cote"]
    if niveau == "prudent":
        return p
    if niveau == "equilibre":
        return p * cote
    if niveau == "risque":
        return math.log(cote) + 0.5 * math.log(p)
    raise ValueError(f"niveau de risque inconnu : {niveau!r}")


def utilite_coupon(niveau, jambes):
    """Utilité d'un coupon entier (recherche exhaustive du moteur central). prudent : ln P + 0,25 ln C ; équilibré : ln P + 0,6 ln C ; risque : 0,5 ln P + ln C."""
    p, c = proba_jointe(jambes), cote_totale(jambes)
    if p <= 0 or c <= 0:
        return float("-inf")
    poids = {"prudent": (1.0, 0.25), "equilibre": (1.0, 0.6), "risque": (0.5, 1.0)}[niveau]
    return poids[0] * math.log(p) + poids[1] * math.log(c)


def regles_coupon(jambes, niveau=None, profil=None):
    """Règles de cohérence COMMUNES aux trois moteurs. Renvoie la liste des problèmes (vide = coupon cohérent)."""
    problemes = []
    profil = profil or {}
    minimum = profil.get("nb_jambes_min") or NB_JAMBES_MIN
    maximum = profil.get("nb_jambes")
    if len(jambes) < minimum:
        problemes.append(f"{len(jambes)} jambe(s) : minimum {minimum}")
    if maximum and len(jambes) > maximum:
        problemes.append(f"{len(jambes)} jambe(s) : maximum {maximum}")
    matchs = [j.get("match") for j in jambes]
    if len(matchs) != len(set(matchs)):
        problemes.append("plusieurs paris sur le même match")
    for j in jambes:
        raison = valider_jambe(j)
        if raison:
            problemes.append(f"{j.get('match')} : {raison}")
    if not diversite_ok(jambes):
        problemes.append("trop de jambes de la même famille et du même sens")
    bas, haut = profil.get("cote_totale_min"), profil.get("cote_totale_max")
    if jambes and bas and cote_totale(jambes) < bas:
        problemes.append(f"cote totale {cote_totale(jambes):.2f} sous le minimum {bas:g} du profil")
    elif jambes and not bas and COTE_TOTALE_MIN_COUPON and cote_totale(jambes) < COTE_TOTALE_MIN_COUPON:
        problemes.append(f"cote totale {cote_totale(jambes):.2f} sous le plancher de rémunération {COTE_TOTALE_MIN_COUPON:g}")
    if jambes and haut and cote_totale(jambes) > haut:
        problemes.append(f"cote totale {cote_totale(jambes):.2f} au-dessus du maximum {haut:g} du profil")
    if niveau and jambes and proba_jointe(jambes) < PROBA_JOINTE_MIN.get(niveau, 0.0):
        problemes.append(f"probabilité jointe {proba_jointe(jambes):.3f} sous le plancher de sécurité du profil {niveau}")
    return problemes


def regles_entre_coupons(coupons):
    """coupons : liste de listes de jambes d'un même run. Un match n'apparaît que dans un coupon ; deux coupons ne sont jamais identiques. Renvoie les problèmes."""
    problemes, vus, empreintes = [], {}, set()
    for i, jambes in enumerate(coupons):
        for j in jambes:
            if j["match"] in vus and vus[j["match"]] != i:
                problemes.append(f"match {j['match']} dans deux coupons")
            vus[j["match"]] = i
        e = frozenset((j["match"], j.get("categorie"), j.get("selection")) for j in jambes)
        if e and e in empreintes:
            problemes.append("deux coupons identiques")
        empreintes.add(e)
    return problemes
