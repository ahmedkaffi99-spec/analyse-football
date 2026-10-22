"""Backtest walk-forward des marchés ABSENTS des coupons ou jamais validés (22/10/2026, demande
explicite : « backtest tout ce qui est absent »).

Aucune fuite du futur : pour chaque match, seules les données des matchs STRICTEMENT antérieurs servent
(moteur.features.Historique). Les probabilités viennent des fonctions de PRODUCTION de
analyser_et_envoyer (mêmes mu buts forme + H2H + Elo, mêmes mu corners/tirs/fautes/cartons, mêmes lois,
même EV exacte des remboursements) — jamais une réimplémentation parallèle.

Marchés couverts : BTTS, handicap de buts, pair/impair, clean sheet, win-to-nil, score exact (modal),
handicaps de corners/cartons/tirs cadrés/fautes/tirs, totaux PAR ÉQUIPE de corners/cartons/tirs cadrés/
fautes/tirs. Non couvert ici : hors-jeux (statistique absente de hist_matchs, voir backtest_hors_jeux),
mi-temps (pas de score à la mi-temps dans l'historique).

Lecture d'un résultat : pour chaque marché, on garde le côté PROBABLE (p >= 0.5) de chaque événement et on
compare la probabilité annoncée à la fréquence réelle par tranche ; les remboursements (lignes entières)
sont écartés du calcul de fréquence et p est ramenée à p_gain / (1 - p_remboursement).
"""

import math
from collections import defaultdict

import analyser_et_envoyer as ae
from moteur import calibration as calib
from moteur.features import Historique, en_datetime, est_termine
from moteur.modeles import marches as mm

NB_MIN_MATCHS_EQUIPE = 5
AVANTAGE_DOMICILE_DESACTIVE = bool(__import__("os").getenv("BACKTEST_SANS_AVANTAGE_DOMICILE"))
TRANCHES = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0001))
SEUIL_ECART_PTS = 3.0     # |réel - annoncé| toléré dans la tranche >= 70 %
N_MIN_VERDICT = 150

# famille -> (champ de statistique, forme du calcul de mu, prior, dispersion, lignes de handicap)
FAMILLES_COMPTAGE = {
    "corners": ("corners", "ad", ae.CORNERS_PRIOR, 1.16, (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)),
    "cartons": ("yellow_cards", "direct", ae.CARTONS_PRIOR, 1.0, (-1.5, -0.5, 0.5, 1.5)),
    "tirs_cadres": ("shots_on_target", "ad", ae.TIRS_CADRES_PRIOR, 1.10, (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)),
    "fautes": ("fouls", "ad", ae.FAUTES_PRIOR, 1.22, (-3.5, -1.5, -0.5, 0.5, 1.5, 3.5)),
    "tirs": ("shots", "ad", ae.TIRS_PRIOR, 1.34, (-4.5, -2.5, -0.5, 0.5, 2.5, 4.5)),
}
LIGNES_BUTS = (-2.5, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.5)


def _moyennes(vues, champ):
    pour = [v["stats_pour"].get(champ) for v in vues if v["stats_pour"].get(champ) is not None]
    contre = [v["stats_contre"].get(champ) for v in vues if v["stats_contre"].get(champ) is not None]
    if len(pour) < NB_MIN_MATCHS_EQUIPE or len(contre) < NB_MIN_MATCHS_EQUIPE:
        return None
    return {"pour": sum(pour) / len(pour), "contre": sum(contre) / len(contre), "n": min(len(pour), len(contre))}


