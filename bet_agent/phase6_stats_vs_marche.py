"""Phase 6 — marchés STATISTIQUES (corners, cartons jaunes, fautes, tirs, tirs cadrés) : moteur de production et moteur Phase 5 (binomiale
négative par équipe) contre le marché 1xBet, sur les collectes archivées rejouées. Résultats réels : totaux Football-Data (table fd_matchs)
pour les 5 championnats (les jambes « non vérifiables » faute de statistiques API-Football deviennent jugeables). Lecture seule.
Limite : un seul mois de matchs ; plusieurs lignes d'un même match sont corrélées ; « Yellow Cards » 1xBet supposé = cartons jaunes seuls."""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import phase2_modeles as pm
import phase2_production as pp
import phase2_reference as pr
import phase5_comptages as p5

STAT_PAR_CATEGORIE = {  # catégorie de production -> (clé phase 5, colonnes FD domicile/extérieur)
    "Total Corners": "corners", "Total Cartons": "cartons_jaunes", "Total Fautes": "fautes", "Total Tirs": "tirs",
    "Total Tirs Cadrés": "tirs_cadres"}
TOUTES = {"Corners": ("HC", "AC"), "Cartons": ("HY", "AY"), "Fautes": ("HF", "AF"), "Tirs Cadrés": ("HST", "AST"), "Tirs": ("HS", "AS")}


def colonnes_fd(categorie):
    """('HC','AC') pour une catégorie de production ('Total Corners', 'Total Corners Équipe 1', 'Handicap Tirs'...) ; None sinon."""
    for mot in ("Tirs Cadrés", "Corners", "Cartons", "Fautes", "Tirs"):          # « Tirs Cadrés » avant « Tirs »
        if mot in categorie:
            return TOUTES[mot]
    return None


def juger(pick, stats_fd):
    """gagne/perdu/push d'un pari statistique d'après les totaux Football-Data ; None si non jugeable."""
    import verifier_resultats as vr
    cols = colonnes_fd(pick["categorie"])
    if not cols or not stats_fd or cols[0] not in stats_fd or cols[1] not in stats_fd:
        return None
    return vr.grader_pick_stat(pick["categorie"], pick.get("handicap"), pick["selection"], stats_fd[cols[0]], stats_fd[cols[1]])


