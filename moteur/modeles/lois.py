"""Lois de probabilité en Python pur (aucune dépendance) : Poisson, binomiale négative,
matrice de scores Dixon-Coles."""

import math


def poisson_pmf(k, mu):
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(mu) - mu - math.lgamma(k + 1))


def binomiale_negative_pmf(k, mu, variance):
    """Paramétrée par moyenne et variance (méthode des moments). Variance <= moyenne ou
    inconnue : retombe sur Poisson (pas de surdispersion mesurée)."""
    if variance is None or variance <= mu or mu <= 0:
        return poisson_pmf(k, mu)
    r = mu * mu / (variance - mu)
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p))


def distribution(mu, variance=None, k_max=None):
    """Distribution discrète tronquée, renormalisée (la masse au-delà de k_max est négligeable
    pour les k_max choisis : contrôlé par test)."""
    if k_max is None:
        k_max = max(15, int(mu + 10 * math.sqrt(max(variance or mu, 1e-9))) + 5)
    probs = [binomiale_negative_pmf(k, mu, variance) for k in range(k_max + 1)]
    total = sum(probs)
    return [p / total for p in probs]


def _tau(i, j, lh, la, rho):
    if i == 0 and j == 0:
        return 1 - lh * la * rho
    if i == 0 and j == 1:
        return 1 + lh * rho
    if i == 1 and j == 0:
        return 1 + la * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def matrice_scores(lambda_home, lambda_away, rho=0.0, buts_max=10):
    """P(home=i, away=j). rho=0 : Poisson indépendant ; rho<0 (typique, ~-0.05 à -0.15) :
    correction Dixon-Coles des scores faibles (0-0, 1-1 plus fréquents que l'indépendance)."""
    ph = [poisson_pmf(i, lambda_home) for i in range(buts_max + 1)]
    pa = [poisson_pmf(j, lambda_away) for j in range(buts_max + 1)]
    m = [[ph[i] * pa[j] * _tau(i, j, lambda_home, lambda_away, rho) for j in range(buts_max + 1)]
         for i in range(buts_max + 1)]
    total = sum(map(sum, m))
    return [[v / total for v in ligne] for ligne in m]


def proba_depasse(dist, ligne):
    """Pour une ligne de total : (P(> ligne), P(= ligne), P(< ligne)) — P(=) non nul seulement
    pour une ligne entière (remboursement)."""
    plus = sum(p for k, p in enumerate(dist) if k > ligne + 1e-9)
    egal = sum(p for k, p in enumerate(dist) if abs(k - ligne) < 1e-9)
    return plus, egal, 1 - plus - egal
