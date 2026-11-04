"""Phase 5 — moteurs de COMPTAGE (corners, cartons jaunes, tirs, tirs cadrés, fautes) sur la base historique `fd_matchs`.
Football-Data ne fournit PAS de cotes pour ces marchés : on évalue donc la QUALITÉ DES PROBABILITÉS (Brier, log-loss, calibration), hors
échantillon et en walk-forward, jamais un ROI. Comparaison de : référence naïve (fréquence passée de la ligue) / Poisson par équipe /
binomiale négative par équipe. Les probabilités viennent uniquement de moteurs statistiques vérifiables (phase2_modeles)."""
import math
import sys
from datetime import timedelta
from pathlib import Path

import phase2_modeles as pm

STATS = {  # nom: (colonne domicile, colonne extérieur, lignes de total testées, kmax par équipe)
    "corners": ("HC", "AC", (8.5, 9.5, 10.5, 11.5), 30),
    "cartons_jaunes": ("HY", "AY", (2.5, 3.5, 4.5, 5.5), 15),
    "tirs": ("HS", "AS", (22.5, 24.5, 26.5, 28.5), 50),
    "tirs_cadres": ("HST", "AST", (7.5, 8.5, 9.5, 10.5), 25),
    "fautes": ("HF", "AF", (22.5, 24.5, 26.5), 40),
}
FENETRE_JOURS = 1100
REFIT_JOURS = 21


def convolution(p1, p2):
    n = len(p1) + len(p2) - 1
    out = [0.0] * n
    for i, a in enumerate(p1):
        for j, b in enumerate(p2):
            out[i + j] += a * b
    s = sum(out)
    return [x / s for x in out]


def proba_over_total(pmf_total, ligne):
    return sum(p for k, p in enumerate(pmf_total) if k > ligne)


def charger(db):
    """[(date, ligue, dom, ext, stats)] depuis fd_matchs (lecture seule), triés par date."""
    from sqlalchemy import select
    from app.models_historique import FdMatch
    rows = db.execute(select(FdMatch.date_match, FdMatch.ligue, FdMatch.domicile, FdMatch.exterieur, FdMatch.stats)
                      .order_by(FdMatch.date_match)).all()
    return [(d, lg, h, a, s or {}) for d, lg, h, a, s in rows]


def walk_forward(matchs, stat, debut_test):
    """Pour un type de comptage : liste d'événements {ligne, p_naif, p_poisson, p_nb, issue(0/1), ligue, dispersion}."""
    ch, ca, lignes, kmax = STATS[stat]
    serie = [(d, lg, h, a, s[ch], s[ca]) for d, lg, h, a, s in matchs if ch in s and ca in s]
    evts, forces, derniere, passe = [], None, None, []
    for d, lg, h, a, x, y in serie:
        if d >= debut_test:
            if forces is None or (d - derniere).days >= REFIT_JOURS:
                fen = [m for m in passe if (d - m[0]).days <= FENETRE_JOURS]
                forces, derniere = pm.ajuster([(m[0], m[2], m[3], m[4], m[5]) for m in fen], d, iterations=20), d
            lam, mu = forces.buts_attendus(h, a)
            lam, mu = min(max(lam, 0.05), kmax * 0.8), min(max(mu, 0.05), kmax * 0.8)
            tp = convolution(pm.pmf_poisson(lam, kmax), pm.pmf_poisson(mu, kmax))
            tn = convolution(pm.pmf_binomiale_negative(lam, forces.dispersion, kmax), pm.pmf_binomiale_negative(mu, forces.dispersion, kmax))
            recents = [m for m in passe if m[1] == lg and (d - m[0]).days <= 365]
            for ligne in lignes:
                naif = (sum(1 for m in recents if m[4] + m[5] > ligne) + 1) / (len(recents) + 2) if recents else 0.5
                evts.append({"stat": stat, "ligne": ligne, "p_naif": naif, "p_poisson": proba_over_total(tp, ligne),
                             "p_nb": proba_over_total(tn, ligne), "issue": 1.0 if x + y > ligne else 0.0, "ligue": lg,
                             "dispersion": forces.dispersion})
        passe.append((d, lg, h, a, x, y))
    return evts


def brier_bin(p, y):
    return (p - y) ** 2


def log_loss_bin(p, y):
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def rapport_stat(evts):
    out = []
    stat = evts[0]["stat"] if evts else "?"
    for ligne in sorted({e["ligne"] for e in evts}):
        ev = [e for e in evts if e["ligne"] == ligne]
        base = sum(e["issue"] for e in ev) / len(ev)
        ligne_txt = [f"  {stat} total > {ligne} : n={len(ev)}, fréquence réelle {base*100:.1f} %"]
        ref = [brier_bin(e["p_naif"], e["issue"]) for e in ev]
        for nom, cle in (("référence naïve (ligue, 12 mois)", "p_naif"), ("Poisson par équipe", "p_poisson"), ("binomiale négative par équipe", "p_nb")):
            br = [brier_bin(e[cle], e["issue"]) for e in ev]
            ll = [log_loss_bin(e[cle], e["issue"]) for e in ev]
            mb, _ = pm.moyenne_et_erreur_type(br)
            ml, _ = pm.moyenne_et_erreur_type(ll)
            md, ed = pm.moyenne_et_erreur_type([a - b for a, b in zip(br, ref)])
            _, ece = pm.table_calibration([(e[cle], e["issue"]) for e in ev], 10)
            ligne_txt.append(f"    {nom:34} Brier {mb:.4f}  LogLoss {ml:.4f}  ECE {ece:.4f}  ΔBrier vs naïf {md:+.4f}±{ed:.4f}")
        out += ligne_txt
    disp = sum(e["dispersion"] for e in evts) / len(evts)
    out.append(f"  dispersion moyenne estimée (binomiale négative, r) : {disp:.0f} (r grand = proche de Poisson)")
    return out


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.database import SessionLocal
    with SessionLocal() as db:
        matchs = charger(db)
    print(f"{len(matchs)} matchs chargés de fd_matchs")
    debut_test = matchs[0][0] + timedelta(days=2 * 365)
    for stat in STATS:
        evts = walk_forward(matchs, stat, debut_test)
        n = len({(e['ligne']) for e in evts})
        print(f"\n=== {stat.upper()} — {len(evts)//max(n,1)} matchs testés hors échantillon (walk-forward, test à partir de {debut_test}) ===")
        print("\n".join(rapport_stat(evts)))


if __name__ == "__main__":
    main()
