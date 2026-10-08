"""Évaluation d'un marché à partir d'une distribution (matrice de scores ou comptage).

Chaque sélection renvoie une DISTRIBUTION D'ISSUES, pas un simple gagné/perdu :
    gagne, demi_gagne, rembourse, demi_perdu, perdu
car les lignes entières (remboursement) et de quart (deux demi-mises sur les lignes voisines,
ex : -0.75 = moitié sur -0.5, moitié sur -1.0) ne sont pas binaires. L'espérance pour une cote c
vaut  P(g)(c-1) + P(dg)(c-1)/2 - P(dp)/2 - P(p), soit exactement p*c - 1 sur un marché binaire.

Convention des marchés (marche, ligne, selection) :
    resultat         None   "1" | "X" | "2"
    double_chance    None   "1X" | "X2" | "12"
    dnb              None   "1" | "2"                 (draw no bet : remboursé sur nul)
    handicap         h      "1" | "2"                 (h appliqué à l'équipe sélectionnée)
    buts_total       L      "over" | "under"
    buts_equipe1/2   L      "over" | "under"
    btts             None   "oui" | "non"
    {corners,cartons,tirs,tirs_cadres}_{total,equipe1,equipe2}   L   "over" | "under"
"""

ISSUES = ("gagne", "demi_gagne", "rembourse", "demi_perdu", "perdu")
STATS_PAR_FAMILLE = {"corners": "corners", "cartons": "yellow_cards", "tirs": "shots", "tirs_cadres": "shots_on_target"}


def _signe(marge):
    if marge > 1e-9:
        return "gagne"
    if marge < -1e-9:
        return "perdu"
    return "rembourse"


def issue_ligne(marge_sans_ligne, ligne):
    """marge_sans_ligne + ligne > 0 => gagné. Ligne de quart : deux demi-mises."""
    if ligne is None:
        return _signe(marge_sans_ligne)
    quart = abs(ligne * 4 - round(ligne * 4)) < 1e-9 and round(ligne * 4) % 2 != 0
    if not quart:
        return _signe(marge_sans_ligne + ligne)
    a, b = _signe(marge_sans_ligne + ligne - 0.25), _signe(marge_sans_ligne + ligne + 0.25)
    paire = {a, b}
    if paire == {"gagne"}:
        return "gagne"
    if paire == {"perdu"}:
        return "perdu"
    if paire == {"gagne", "rembourse"}:
        return "demi_gagne"
    if paire == {"perdu", "rembourse"}:
        return "demi_perdu"
    return "rembourse"


def issue_buts(marche, ligne, selection, h, a):
    """Issue d'un marché de buts pour le score final (h, a). Sert au calcul ET à la
    vérification des résultats (même règle, jamais deux implémentations)."""
    if marche == "resultat":
        gagne = {"1": h > a, "X": h == a, "2": h < a}[selection]
        return "gagne" if gagne else "perdu"
    if marche == "double_chance":
        gagne = {"1X": h >= a, "X2": h <= a, "12": h != a}[selection]
        return "gagne" if gagne else "perdu"
    if marche == "dnb":
        return _signe(h - a if selection == "1" else a - h)
    if marche == "handicap":
        # ligne référencée du point de vue du domicile (même convention qu'OddsPapi, voir
        # bet_agent.analyser_et_envoyer : "OddsPapi renvoie TOUJOURS la ligne du point de vue
        # de l'équipe DOMICILE"). Corrigé le 09/10/2026 : la sélection "2" doit évaluer la
        # marge extérieure contre la ligne INVERSÉE (symétrique de celle du domicile), jamais
        # la même ligne brute — sinon la condition de victoire de "2" est celle d'un handicap
        # extérieur de MÊME signe que le domicile au lieu de son opposé, inversant le résultat
        # dès que ligne != 0 (ex: ligne=-1.5, domicile gagne 1 but seulement : "2" doit gagner
        # son pari — l'extérieur n'a pas couvert -1.5 — mais le code bogué renvoyait "perdu").
        return issue_ligne(h - a, ligne) if selection == "1" else issue_ligne(a - h, -ligne)
    if marche == "btts":
        les_deux = h > 0 and a > 0
        return "gagne" if les_deux == (selection == "oui") else "perdu"
    total = {"buts_total": h + a, "buts_equipe1": h, "buts_equipe2": a}[marche]
    return issue_total(total, ligne, selection)


def issue_total(valeur, ligne, selection):
    return issue_ligne(valeur if selection == "over" else -valeur, -ligne if selection == "over" else ligne)


def _vide():
    return dict.fromkeys(ISSUES, 0.0)


def distribution_buts(matrice, marche, ligne, selection):
    d = _vide()
    for h, rangee in enumerate(matrice):
        for a, p in enumerate(rangee):
            if p:
                d[issue_buts(marche, ligne, selection, h, a)] += p
    return d


def _convolution(d1, d2):
    total = [0.0] * (len(d1) + len(d2) - 1)
    for i, p in enumerate(d1):
        if p:
            for j, q in enumerate(d2):
                total[i + j] += p * q
    return total


def distribution_comptage(dist_home, dist_away, portee, ligne, selection):
    dist = {"total": None, "equipe1": dist_home, "equipe2": dist_away}[portee]
    if dist is None:
        dist = _convolution(dist_home, dist_away)
    d = _vide()
    for k, p in enumerate(dist):
        if p:
            d[issue_total(k, ligne, selection)] += p
    return d


def esperance(issues, cote):
    return (issues["gagne"] * (cote - 1) + issues["demi_gagne"] * (cote - 1) / 2
            - issues["demi_perdu"] / 2 - issues["perdu"])


def est_binaire(issues):
    return issues["demi_gagne"] + issues["rembourse"] + issues["demi_perdu"] < 1e-12


def profit(issue, cote, mise=1.0):
    return mise * {"gagne": cote - 1, "demi_gagne": (cote - 1) / 2, "rembourse": 0.0,
                   "demi_perdu": -0.5, "perdu": -1.0}[issue]
