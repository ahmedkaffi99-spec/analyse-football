"""Backtest chronologique (walk-forward), sans aucune information future :
1. features calculées à la date du match (features.Historique ne voit que le passé) ;
2. prédiction des 10 modèles ;
3. calibration ajustée UNIQUEMENT sur les prédictions des mois précédents ;
4. cote : dernier relevé STRICTEMENT antérieur au coup d'envoi (sinon : pas de ROI pour cette
   prédiction, seulement Brier/calibration) ;
5. résultat lu APRÈS, sur le score/les statistiques finales.

Les résultats négatifs sont rapportés tels quels.
"""

from collections import defaultdict

from moteur import calibration as calib
from moteur import cotes as mcotes
from moteur.features import Historique, construire_features, en_datetime, est_termine
from moteur.modeles import marches
from moteur.modeles.registre import predire_match, issue_reelle
from moteur.selection import Candidat, composer_coupon, filtrer

LIGNES_BACKTEST = {
    "handicap": [-1.5, -0.5, 0.5, 1.5],
    "buts_total": [1.5, 2.5, 3.5], "buts_equipe1": [0.5, 1.5], "buts_equipe2": [0.5, 1.5],
    "corners_total": [8.5, 9.5, 10.5], "corners_equipe1": [3.5, 4.5], "corners_equipe2": [3.5, 4.5],
    "cartons_total": [3.5, 4.5], "cartons_equipe1": [1.5], "cartons_equipe2": [1.5],
    "tirs_total": [22.5, 24.5], "tirs_equipe1": [10.5], "tirs_equipe2": [10.5],
    "tirs_cadres_total": [7.5, 8.5], "tirs_cadres_equipe1": [3.5], "tirs_cadres_equipe2": [3.5],
}


class Ligne:
    __slots__ = ("match_id", "date", "mois", "competition", "saison", "libelle", "modele", "marche", "ligne",
                 "selection", "proba_brute", "proba", "calibre", "n_calibration", "binaire", "issue", "cote",
                 "parametres")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    @property
    def gagne(self):
        return 1 if self.issue == "gagne" else 0

    def candidat(self):
        return Candidat(self.match_id, self.libelle, self.date, self.competition, self.modele, self.marche,
                        self.ligne, self.selection, self.proba_brute, self.proba, self.calibre, self.n_calibration,
                        self.binaire, self.cote, mcotes.edge(self.proba, self.cote) if self.cote else None,
                        self.parametres)


def _cote_avant(releves, coup_envoi, marche, ligne, selection):
    meilleur = None
    for r in releves or []:
        if r["marche"] == marche and r.get("ligne") == ligne and r["selection"] == selection \
                and en_datetime(r["horodatage"]) < coup_envoi:
            if meilleur is None or en_datetime(r["horodatage"]) > en_datetime(meilleur["horodatage"]):
                meilleur = r
    return meilleur["cote"] if meilleur else None


def generer_lignes(matchs, cotes_par_match, cfg, debut, fin, lignes=None):
    hist = Historique(matchs)
    debut, fin = en_datetime(debut), en_datetime(fin)
    a_tester = sorted((m for m in matchs if est_termine(m) and debut <= en_datetime(m["date"]) < fin),
                      key=lambda m: en_datetime(m["date"]))
    resultat = []
    for m in a_tester:
        t = en_datetime(m["date"])
        releves = cotes_par_match.get(m["match_id"], [])
        lignes_match = {k: list(v) for k, v in (lignes or LIGNES_BACKTEST).items()}
        for r in releves:
            if r.get("ligne") is not None and r["marche"] in lignes_match and r["ligne"] not in lignes_match[r["marche"]]:
                lignes_match[r["marche"]].append(r["ligne"])
        features = construire_features(m, hist, cfg.fenetre_forme)
        for p in predire_match(features, cfg, lignes_match):
            issue = issue_reelle(m, p.marche, p.ligne, p.selection)
            if issue is None:
                continue
            resultat.append(Ligne(
                match_id=m["match_id"], date=t, mois=(t.year, t.month), competition=m.get("competition"),
                saison=m.get("saison"), libelle=f"{m.get('home')} vs {m.get('away')}", modele=p.modele,
                marche=p.marche, ligne=p.ligne, selection=p.selection, proba_brute=p.probabilite,
                proba=p.probabilite, calibre=False, n_calibration=0, binaire=p.binaire, issue=issue,
                cote=_cote_avant(releves, t, p.marche, p.ligne, p.selection), parametres=p.parametres))
    return resultat