def _mu_buts(m, hist, par_paire, t):
    """(mu_home, mu_away) buts : forme 10 matchs -> H2H -> Elo, exactement comme la production."""
    vh, va = hist.equipe_avant(m["home_id"], t, n=10), hist.equipe_avant(m["away_id"], t, n=10)
    if len(vh) < NB_MIN_MATCHS_EQUIPE or len(va) < NB_MIN_MATCHS_EQUIPE:
        return None

    def sd(v):
        return {"buts_marques_moyenne": sum(x["buts_pour"] for x in v) / len(v),
                "buts_encaisses_moyenne": sum(x["buts_contre"] for x in v) / len(v), "matchs_avec_donnees": len(v)}

    xg = ae.calculer_xg_depuis_stats_detaillees(sd(vh), sd(va))
    if not xg:
        return None
    confrontations = [c for c in par_paire.get(frozenset((m["home_id"], m["away_id"])), [])
                      if en_datetime(c["date"]) < t][-10:]
    if confrontations:
        bh = sum(c["home_score"] if c["home_id"] == m["home_id"] else c["away_score"] for c in confrontations)
        ba = sum(c["away_score"] if c["home_id"] == m["home_id"] else c["home_score"] for c in confrontations)
        xg = ae._ponderer_avec_h2h(*xg, {"matchs_analyses": len(confrontations),
                                         "buts_home_moyenne": bh / len(confrontations),
                                         "buts_away_moyenne": ba / len(confrontations)})
    elo_h, elo_a = hist.elo(m)
    return ae._ajuster_avec_elo(xg[0], xg[1], {"elo_home": elo_h, "elo_away": elo_a})


def _mu_comptage(famille, vh, va):
    champ, forme, prior = FAMILLES_COMPTAGE[famille][:3]
    mh, ma = _moyennes(vh, champ), _moyennes(va, champ)
    if not mh or not ma:
        return None
    if forme == "ad":
        mu = ae._mu_attaque_defense({"p": mh["pour"], "c": mh["contre"], "matchs_avec_donnees": mh["n"]},
                                    {"p": ma["pour"], "c": ma["contre"], "matchs_avec_donnees": ma["n"]},
                                    "p", "c", prior)
    else:
        mu = ae._mu_direct({"p": mh["pour"], "matchs_avec_donnees": mh["n"]},
                           {"p": ma["pour"], "matchs_avec_donnees": ma["n"]}, "p", prior)
    # même ajustement que la production (analyser_et_envoyer.appliquer_avantage_domicile) ; désactivable pour
    # mesurer l'effet : BACKTEST_SANS_AVANTAGE_DOMICILE=1
    return mu if AVANTAGE_DOMICILE_DESACTIVE else ae.appliquer_avantage_domicile(famille, mu)


class Collecteur:
    """{marché: [(p_annoncee, issue 0/1)]} — uniquement le côté probable, remboursements écartés."""

    def __init__(self):
        self.points = defaultdict(list)

    def issues(self, marche, issues_modele, issue_reelle):
        """issues_modele : dict des 5 issues (probabilités) ; issue_reelle : 'gagne' / 'perdu' / ..."""
        g = issues_modele["gagne"] + issues_modele["demi_gagne"] * 0.5
        p_ = issues_modele["perdu"] + issues_modele["demi_perdu"] * 0.5
        if g + p_ <= 1e-12 or issue_reelle in ("rembourse",):
            return
        p_gain = g / (g + p_)
        gagne = 1 if issue_reelle in ("gagne", "demi_gagne") else 0
        if p_gain >= 0.5:
            self.points[marche].append((p_gain, gagne))
        else:
            self.points[marche].append((1 - p_gain, 1 - gagne))

    def binaire(self, marche, p, evenement):
        if p >= 0.5:
            self.points[marche].append((p, 1 if evenement else 0))
        else:
            self.points[marche].append((1 - p, 0 if evenement else 1))


def _issues_diff(d_pour, d_contre):
    """pmf de (X - Y) pour deux lois indépendantes : {écart: proba}."""
    diff = defaultdict(float)
    for i, pi in enumerate(d_pour):
        for j, pj in enumerate(d_contre):
            diff[i - j] += pi * pj
    return diff


def _issues_handicap_diff(diff, ligne):
    r = dict.fromkeys(mm.ISSUES, 0.0)
    for ecart, p in diff.items():
        r[mm.issue_ligne(ecart, ligne)] += p
    return r


