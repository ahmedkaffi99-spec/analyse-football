"""Phase 2 — moteurs statistiques de buts, VÉRIFIABLES et indépendants de la production (Python pur, sans dépendance) :
Poisson, Dixon-Coles (correction des petits scores) et binomiale négative, avec ajustement walk-forward et métriques
(Brier, log-loss, calibration, valeur par rapport à la clôture). Aucune donnée postérieure à la date de prédiction.

Convention : lam = buts attendus de l'équipe à domicile, mu = ceux de l'équipe à l'extérieur."""
import math
from collections import defaultdict
from datetime import datetime

KMAX = 12  # matrice de scores 0..KMAX (queue négligeable au-delà)


# ----------------------------------------------------------------- lois de comptage
def pmf_poisson(mu, kmax=KMAX):
    p, out = math.exp(-mu), []
    for k in range(kmax + 1):
        out.append(p)
        p *= mu / (k + 1)
    return out


def pmf_binomiale_negative(mu, r, kmax=KMAX):
    """Binomiale négative de moyenne mu et de dispersion r : variance = mu + mu²/r (r grand -> Poisson)."""
    q = r / (r + mu)
    p, out = q ** r, []
    for k in range(kmax + 1):
        out.append(p)
        p *= (k + r) / (k + 1) * (1 - q)
    return out


def matrice(pmf_dom, pmf_ext):
    """Matrice de scores jointe (indépendance), renormalisée."""
    m = [[a * b for b in pmf_ext] for a in pmf_dom]
    s = sum(sum(l) for l in m)
    return [[x / s for x in l] for l in m]


def tau(x, y, lam, mu, rho):
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def matrice_dixon_coles(lam, mu, rho):
    m = matrice(pmf_poisson(lam), pmf_poisson(mu))
    for x in (0, 1):
        for y in (0, 1):
            m[x][y] *= max(tau(x, y, lam, mu, rho), 1e-9)
    s = sum(sum(l) for l in m)
    return [[v / s for v in l] for l in m]


# ----------------------------------------------------------------- marchés à partir d'une matrice
def probas_1x2(m):
    h = sum(m[i][j] for i in range(len(m)) for j in range(len(m)) if i > j)
    d = sum(m[i][i] for i in range(len(m)))
    return {"1": h, "X": d, "2": 1 - h - d}


def proba_over(m, ligne):
    """P(total buts > ligne) pour une ligne en .5 (pas de remboursement)."""
    return sum(m[i][j] for i in range(len(m)) for j in range(len(m)) if i + j > ligne)


def proba_btts(m):
    return sum(m[i][j] for i in range(1, len(m)) for j in range(1, len(m)))


def proba_ah_demi_ligne(m, ligne_dom):
    """P(l'équipe à domicile COUVRE le handicap `ligne_dom` en .5) : victoire si (buts_dom + ligne) > buts_ext."""
    return sum(m[i][j] for i in range(len(m)) for j in range(len(m)) if i + ligne_dom > j)


def frequences_attendues(m):
    """Fréquences que la matrice attribue à des événements d'intérêt (analyse d'erreur)."""
    n = len(m)
    return {"nul": sum(m[i][i] for i in range(n)),
            "ecart>=3": sum(m[i][j] for i in range(n) for j in range(n) if abs(i - j) >= 3),
            "total>=5": sum(m[i][j] for i in range(n) for j in range(n) if i + j >= 5),
            "total<=1": sum(m[i][j] for i in range(n) for j in range(n) if i + j <= 1)}


# ----------------------------------------------------------------- ajustement Dixon-Coles (walk-forward)
class ForceEquipes:
    """Forces d'attaque/défense par équipe et avantage du terrain, ajustés sur les matchs passés avec décroissance
    exponentielle du poids (xi par jour) et régularisation vers la moyenne (k matchs fictifs)."""

    def __init__(self, attaque, defense, gamma, moyenne, rho, dispersion):
        self.attaque, self.defense, self.gamma = attaque, defense, gamma
        self.moyenne, self.rho, self.dispersion = moyenne, rho, dispersion

    def buts_attendus(self, dom, ext):
        a_d, d_d = self.attaque.get(dom, self.moyenne), self.defense.get(dom, 1.0)
        a_e, d_e = self.attaque.get(ext, self.moyenne), self.defense.get(ext, 1.0)
        return a_d * d_e * self.gamma, a_e * d_d


