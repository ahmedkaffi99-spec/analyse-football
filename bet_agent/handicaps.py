"""HANDICAPS (08/11/2026) : les DEUX seuls handicaps de buts du Bet Agent, calculés et réglés par la MÊME règle (moteur.modeles.marches) — jamais deux implémentations.

1. ASIAN HANDICAP (AH, 2 voies) : ligne ENTIÈRE (remboursement possible), DEMIE (jamais de remboursement) ou de QUART (.25/.75 = deux demi-mises sur les lignes voisines).
   Issues : gagné, demi-gagné, remboursé, demi-perdu, perdu. Le handicap s'applique à l'équipe choisie ; les cotes OddsPapi/API-Football sont référencées DOMICILE.
2. EUROPEAN HANDICAP (EH, 3 voies 1/X/2) : ligne ENTIÈRE ajoutée aux buts du DOMICILE, puis lecture du résultat du score ajusté (le nul reste possible : gagné ou perdu seulement).

Pour chaque ligne : probabilités, cote juste (Fair Odds), valeur espérée (EV) et règlement (profit selon l'issue). Aucun handicap d'équipe (corners, cartons, fautes, tirs, hors-jeux) ni handicap
fondé sur des statistiques n'est géré ici : ces marchés restent traités à part, inchangés. Module sans dépendance réseau ni base."""

import os
import sys

_RACINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)
from moteur.modeles import marches as _m  # noqa: E402
import modele_probabilites as _mp  # noqa: E402

ISSUES = _m.ISSUES