def _evaluer_match(col, m, mu_buts, mus):
    h, a = m["home_score"], m["away_score"]
    mu_h, mu_a = mu_buts
    # --- buts ---
    col.binaire("BTTS (oui/non)", ae.proba_btts(mu_h, mu_a), h > 0 and a > 0)
    col.binaire("Pair/Impair des buts", ae.proba_total_impair(mu_h + mu_a), (h + a) % 2 == 1)
    col.binaire("Clean sheet équipe 1", ae.proba_clean_sheet(mu_a), a == 0)
    col.binaire("Clean sheet équipe 2", ae.proba_clean_sheet(mu_h), h == 0)
    col.binaire("Win To Nil équipe 1", ae.proba_win_to_nil(mu_h, mu_a), h > a and a == 0)
    col.binaire("Win To Nil équipe 2", ae.proba_win_to_nil(mu_a, mu_h), a > h and h == 0)
    d_h, d_a = ae._distribution_comptage(mu_h), ae._distribution_comptage(mu_a)
    diff = _issues_diff(d_h, d_a)
    for ligne in LIGNES_BUTS:
        col.issues(f"Handicap buts, ligne {ligne:+g}", _issues_handicap_diff(diff, ligne),
                   mm.issue_ligne(h - a, ligne))
    # score exact : le score le plus probable selon le modèle, comparé au score réellement joué
    p_max, meilleur = max(((pi * pj, (i, j)) for i, pi in enumerate(d_h) for j, pj in enumerate(d_a)))
    col.points["Score exact (score le plus probable)"].append((p_max, 1 if (h, a) == meilleur else 0))
    # --- comptages ---
    stats = m.get("stats") or {}
    for famille, (champ, _, _, disp, lignes) in FAMILLES_COMPTAGE.items():
        mu = mus.get(famille)
        sh, sa = (stats.get("home") or {}).get(champ), (stats.get("away") or {}).get(champ)
        if not mu or sh is None or sa is None:
            continue
        dist_h, dist_a = ae._distribution_comptage(mu[0], disp), ae._distribution_comptage(mu[1], disp)
        diff = _issues_diff(dist_h, dist_a)
        for ligne in lignes:
            col.issues(f"Handicap {famille}, ligne {ligne:+g}", _issues_handicap_diff(diff, ligne),
                       mm.issue_ligne(sh - sa, ligne))
        for equipe, (mu_e, dist, reel) in enumerate(((mu[0], dist_h, sh), (mu[1], dist_a, sa)), start=1):
            base = math.floor(mu_e) + 0.5
            for ligne in (base - 1, base, base + 1):
                over = {k: 0.0 for k in mm.ISSUES}
                for k, p in enumerate(dist):
                    over[mm.issue_total(k, ligne, "over")] += p
                col.issues(f"Total {famille} équipe {equipe} (over/under)", over, mm.issue_total(reel, ligne, "over"))


def executer(matchs_par_competition):
    """matchs_par_competition : {id: [match, ...]} au format moteur.features. Renvoie le Collecteur."""
    col = Collecteur()
    for matchs in matchs_par_competition.values():
        hist = Historique(matchs)
        par_paire = defaultdict(list)
        for m in matchs:
            if est_termine(m):
                par_paire[frozenset((m["home_id"], m["away_id"]))].append(m)
        for paire in par_paire.values():
            paire.sort(key=lambda x: en_datetime(x["date"]))
        for m in sorted((m for m in matchs if est_termine(m)), key=lambda x: en_datetime(x["date"])):
            t = en_datetime(m["date"])
            mu_buts = _mu_buts(m, hist, par_paire, t)
            if not mu_buts:
                continue
            vh, va = hist.equipe_avant(m["home_id"], t, n=10), hist.equipe_avant(m["away_id"], t, n=10)
            mus = {f: _mu_comptage(f, vh, va) for f in FAMILLES_COMPTAGE}
            _evaluer_match(col, m, mu_buts, mus)
    return col


def resumer(points):
    """Statistiques d'un marché : n, annoncé moyen, réel moyen, Brier, tranches, verdict."""
    n = len(points)
    if not n:
        return None
    brier = sum((p - y) ** 2 for p, y in points) / n
    tranches = []
    for bas, haut in TRANCHES:
        dans = [(p, y) for p, y in points if bas <= p < haut]
        if dans:
            tranches.append({"tranche": f"{int(bas * 100)}-{min(int(haut * 100), 100)}%", "n": len(dans),
                             "annonce": sum(p for p, _ in dans) / len(dans), "reel": sum(y for _, y in dans) / len(dans)})
    hautes = [(p, y) for p, y in points if p >= 0.7]
    verdict = "n insuffisant (< %d paris à >= 70 %%)" % N_MIN_VERDICT
    ecart = None
    if len(hautes) >= N_MIN_VERDICT:
        ecart = 100 * (sum(y for _, y in hautes) / len(hautes) - sum(p for p, _ in hautes) / len(hautes))
        verdict = ("CALIBRÉ" if abs(ecart) <= SEUIL_ECART_PTS else
                   "SUR-ESTIMÉ (modèle trop confiant)" if ecart < 0 else "SOUS-ESTIMÉ (modèle prudent)")
    return {"n": n, "annonce": sum(p for p, _ in points) / n, "reel": sum(y for _, y in points) / n,
            "brier": brier, "tranches": tranches, "n_hautes": len(hautes), "ecart_hautes_pts": ecart,
            "verdict": verdict}


