"""Championnat synthétique à forces connues (aucune donnée réelle inventée : sert uniquement à
vérifier que le moteur retrouve une réalité connue d'avance)."""

import math
import random
from datetime import datetime, timedelta, timezone


def _poisson(rng, mu):
    seuil, k, p = math.exp(-mu), 0, 1.0
    while True:
        p *= rng.random()
        if p <= seuil:
            return k
        k += 1


def championnat(n_equipes=12, saisons=(2023, 2024), graine=1, avec_stats=True):
    rng = random.Random(graine)
    forces = {e: (rng.uniform(0.6, 1.6), rng.uniform(0.6, 1.5)) for e in range(1, n_equipes + 1)}
    matchs, mid = [], 1
    for saison in saisons:
        jour = datetime(saison, 8, 1, 18, tzinfo=timezone.utc)
        for aller in (0, 1):
            for h in forces:
                for a in forces:
                    if h == a or (aller and h < a) or (not aller and h > a):
                        continue
                    lh = 1.45 * forces[h][0] * forces[a][1]
                    la = 1.15 * forces[a][0] * forces[h][1]
                    m = {"match_id": mid, "date": jour, "competition_id": 1, "competition": "Ligue Test",
                         "saison": saison, "home_id": h, "home": f"E{h}", "away_id": a, "away": f"E{a}",
                         "home_score": _poisson(rng, lh), "away_score": _poisson(rng, la), "arbitre": f"A{mid % 5}"}
                    if avec_stats:
                        m["stats"] = {
                            "home": {"corners": _poisson(rng, 5.5 * forces[h][0]), "yellow_cards": _poisson(rng, 1.8),
                                     "shots": _poisson(rng, 13 * forces[h][0]), "shots_on_target": _poisson(rng, 4.5 * forces[h][0]),
                                     "fouls": _poisson(rng, 11)},
                            "away": {"corners": _poisson(rng, 4.5 * forces[a][0]), "yellow_cards": _poisson(rng, 2.0),
                                     "shots": _poisson(rng, 10 * forces[a][0]), "shots_on_target": _poisson(rng, 3.5 * forces[a][0]),
                                     "fouls": _poisson(rng, 12)},
                        }
                    matchs.append(m)
                    mid += 1
                    jour += timedelta(hours=7)
    return matchs, forces