def calibrer_walk_forward(lignes, cfg):
    """Chaque mois est calibré avec les mois STRICTEMENT antérieurs."""
    par_mois = defaultdict(list)
    for ln in lignes:
        par_mois[ln.mois].append(ln)
    passe = []
    for mois in sorted(par_mois):
        cal = calib.Calibrateur(cfg.calibration_min_n).ajuster(passe)
        for ln in par_mois[mois]:
            if ln.binaire:
                ln.proba, ln.n_calibration, ln.calibre = cal.calibrer(ln.modele, ln.marche, ln.proba_brute)
        passe.extend((ln.modele, ln.marche, ln.proba_brute, ln.gagne) for ln in par_mois[mois] if ln.binaire)
    return lignes


def _serie_et_drawdown(profits):
    cumul = pic = dd = 0.0
    serie = pire = 0
    for p in profits:
        cumul += p
        pic = max(pic, cumul)
        dd = max(dd, pic - cumul)
        serie = serie + 1 if p < 0 else 0
        pire = max(pire, serie)
    return dd, pire


def metriques(lignes, cfg, paris=False):
    """paris=False : qualité des probabilités (toutes les prédictions binaires).
    paris=True : simulation de mise sur les lignes fournies (doivent avoir une cote)."""
    binaires = [ln for ln in lignes if ln.binaire]
    points = [(ln.proba, ln.gagne) for ln in binaires]
    m = {"n_predictions": len(binaires), "n_gagnants": sum(y for _, y in points),
         "win_rate": round(sum(y for _, y in points) / len(points), 4) if points else None,
         "brier": round(calib.brier(points), 4) if points else None,
         "log_loss": round(calib.log_loss(points), 4) if points else None,
         "calibration": calib.tableau_fiabilite(points)}
    if paris:
        avec_cote = [ln for ln in lignes if ln.cote]
        profits = [marches.profit(ln.issue, ln.cote, cfg.mise) for ln in avec_cote]
        dd, pire = _serie_et_drawdown(profits)
        m.update({"n_paris": len(avec_cote), "profit": round(sum(profits), 2),
                  "roi": round(sum(profits) / (cfg.mise * len(avec_cote)), 4) if avec_cote else None,
                  "drawdown_max": round(dd, 2), "plus_longue_serie_perdante": pire,
                  "cote_moyenne": round(sum(ln.cote for ln in avec_cote) / len(avec_cote), 3) if avec_cote else None,
                  "edge_moyen": round(sum(mcotes.edge(ln.proba, ln.cote) for ln in avec_cote) / len(avec_cote), 4)
                  if avec_cote else None})
    return m


def par_groupe(lignes, cle, cfg, paris=False):
    groupes = defaultdict(list)
    for ln in lignes:
        groupes[cle(ln)].append(ln)
    return {str(k): metriques(v, cfg, paris) for k, v in sorted(groupes.items(), key=lambda kv: str(kv[0]))}


def tranche(p):
    for bas, haut in calib.TRANCHES:
        if bas <= p < haut:
            return f"{int(bas * 100)}-{min(int(haut * 100), 100)}%"
    return "?"


def selectionner(lignes, cfg):
    candidats = [ln.candidat() for ln in lignes if ln.cote]
    retenus = {(c.match_id, c.marche, c.ligne, c.selection) for c in filtrer(candidats, cfg)}
    return [ln for ln in lignes if (ln.match_id, ln.marche, ln.ligne, ln.selection) in retenus]