def imprimer(col):
    lignes = []
    for marche in sorted(col.points):
        r = resumer(col.points[marche])
        ecart = "" if r["ecart_hautes_pts"] is None else f" écart>=70%={r['ecart_hautes_pts']:+.1f} pts"
        lignes.append(f"{marche:48s} n={r['n']:6d} annoncé={100 * r['annonce']:5.1f}% réel={100 * r['reel']:5.1f}% "
                      f"Brier={r['brier']:.4f}{ecart} [{r['verdict']}]")
        for t in r["tranches"]:
            if t["n"] >= 30:
                lignes.append(f"      {t['tranche']:8s} n={t['n']:6d} annoncé={100 * t['annonce']:5.1f}% "
                              f"réel={100 * t['reel']:5.1f}%")
    print("\n".join(lignes))
    return lignes


def brier_par_famille(col):
    """{famille: Brier moyen} sur les handicaps ET les totaux par équipe de la famille (n pondéré)."""
    sortie = {}
    for famille in FAMILLES_COMPTAGE:
        pts = [pt for marche, lst in col.points.items()
               if marche.startswith(f"Handicap {famille},") or marche.startswith(f"Total {famille} équipe")
               for pt in lst]
        if pts:
            sortie[famille] = (sum((p - y) ** 2 for p, y in pts) / len(pts), len(pts))
    return sortie


def grille_facteurs(donnees, echelles=(0.0, 0.5, 0.75, 1.0)):
    """Rejoue le backtest avec l'avantage du terrain à échelle × (facteur mesuré - 1) et rapporte le Brier par
    famille : choix du facteur par l'erreur, pas à l'intuition. Restaure ae.FACTEUR_DOMICILE à la fin."""
    original = dict(ae.FACTEUR_DOMICILE)
    resultats = {}
    try:
        for e in echelles:
            ae.FACTEUR_DOMICILE.update({f: 1 + e * (v - 1) for f, v in original.items()})
            resultats[e] = brier_par_famille(executer(donnees))
    finally:
        ae.FACTEUR_DOMICILE.update(original)
    return resultats


def imprimer_grille(resultats):
    echelles = sorted(resultats)
    print("\n=== Brier (handicaps + totaux par équipe) selon l'échelle de l'avantage du terrain ===")
    print("famille      " + "".join(f"  échelle {e:>4.2f}" for e in echelles) + "   meilleure")
    for famille in FAMILLES_COMPTAGE:
        valeurs = {e: resultats[e][famille][0] for e in echelles if famille in resultats[e]}
        if not valeurs:
            continue
        meilleure = min(valeurs, key=valeurs.get)
        print(f"{famille:12s} " + "".join(f"  {valeurs[e]:12.4f}" for e in echelles)
              + f"   {meilleure:.2f} -> facteur {1 + meilleure * (ae.FACTEUR_DOMICILE[famille] - 1):.3f}")


if __name__ == "__main__":  # pragma: no cover — lancé par diagnostics.yml (accès base)
    import sys
    from pathlib import Path
    racine = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(racine / "backend"))
    from app.database import SessionLocal
    from app.services.historique import charger_matchs

    competitions = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
    with SessionLocal() as db:
        donnees = {cid: charger_matchs(db, competition_id=cid) for cid in competitions}
    print(f"{sum(len(v) for v in donnees.values())} matchs chargés ({', '.join(competitions.values())}).")
    if __import__("os").getenv("BACKTEST_GRILLE_DOMICILE"):
        imprimer_grille(grille_facteurs(donnees))
    else:
        imprimer(executer(donnees))