# ---------------------------------------------------------------- Asian Handicap
def type_ligne_asiatique(ligne):
    """'entiere', 'demie' ou 'quart' ; ValueError si la ligne n'est pas un multiple de 0,25."""
    r = ligne * 4
    if abs(r - round(r)) > 1e-9:
        raise ValueError(f"ligne d'Asian Handicap invalide (multiple de 0,25 attendu) : {ligne}")
    quarts = round(r)
    if quarts % 2:
        return "quart"
    return "demie" if (quarts // 2) % 2 else "entiere"


def _cote_selection(selection):
    sel = str(selection).strip().lower()
    if sel in ("1", "home"):
        return "1"
    if sel in ("2", "away"):
        return "2"
    raise ValueError(f"sélection d'Asian Handicap invalide : {selection}")


def issue_asiatique(h, a, ligne, selection):
    """Issue d'un pari AH pour le score final (h, a) ; ligne référencée DOMICILE (la sélection '2' évalue la ligne opposée)."""
    type_ligne_asiatique(ligne)
    return _m.issue_buts("handicap", ligne, _cote_selection(selection), h, a)


def reglement_asiatique(h, a, ligne, selection, cote, mise=1.0):
    """{'issue', 'profit', 'retour'} d'un pari AH réglé au score (h, a). Retour = mise + profit."""
    issue = issue_asiatique(h, a, ligne, selection)
    profit = _m.profit(issue, cote, mise)
    return {"issue": issue, "profit": round(profit, 10), "retour": round(mise + profit, 10)}


def analyser_ligne_asiatique(mu_home, mu_away, ligne, cote_home=None, cote_away=None, dispersion=1.0):
    """Probabilités des 5 issues, cote juste et EV (si une cote est fournie) des deux côtés d'une ligne AH (ligne référencée domicile)."""
    genre = type_ligne_asiatique(ligne)
    cotes = {"1": cote_home, "2": cote_away}
    cotes_issues = {"1": _mp.issues_handicap(mu_home, mu_away, ligne, dispersion),
                    "2": _mp.issues_handicap(mu_away, mu_home, -ligne, dispersion)}
    sortie = {"type": "AH", "ligne": ligne, "genre_ligne": genre, "selections": {}}
    for sel, issues in cotes_issues.items():
        cote = cotes[sel]
        sortie["selections"][sel] = {
            "issues": issues,
            "proba_gain_pct": round((issues["gagne"] + issues["demi_gagne"]) * 100, 2),
            "cote_juste": _m.cote_juste(issues),
            "cote": cote,
            "ev": (round(_m.esperance(issues, cote), 6) if cote and cote > 1 else None),
        }
    return sortie


# ---------------------------------------------------------------- European Handicap
def issue_europeenne(h, a, ligne, selection):
    return _m.issue_handicap_europeen(h, a, ligne, selection)


def reglement_europeen(h, a, ligne, selection, cote, mise=1.0):
    """Règlement d'un pari EH (gagné ou perdu seulement)."""
    issue = issue_europeenne(h, a, ligne, selection)
    profit = _m.profit(issue, cote, mise)
    return {"issue": issue, "profit": round(profit, 10), "retour": round(mise + profit, 10),
            "resultat_ajuste": _m.resultat_handicap_europeen(h, a, ligne)}


def score_ajuste(h, ligne):
    """Buts du domicile après application du handicap européen."""
    if not _m.ligne_europeenne_valide(ligne):
        raise ValueError(f"ligne de handicap européen invalide (entier attendu) : {ligne}")
    return h + round(ligne)


def analyser_ligne_europeenne(mu_home, mu_away, ligne, cotes=None, dispersion=1.0):
    """Probabilités 1/X/2, cotes justes, EV de chaque sélection (si ses cotes sont fournies) et marge du bookmaker (somme des probabilités implicites - 1)."""
    probas = _mp.proba_handicap_europeen(mu_home, mu_away, ligne, dispersion)
    cotes = cotes or {}
    sortie = {"type": "EH", "ligne": ligne, "selections": {}}
    for sel in ("1", "X", "2"):
        p, cote = probas[sel], cotes.get(sel)
        sortie["selections"][sel] = {
            "proba_pct": round(p * 100, 2),
            "cote_juste": (1 / p if p > 1e-12 else None),
            "cote": cote,
            "ev": (round(p * cote - 1, 6) if cote and cote > 1 else None),
        }
    if all(cotes.get(s) and cotes[s] > 1 for s in ("1", "X", "2")):
        sortie["marge_bookmaker_pct"] = round((sum(1 / cotes[s] for s in ("1", "X", "2")) - 1) * 100, 2)
    return sortie


# ---------------------------------------------------------------- Vérification du règlement
def verifier_reglement(matrice, type_handicap, ligne, selection, cote, tolerance=1e-9):
    """Contrôle de cohérence modèle / règlement : l'espérance calculée par la distribution des issues doit être égale à la moyenne, pondérée par la matrice de scores, des profits RÉGLÉS score par score.
    Renvoie {'ev_distribution', 'ev_reglement', 'ecart', 'coherent'} (ValueError si la matrice est vide)."""
    if not matrice:
        raise ValueError("matrice de scores vide")
    ev_reglement = 0.0
    for h, rangee in enumerate(matrice):
        for a, p in enumerate(rangee):
            if p:
                regle = reglement_asiatique(h, a, ligne, selection, cote) if type_handicap == "AH" else reglement_europeen(h, a, ligne, selection, cote)
                ev_reglement += p * regle["profit"]
    if type_handicap == "AH":
        issues = _m.distribution_buts(matrice, "handicap", ligne, _cote_selection(selection))
        ev_distribution = _m.esperance(issues, cote)
    else:
        probas = _m.distribution_handicap_europeen(matrice, ligne)
        ev_distribution = probas[str(selection).upper()] * cote - 1
    ecart = abs(ev_distribution - ev_reglement)
    return {"ev_distribution": ev_distribution, "ev_reglement": ev_reglement, "ecart": ecart, "coherent": ecart <= tolerance}


def matrice_scores(mu_home, mu_away, dispersion=1.0):
    """Matrice [buts domicile][buts extérieur] sous indépendance (mêmes lois que le modèle de production)."""
    d_home, d_away = _mp._distribution_comptage(mu_home, dispersion), _mp._distribution_comptage(mu_away, dispersion)
    return [[pi * pj for pj in d_away] for pi in d_home]


def tableau_handicaps(mu_home, mu_away, lignes_asiatiques=(), lignes_europeennes=(), dispersion=1.0):
    """Une entrée par ligne (AH puis EH) : probabilités, cotes justes, EV (sans cote : None)."""
    lignes = [analyser_ligne_asiatique(mu_home, mu_away, l, dispersion=dispersion) for l in lignes_asiatiques]
    lignes += [analyser_ligne_europeenne(mu_home, mu_away, l, dispersion=dispersion) for l in lignes_europeennes]
    return lignes