def ajuster(matchs, date_ref, xi=0.0018, iterations=40, k=3.0):
    """matchs : [(date, id_dom, id_ext, buts_dom, buts_ext)] STRICTEMENT antérieurs à date_ref."""
    pas_de_donnee = not matchs
    if pas_de_donnee:
        return ForceEquipes({}, {}, 1.3, 1.3, 0.0, 1e6)
    poids = [math.exp(-xi * max((date_ref - m[0]).days, 0)) for m in matchs]
    total_w = sum(poids)
    moyenne = sum(w * (m[3] + m[4]) for w, m in zip(poids, matchs)) / (2 * total_w)
    equipes = {t for m in matchs for t in (m[1], m[2])}
    att, dfn, gamma = {t: moyenne for t in equipes}, {t: 1.0 for t in equipes}, 1.3
    for _ in range(iterations):
        s_att, e_att = defaultdict(float), defaultdict(float)
        s_def, e_def = defaultdict(float), defaultdict(float)
        for w, (_, d, e, gd, ge) in zip(poids, matchs):
            s_att[d] += w * gd; e_att[d] += w * dfn[e] * gamma
            s_att[e] += w * ge; e_att[e] += w * dfn[d]
            s_def[d] += w * ge; e_def[d] += w * att[e]
            s_def[e] += w * gd; e_def[e] += w * att[d] * gamma
        att = {t: (s_att[t] + k * moyenne) / (e_att[t] + k) for t in equipes}
        dfn = {t: (s_def[t] + k * moyenne) / (e_def[t] + k * moyenne) for t in equipes}
        norme = sum(dfn.values()) / len(dfn)
        dfn = {t: v / norme for t, v in dfn.items()}
        num = sum(w * m[3] for w, m in zip(poids, matchs))
        den = sum(w * att[m[1]] * dfn[m[2]] for w, m in zip(poids, matchs))
        gamma = num / den if den > 0 else gamma
    # rho : maximise la vraisemblance des quatre cases à petit score (seules dépendantes de rho)
    meilleur, rho_opt = -1e18, 0.0
    for r in [x / 100 for x in range(-20, 11)]:
        ll = 0.0
        for w, (_, d, e, gd, ge) in zip(poids, matchs):
            if gd <= 1 and ge <= 1:
                lam, mu = att[d] * dfn[e] * gamma, att[e] * dfn[d]
                ll += w * math.log(max(tau(gd, ge, lam, mu, r), 1e-9))
        if ll > meilleur:
            meilleur, rho_opt = ll, r
    # dispersion de la binomiale négative par la méthode des moments : var = mu + mu²/r
    num = den = 0.0
    for w, (_, d, e, gd, ge) in zip(poids, matchs):
        for obs, esp in ((gd, att[d] * dfn[e] * gamma), (ge, att[e] * dfn[d])):
            num += w * esp * esp
            den += w * ((obs - esp) ** 2 - esp)
    dispersion = min(max(num / den, 5.0), 500.0) if den > 0 else 500.0
    return ForceEquipes(att, dfn, gamma, moyenne, rho_opt, dispersion)


def matrices_modeles(forces, dom, ext):
    """{nom du modèle: matrice de scores} pour la même moyenne de buts : Poisson, Dixon-Coles, binomiale négative."""
    lam, mu = forces.buts_attendus(dom, ext)
    lam, mu = min(max(lam, 0.05), 6.0), min(max(mu, 0.05), 6.0)
    return {"poisson": matrice(pmf_poisson(lam), pmf_poisson(mu)),
            "dixon_coles": matrice_dixon_coles(lam, mu, forces.rho),
            "binomiale_negative": matrice(pmf_binomiale_negative(lam, forces.dispersion),
                                          pmf_binomiale_negative(mu, forces.dispersion))}


# ----------------------------------------------------------------- probabilités du marché
def sans_marge(cotes):
    """{sélection: proba} d'un marché complet, marge retirée proportionnellement ; None si une cote manque."""
    if not cotes or any(c is None or c <= 1.0 for c in cotes.values()):
        return None
    s = sum(1 / c for c in cotes.values())
    return {k: (1 / c) / s for k, c in cotes.items()}


def melanger(p_marche, p_modele, w):
    return {s: (1 - w) * p_marche[s] + w * p_modele[s] for s in p_marche}


# ----------------------------------------------------------------- métriques
def brier(p, gagnante):
    return sum((q - (1.0 if s == gagnante else 0.0)) ** 2 for s, q in p.items())


def log_loss(p, gagnante):
    return -math.log(max(p[gagnante], 1e-9))


def moyenne_et_erreur_type(valeurs):
    n = len(valeurs)
    if n < 2:
        return (valeurs[0] if n else float("nan")), float("nan")
    m = sum(valeurs) / n
    return m, math.sqrt(sum((v - m) ** 2 for v in valeurs) / (n - 1) / n)


def table_calibration(points, nb_tranches=10):
    """points : [(proba annoncée, 0/1 réel)] -> [(tranche, n, annoncé moyen, réel moyen)] et l'erreur de calibration
    espérée (ECE : moyenne pondérée de |annoncé - réel|)."""
    tranches = defaultdict(list)
    for p, y in points:
        tranches[min(int(p * nb_tranches), nb_tranches - 1)].append((p, y))
    lignes, ece, n_tot = [], 0.0, len(points)
    for t in sorted(tranches):
        v = tranches[t]
        ann, reel = sum(p for p, _ in v) / len(v), sum(y for _, y in v) / len(v)
        lignes.append((t, len(v), ann, reel))
        ece += len(v) / n_tot * abs(ann - reel)
    return lignes, ece


def clv_pct(cote_prise, proba_cloture_sans_marge):
    """Valeur espérée du pari au prix équitable de CLÔTURE : cote prise x proba juste - 1 (> 0 : on a battu la clôture)."""
    return cote_prise * proba_cloture_sans_marge - 1.0
