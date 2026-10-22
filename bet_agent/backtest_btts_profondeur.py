"""Investigation en profondeur du BTTS (22/10/2026) : POURQUOI le Poisson de production échoue, et ce qui peut
être corrigé. Cinq diagnostics sur les mêmes matchs, walk-forward quand un paramètre est appris :

 A. calibration PAR CÔTÉ (Oui / Non) : l'erreur vient-elle d'un seul côté ?
 B. calibration du « marque au moins un but » de CHAQUE équipe par tranche de buts attendus (zéro gonflé ?)
 C. dépendance : le 0-0 et le « une équipe blanchie » arrivent-ils plus (ou moins) que sous indépendance ?
 D. calibration du BTTS par tranche de la plus FAIBLE attaque (min des deux mu), du total, et par ligue
 E. modèle corrigé : zéros gonflés (pi) + dépendance (kappa) ajustés sur le passé, évalués sur le futur
"""

import math
from collections import defaultdict

import backtest_btts as bb
from moteur import calibration as calib


def _p_yes(mu_h, mu_a, pi=0.0, kappa=1.0):
    """P(BTTS) avec zéros gonflés (pi) et facteur de dépendance du 0-0 (kappa) :
    P(oui) = 1 - P(h=0) - P(a=0) + P(0,0)."""
    p0h = pi + (1 - pi) * math.exp(-mu_h)
    p0a = pi + (1 - pi) * math.exp(-mu_a)
    p00 = min(p0h, p0a, p0h * p0a * kappa)
    return min(max(1 - p0h - p0a + p00, 1e-4), 1 - 1e-4)


def _table(points, bornes, titre, formater=lambda b: f"{b[0]:.2f}-{b[1]:.2f}"):
    print(f"\n{titre}")
    for bas, haut in bornes:
        dans = [(p, y) for p, y, x in points if bas <= x < haut]
        if len(dans) >= 30:
            print(f"   {formater((bas, haut)):12s} n={len(dans):5d} annoncé={100 * sum(p for p, _ in dans) / len(dans):5.1f}% "
                  f"réel={100 * sum(y for _, y in dans) / len(dans):5.1f}%")


