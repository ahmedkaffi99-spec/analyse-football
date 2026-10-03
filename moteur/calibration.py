"""Calibration : si le modèle annonce 80 %, environ 80 % doivent réellement passer.

- Régression isotone (algorithme PAV, Python pur) ajustée UNIQUEMENT sur des prédictions hors
  échantillon antérieures (walk-forward, voir backtest) ; une calibration ajustée sur la même
  période qu'elle évalue serait une fuite.
- Une clé (modèle, marché) sans assez d'historique (cfg.calibration_min_n) est marquée non
  calibrée : la probabilité brute est conservée mais le filtre de sélection la refuse si
  cfg.exiger_calibration.
- Seuls les marchés binaires sont calibrés (gagné/perdu) ; un remboursement n'est pas une issue
  binaire.
"""

import bisect
import math

TRANCHES = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0001)]


def brier(points):
    return sum((p - y) ** 2 for p, y in points) / len(points) if points else None


def log_loss(points, eps=1e-6):
    if not points:
        return None
    return -sum(y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps)) for p, y in points) / len(points)


def tableau_fiabilite(points, tranches=TRANCHES):
    lignes = []
    for bas, haut in tranches:
        dans = [(p, y) for p, y in points if bas <= p < haut]
        if dans:
            proba = sum(p for p, _ in dans) / len(dans)
            reel = sum(y for _, y in dans) / len(dans)
            lignes.append({"tranche": f"{int(bas * 100)}-{min(int(haut * 100), 100)}%", "n": len(dans),
                           "proba_moyenne": round(proba, 4), "frequence_reelle": round(reel, 4),
                           "ecart": round(reel - proba, 4)})
    return lignes


class Isotone:
    def __init__(self, points):
        """points : [(proba_brute, issue 0/1)]. Ajuste une fonction croissante par PAV."""
        groupes = {}
        for p, y in points:  # probabilités identiques = un seul bloc (sinon PAV dépend de l'ordre des y)
            s, w = groupes.get(p, (0, 0))
            groupes[p] = (s + y, w + 1)
        blocs = []  # [somme_y, poids, p_min, p_max]
        for p, (s, w) in sorted(groupes.items()):
            blocs.append([s, w, p, p])
            while len(blocs) > 1 and blocs[-2][0] / blocs[-2][1] >= blocs[-1][0] / blocs[-1][1]:
                s, w, _, pmax = blocs.pop()
                blocs[-1][0] += s
                blocs[-1][1] += w
                blocs[-1][3] = pmax
        self.seuils = [b[3] for b in blocs]
        self.valeurs = [b[0] / b[1] for b in blocs]
        self.n = len(points)

    def __call__(self, p):
        if not self.seuils:
            return p
        i = min(bisect.bisect_left(self.seuils, p), len(self.seuils) - 1)
        return self.valeurs[i]


class Calibrateur:
    def __init__(self, min_n=100):
        self.min_n = min_n
        self.modeles = {}

    @staticmethod
    def cle(modele, marche):
        return (modele, marche)

    def ajuster(self, historique):
        """historique : itérable de (modele, marche, proba_brute, issue_binaire 0/1)."""
        groupes = {}
        for modele, marche, p, y in historique:
            groupes.setdefault(self.cle(modele, marche), []).append((p, y))
        self.modeles = {cle: Isotone(points) for cle, points in groupes.items()}
        return self

    def calibrer(self, modele, marche, p):
        """(proba_calibrée, n_historique, calibrée_fiable)."""
        iso = self.modeles.get(self.cle(modele, marche))
        if iso is None or iso.n < self.min_n:
            return p, (iso.n if iso else 0), False
        return iso(p), iso.n, True