def tester_seuils(lignes, cfg, edges=(None, 0.03, 0.05, 0.07, 0.10), probas=(0.70, 0.75, 0.80, 0.85), n_min=30):
    """Grille choisie sur la 1re moitié chronologique (validation), puis rapportée sur la 2nde
    (test, hors échantillon). Le meilleur seuil passé n'est PAS considéré comme acquis."""
    avec_cote = sorted((ln for ln in lignes if ln.cote), key=lambda ln: ln.date)
    if len(avec_cote) < 2:
        return {"disponible": False, "raison": "aucune cote historique antérieure aux matchs"}
    coupure = avec_cote[len(avec_cote) // 2].date
    validation = [ln for ln in avec_cote if ln.date < coupure]
    test = [ln for ln in avec_cote if ln.date >= coupure]
    grille = []
    for e in edges:
        for p in probas:
            variante = type(cfg)(**{**cfg.__dict__, "proba_min": p, "edge_min": -1.0 if e is None else e})
            mv = metriques(selectionner(validation, variante), variante, paris=True)
            mt = metriques(selectionner(test, variante), variante, paris=True)
            grille.append({"edge_min": e, "proba_min": p, "validation": mv, "test": mt})
    eligibles = [g for g in grille if (g["validation"]["n_paris"] or 0) >= n_min and g["validation"]["roi"] is not None]
    choix = max(eligibles, key=lambda g: g["validation"]["roi"]) if eligibles else None
    return {"disponible": True, "coupure": coupure.isoformat(), "grille": grille,
            "choix_validation": {"edge_min": choix["edge_min"], "proba_min": choix["proba_min"],
                                 "roi_validation": choix["validation"]["roi"], "roi_test": choix["test"]["roi"],
                                 "n_paris_test": choix["test"]["n_paris"]} if choix else None}


def backtest_coupons(lignes, cfg):
    par_jour = defaultdict(list)
    for ln in selectionner(lignes, cfg):
        par_jour[ln.date.date()].append(ln)
    coupons = []
    for jour in sorted(par_jour):
        lignes_jour = {(ln.match_id, ln.marche, ln.ligne, ln.selection): ln for ln in par_jour[jour]}
        coupon = composer_coupon([ln.candidat() for ln in par_jour[jour]], cfg)
        if not coupon["genere"]:
            continue
        issues = [lignes_jour[(j.match_id, j.marche, j.ligne, j.selection)].issue for j in coupon["jambes"]]
        gagne = all(i == "gagne" for i in issues)
        coupons.append({"jour": jour.isoformat(), "jambes": len(issues), "cote": coupon["cote_totale"],
                        "proba_annoncee": coupon["proba_combinee"], "gagne": gagne,
                        "profit": cfg.mise * (coupon["cote_totale"] - 1) if gagne else -cfg.mise})
    profits = [c["profit"] for c in coupons]
    dd, pire = _serie_et_drawdown(profits)
    return {"n_coupons": len(coupons), "n_gagnants": sum(c["gagne"] for c in coupons),
            "cote_moyenne": round(sum(c["cote"] for c in coupons) / len(coupons), 2) if coupons else None,
            "proba_annoncee_moyenne": round(sum(c["proba_annoncee"] for c in coupons) / len(coupons), 4) if coupons else None,
            "mise_totale": cfg.mise * len(coupons), "profit": round(sum(profits), 2),
            "roi": round(sum(profits) / (cfg.mise * len(coupons)), 4) if coupons else None,
            "drawdown_max": round(dd, 2), "plus_longue_serie_perdante": pire, "detail": coupons}


def executer(matchs, cotes_par_match, cfg, debut, fin, lignes=None):
    lignes_bt = calibrer_walk_forward(generer_lignes(matchs, cotes_par_match, cfg, debut, fin, lignes), cfg)
    retenues = selectionner(lignes_bt, cfg)
    return {
        "periode": {"debut": str(debut), "fin": str(fin)},
        "global": metriques(lignes_bt, cfg),
        "par_modele": par_groupe(lignes_bt, lambda ln: ln.modele, cfg),
        "par_marche": par_groupe(lignes_bt, lambda ln: ln.marche, cfg),
        "par_competition": par_groupe(lignes_bt, lambda ln: ln.competition, cfg),
        "par_saison": par_groupe(lignes_bt, lambda ln: ln.saison, cfg),
        "par_tranche": par_groupe(lignes_bt, lambda ln: tranche(ln.proba), cfg),
        "selection": metriques(retenues, cfg, paris=True),
        "selection_par_modele": par_groupe(retenues, lambda ln: ln.modele, cfg, paris=True),
        "seuils": tester_seuils(lignes_bt, cfg),
        "coupons": backtest_coupons(lignes_bt, cfg),
        "_lignes": lignes_bt,
    }