def diagnostics(ech):
    n = len(ech)
    test = ech[int(n * 0.5):]
    print(f"{n} matchs, test = {len(test)} (50 % les plus récents)")

    # --- A. par côté
    print("\n=== A. Calibration par côté du BTTS (Poisson de production, matchs de test) ===")
    for nom, selection in (("OUI (les deux marquent)", lambda p: p), ("NON (une équipe blanchie)", lambda p: 1 - p)):
        pts = [(selection(e["p_pois"]), e["y"] if nom.startswith("OUI") else 1 - e["y"]) for e in test]
        for bas, haut in ((0.40, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.80)):
            dans = [(p, y) for p, y in pts if bas <= p < haut]
            if len(dans) >= 30:
                print(f"   {nom:26s} {bas:.2f}-{haut:.2f}: n={len(dans):5d} annoncé={100 * sum(p for p, _ in dans) / len(dans):5.1f}% "
                      f"réel={100 * sum(y for _, y in dans) / len(dans):5.1f}%")

    # --- B. zéro par équipe selon mu
    print("\n=== B. « L'équipe marque au moins un but » par tranche de buts attendus (toutes équipes, matchs de test) ===")
    pts = []
    for e in test:
        for mu_e, g in ((e["mu"][0], e["buts"][0]), (e["mu"][1], e["buts"][1])):
            pts.append((1 - math.exp(-mu_e), 1 if g > 0 else 0, mu_e))
    _table(pts, ((0, .7), (.7, .9), (.9, 1.1), (1.1, 1.3), (1.3, 1.6), (1.6, 2.0), (2.0, 9)), "   (annoncé = 1 - exp(-mu))")
    biais = sum(g for e in test for g in e["buts"]) / (2 * len(test)) - sum(sum(e["mu"]) for e in test) / (2 * len(test))
    print(f"   biais de mu (observé - attendu, buts par équipe) : {biais:+.3f}")

    # --- C. dépendance
    print("\n=== C. Dépendance entre les deux équipes (matchs de test) ===")
    p_h0 = sum(1 for e in test if e["buts"][0] == 0) / len(test)
    p_a0 = sum(1 for e in test if e["buts"][1] == 0) / len(test)
    p_00 = sum(1 for e in test if e["buts"] == (0, 0)) / len(test)
    mod_00 = sum(math.exp(-e["mu"][0] - e["mu"][1]) for e in test) / len(test)
    print(f"   P(domicile à 0)={100 * p_h0:.1f}%  P(extérieur à 0)={100 * p_a0:.1f}%  P(0-0) observé={100 * p_00:.1f}%  "
          f"sous indépendance (observé)={100 * p_h0 * p_a0:.1f}%  Poisson du modèle={100 * mod_00:.1f}%  "
          f"=> facteur kappa observé = {p_00 / (p_h0 * p_a0):.2f}")
    cov = sum((e["buts"][0] - e["mu"][0]) * (e["buts"][1] - e["mu"][1]) for e in test) / len(test)
    print(f"   covariance des résidus de buts = {cov:+.3f}")

    # --- D. segmentation
    pts = [(e["p_pois"], e["y"], min(e["mu"])) for e in test]
    _table(pts, ((0, .8), (.8, 1.0), (1.0, 1.2), (1.2, 1.4), (1.4, 1.7), (1.7, 9)),
           "=== D1. P(BTTS oui) par tranche de la plus FAIBLE attaque (min des deux mu) ===")
    pts = [(e["p_pois"], e["y"], sum(e["mu"])) for e in test]
    _table(pts, ((0, 2.0), (2.0, 2.4), (2.4, 2.8), (2.8, 3.2), (3.2, 9)),
           "=== D2. P(BTTS oui) par tranche de buts attendus totaux ===")
    par_ligue = defaultdict(list)
    for e in test:
        par_ligue[e.get("ligue")].append(e)
    print("\n=== D3. Par ligue (taux réel de BTTS oui, annoncé moyen) ===")
    for ligue, lst in sorted(par_ligue.items(), key=lambda kv: str(kv[0])):
        print(f"   ligue {ligue}: n={len(lst):4d} annoncé={100 * sum(e['p_pois'] for e in lst) / len(lst):5.1f}% "
              f"réel={100 * sum(e['y'] for e in lst) / len(lst):5.1f}%")

    # --- E. modèle corrigé (pi, kappa appris sur le PASSÉ)
    print("\n=== E. Zéros gonflés (pi) + dépendance du 0-0 (kappa), appris sur les 50 % les plus anciens ===")
    coupe = int(n * 0.5)
    apprentissage = ech[:coupe]

    def logloss(sub, pi, kappa):
        return -sum(e["y"] * math.log(_p_yes(*e["mu"], pi, kappa)) + (1 - e["y"]) * math.log(1 - _p_yes(*e["mu"], pi, kappa))
                    for e in sub) / len(sub)

    meilleur = min(((logloss(apprentissage, pi, k), pi, k) for pi in (0.0, 0.02, 0.04, 0.06, 0.08)
                    for k in (0.8, 0.9, 1.0, 1.1, 1.2, 1.3)))
    print(f"   meilleurs paramètres sur l'apprentissage : pi={meilleur[1]:.2f} kappa={meilleur[2]:.2f} (logloss {meilleur[0]:.4f})")
    taux = sum(e["y"] for e in apprentissage) / len(apprentissage)
    variantes = {
        "constante (taux de l'apprentissage)": lambda e: taux,
        "Poisson de production": lambda e: e["p_pois"],
        f"Poisson corrigé pi={meilleur[1]:.2f} kappa={meilleur[2]:.2f}": lambda e: _p_yes(*e["mu"], meilleur[1], meilleur[2]),
    }
    iso = calib.Isotone([(_p_yes(*e["mu"], meilleur[1], meilleur[2]), e["y"]) for e in apprentissage])
    variantes["corrigé + isotone"] = lambda e: iso(_p_yes(*e["mu"], meilleur[1], meilleur[2]))
    ref = None
    for nom, f in variantes.items():
        pts = [(f(e), e["y"]) for e in test]
        m = bb.metriques(pts)
        ref = ref or m["brier"]
        s = "  ".join(f">={int(k * 100)}%: {v[0]} ({100 * v[1]:.1f}/{100 * v[2]:.1f})" for k, v in m["seuils"].items() if v[0])
        print(f"   {nom:42s} Brier={m['brier']:.4f} ({100 * (ref - m['brier']) / ref:+.2f}%) logloss={m['log_loss']:.4f}  {s}")


if __name__ == "__main__":  # pragma: no cover — lancé par diagnostics.yml (accès base)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app.database import SessionLocal
    from app.services.historique import charger_matchs

    competitions = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
    with SessionLocal() as db:
        donnees = {cid: charger_matchs(db, competition_id=cid) for cid in competitions}
    diagnostics(bb.construire_echantillons(donnees))
