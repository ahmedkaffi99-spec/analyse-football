"""Backtest des HORS-JEUX (22/10/2026) : la statistique « Offsides » n'existe pas dans hist_matchs, donc elle
est échantillonnée en mémoire depuis API-Football (GET /fixtures + /fixtures/statistics), AUCUNE écriture en
base. Walk-forward : mu d'un match = moyenne des hors-jeux de chaque équipe sur ses 10 matchs précédents
(dans l'échantillon), lissée vers HORS_JEUX_PRIOR comme en production (ae._mu_direct, Poisson sans
surdispersion). Mesure : biais du mu, rapport variance/mu résiduel (la dispersion à utiliser), calibration des
totaux, des totaux par équipe et des handicaps.
"""

import math
import os
from collections import defaultdict

import analyser_et_envoyer as ae
import backtest_marches_absents as bt
from moteur.features import Historique, en_datetime
from moteur.modeles import marches as mm

LIGUES = {39: "Premier League", 140: "La Liga"}
SAISONS = (2025, 2024)
NB_MAX_MATCHS = int(os.getenv("HJ_MAX_MATCHS") or 760)
FENETRE = 10


def construire_matchs(fixtures_avec_stats):
    """[(fixture API-Football, bloc_stats_domicile, bloc_stats_exterieur)] -> matchs au format moteur
    (stats.home.offsides / stats.away.offsides). Un match sans hors-jeux suivis est ignoré."""
    import collecte_donnees as cd
    matchs = []
    for fx, bloc_dom, bloc_ext in fixtures_avec_stats:
        oh, oa = cd._valeur_stat(bloc_dom, "Offsides"), cd._valeur_stat(bloc_ext, "Offsides")
        goals = fx.get("goals") or {}
        if oh is None or oa is None or goals.get("home") is None:
            continue
        matchs.append({"match_id": fx["fixture"]["id"], "date": fx["fixture"]["date"],
                       "competition_id": fx["league"]["id"], "saison": fx["league"].get("season"),
                       "home_id": fx["teams"]["home"]["id"], "away_id": fx["teams"]["away"]["id"],
                       "home_score": goals["home"], "away_score": goals["away"],
                       "stats": {"home": {"offsides": oh}, "away": {"offsides": oa}}})
    return matchs


def evaluer(matchs):
    """Renvoie (Collecteur, diagnostics) — diagnostics : biais de mu, variance résiduelle/mu, moyenne observée."""
    col = bt.Collecteur()
    hist = Historique(matchs)
    mus, observes, residus = [], [], []
    for m in sorted(matchs, key=lambda x: en_datetime(x["date"])):
        t = en_datetime(m["date"])
        vh, va = hist.equipe_avant(m["home_id"], t, n=FENETRE), hist.equipe_avant(m["away_id"], t, n=FENETRE)
        if len(vh) < bt.NB_MIN_MATCHS_EQUIPE or len(va) < bt.NB_MIN_MATCHS_EQUIPE:
            continue
        sd = lambda v: {"hors_jeux_moyenne": sum(x["stats_pour"]["offsides"] for x in v) / len(v),
                        "matchs_avec_donnees": len(v)}
        mu = ae.calculer_mu_hors_jeux_depuis_stats_detaillees(sd(vh), sd(va))
        if not mu:
            continue
        oh, oa = m["stats"]["home"]["offsides"], m["stats"]["away"]["offsides"]
        mus.append(sum(mu))
        observes.append(oh + oa)
        residus.append((oh + oa - sum(mu)) ** 2 / sum(mu))
        dist_h, dist_a = ae._distribution_comptage(mu[0]), ae._distribution_comptage(mu[1])
        total = ae._distribution_comptage(sum(mu))
        base = math.floor(sum(mu)) + 0.5
        for ligne in (base - 1, base, base + 1):
            over = dict.fromkeys(mm.ISSUES, 0.0)
            for k, p in enumerate(total):
                over[mm.issue_total(k, ligne, "over")] += p
            col.issues("Total hors-jeux (over/under)", over, mm.issue_total(oh + oa, ligne, "over"))
        for equipe, (mu_e, dist, reel) in enumerate(((mu[0], dist_h, oh), (mu[1], dist_a, oa)), start=1):
            b = math.floor(mu_e) + 0.5
            for ligne in (b - 1, b, b + 1):
                over = dict.fromkeys(mm.ISSUES, 0.0)
                for k, p in enumerate(dist):
                    over[mm.issue_total(k, ligne, "over")] += p
                col.issues(f"Total hors-jeux équipe {equipe} (over/under)", over, mm.issue_total(reel, ligne, "over"))
        diff = bt._issues_diff(dist_h, dist_a)
        for ligne in (-1.5, -0.5, 0.5, 1.5):
            col.issues(f"Handicap hors-jeux, ligne {ligne:+g}", bt._issues_handicap_diff(diff, ligne),
                       mm.issue_ligne(oh - oa, ligne))
    n = len(mus)
    diag = {"n": n, "mu_moyen": sum(mus) / n if n else None, "observe_moyen": sum(observes) / n if n else None,
            "variance_residuelle_sur_mu": sum(residus) / n if n else None,
            "observe_par_equipe": sum(observes) / (2 * n) if n else None, "prior": ae.HORS_JEUX_PRIOR}
    return col, diag


def charger_depuis_api():  # pragma: no cover — appels réseau réels, lancé par diagnostics.yml
    import collecte_donnees as cd
    import requests
    fixtures_avec_stats = []
    for ligue, nom in LIGUES.items():
        for saison in SAISONS:
            r = requests.get(f"{ae_base()}/fixtures", headers={"x-apisports-key": cd.API_FOOTBALL_KEY},
                             params={"league": ligue, "season": saison, "status": "FT"}, timeout=30)
            fixtures = sorted(r.json().get("response") or [], key=lambda f: f["fixture"]["date"])
            print(f"{nom} {saison} : {len(fixtures)} match(s) terminé(s).")
            for fx in fixtures:
                if len(fixtures_avec_stats) >= NB_MAX_MATCHS:
                    break
                try:
                    blocs = cd._appel_statistiques_fixture(fx["fixture"]["id"])
                except Exception as e:
                    print(f"   ⚠️ statistiques indisponibles ({fx['fixture']['id']}) : {e}")
                    continue
                par_equipe = {b["team"]["id"]: b.get("statistics") for b in blocs if b.get("team")}
                fixtures_avec_stats.append((fx, par_equipe.get(fx["teams"]["home"]["id"]),
                                            par_equipe.get(fx["teams"]["away"]["id"])))
    return fixtures_avec_stats


def ae_base():
    import adaptateur_api_football as adf
    return adf.API_FOOTBALL_BASE


if __name__ == "__main__":  # pragma: no cover
    matchs = construire_matchs(charger_depuis_api())
    print(f"\n{len(matchs)} match(s) avec hors-jeux suivis.")
    col, diag = evaluer(matchs)
    print(f"\nDiagnostic du mu : n={diag['n']}  mu moyen={diag['mu_moyen']:.2f}  observé moyen={diag['observe_moyen']:.2f}  "
          f"biais={diag['mu_moyen'] - diag['observe_moyen']:+.2f}  variance résiduelle/mu={diag['variance_residuelle_sur_mu']:.2f}  "
          f"observé par équipe={diag['observe_par_equipe']:.2f} (prior production {diag['prior']})\n")
    bt.imprimer(col)