def p_selection_nb(forces, kmax, fd_dom, fd_ext, pick):
    """Probabilité NB de la sélection Over/Under d'un total de match (None si non applicable)."""
    ligne, sel = pick.get("handicap"), (pick.get("selection") or "").lower()
    if ligne is None or ("over" not in sel and "under" not in sel):
        return None
    lam, mu = forces.buts_attendus(fd_dom, fd_ext)
    lam, mu = min(max(lam, 0.05), kmax * 0.8), min(max(mu, 0.05), kmax * 0.8)
    pmf = p5.convolution(pm.pmf_binomiale_negative(lam, forces.dispersion, kmax), pm.pmf_binomiale_negative(mu, forces.dispersion, kmax))
    over = p5.proba_over_total(pmf, ligne)
    exact = pmf[int(ligne)] if abs(ligne - int(ligne)) < 1e-9 and int(ligne) < len(pmf) else 0.0     # ligne entière : push possible
    return over if "over" in sel else 1 - over - exact


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models_historique import FdMatch
    with SessionLocal() as db:
        cands, _ = pp.rejouer_runs(db, pp.DEPUIS)
        fd_all = db.execute(select(FdMatch.date_match, FdMatch.ligue, FdMatch.domicile, FdMatch.exterieur, FdMatch.stats, FdMatch.saison)).all()
    cands = [c for c in cands if colonnes_fd(c["categorie"])]
    cut = date.fromisoformat(pp.DEPUIS)
    lignes_fd = [{"date": datetime.combine(d, datetime.min.time()), "ligue": lg, "dom": h, "ext": a, "stats": s or {}}
                 for d, lg, h, a, s, sa in fd_all if sa == "2627"]
    hist = [(d, lg, h, a, s or {}) for d, lg, h, a, s, sa in fd_all if d < cut]
    print(f"Candidats statistiques rejoués : {len(cands)} ; matchs 2026/27 Football-Data : {len(lignes_fd)} ; historique d'ajustement : {len(hist)}")
    forces = {}
    for nom, (ch, ca, lignes, kmax) in p5.STATS.items():
        serie = [(d, h, a, s[ch], s[ca]) for d, lg, h, a, s in hist if ch in s and ca in s and (cut - d).days <= p5.FENETRE_JOURS]
        forces[nom] = pm.ajuster(serie, cut, iterations=20)
    cache, jugees = {}, []
    for c in cands:
        k = (c["dom"], c["ext"], c["date_iso"])
        if k not in cache:
            cache[k] = pp.rapprocher(c["dom"], c["ext"], c["date_iso"], lignes_fd)
        fd, _ = cache[k]
        if fd is None:
            continue
        issue = juger(c["pick"], fd["stats"])
        if issue not in ("gagne", "perdu", "push"):
            continue
        c["issue"], c["fd_ligue"] = issue, fd["ligue"]
        cle = STAT_PAR_CATEGORIE.get(c["categorie"])
        c["p_nb"] = p_selection_nb(forces[cle], p5.STATS[cle][3], fd["dom"], fd["ext"], c["pick"]) if cle else None
        jugees.append(c)
    print(f"Paris statistiques jugés (match retrouvé dans Football-Data) : {len(jugees)} sur {len({c['match'] for c in jugees})} matchs")
    cats = sorted({c["categorie"] for c in jugees})
    print(f"\n{'catégorie':28} {'n':>5} {'Brier 1xBet':>12} {'modèle prod.':>13} {'final prod.':>12} {'Δ final-1xBet':>16} {'NB phase 5':>11} {'Δ NB-1xBet':>14}")
    for cat in ["TOUTES"] + cats:
        ens = jugees if cat == "TOUTES" else [c for c in jugees if c["categorie"] == cat]
        ev = [e for e in ens if e["issue"] != "push"]
        if len(ev) < 30:
            continue
        y = lambda e: 1.0 if e["issue"] == "gagne" else 0.0
        b = lambda cle, E=ev: [(e[cle] - y(e)) ** 2 for e in E]
        bm, bf, bp = b("p_marche"), b("p_final"), b("p_modele")
        md, ed = pm.moyenne_et_erreur_type([a - c for a, c in zip(bf, bm)])
        nb = [e for e in ev if e.get("p_nb") is not None]
        txt_nb, txt_d = "—", "—"
        if len(nb) >= 30:
            bn = [(e["p_nb"] - y(e)) ** 2 for e in nb]
            bmn = [(e["p_marche"] - y(e)) ** 2 for e in nb]
            mdn, edn = pm.moyenne_et_erreur_type([a - c for a, c in zip(bn, bmn)])
            txt_nb, txt_d = f"{sum(bn)/len(bn):.4f}", f"{mdn:+.4f}±{edn:.4f}"
        print(f"{cat[:28]:28} {len(ev):5d} {sum(bm)/len(ev):12.4f} {sum(bp)/len(ev):13.4f} {sum(bf)/len(ev):12.4f} {md:+.4f}±{ed:.4f} {txt_nb:>11} {txt_d:>14}")
    # Le moteur Phase 5 trouve-t-il un avantage face à 1xBet ? paris si p_NB >= p_marché + 3 points (cote 1xBet), référence aléatoire
    for b in jugees:
        b["clv_ref"] = None
    nb_bets = [b for b in jugees if b.get("p_nb") is not None and b["issue"] != "push"]
    choisis = [b for b in nb_bets if b["p_nb"] - b["p_marche"] >= 0.03]
    print(f"\n=== Paris du moteur Phase 5 (p_NB ≥ p_1xBet + 3 pts) : {len(choisis)} sur {len(nb_bets)} possibles ===")
    if choisis:
        print(pr.comparer(nb_bets, choisis, 1000, 2026))
        print("  par catégorie : " + " ; ".join(f"{cat} n={r['n']} ROI={r['roi']*100:+.1f}%" for cat in sorted({b['categorie'] for b in choisis})
                                                for r in [pr.resume([b for b in choisis if b['categorie'] == cat])] if r["n"]))


if __name__ == "__main__":
    main()
