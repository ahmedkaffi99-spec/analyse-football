"""Comparaison d'approches (point 9) sur des cibles binaires, en walk-forward PAR SAISON :
pour la saison S, entraînement sur toutes les saisons < S (features à date), test sur S.
Le modèle retenu pour un marché est celui qui a le meilleur Brier HORS ÉCHANTILLON, pas le plus
populaire ni le meilleur sur l'historique d'entraînement.

scikit-learn est optionnel : absent, seule l'approche Poisson est évaluée (signalé).
"""

from moteur.calibration import brier
from moteur.features import Historique, construire_features, est_termine
from moteur.modeles.registre import predire_match

CIBLES = {
    "victoire_domicile": ("resultat", None, "1"),
    "over_2_5": ("buts_total", 2.5, "over"),
    "btts_oui": ("btts", None, "oui"),
    "equipe1_over_0_5": ("buts_equipe1", 0.5, "over"),
    "corners_over_9_5": ("corners_total", 9.5, "over"),
    "cartons_over_3_5": ("cartons_total", 3.5, "over"),
}
VARIABLES = ["elo_difference", "difference_buts_3", "difference_buts_5", "difference_buts_10"]
VARIABLES_EQUIPE = ["buts_pour_moy_5", "buts_contre_moy_5", "buts_pour_moy_10", "buts_contre_moy_10",
                    "buts_pour_moy_dom", "buts_contre_moy_dom", "buts_pour_moy_ext", "buts_contre_moy_ext",
                    "points_par_match", "corners_pour_moy", "corners_contre_moy", "yellow_cards_pour_moy",
                    "yellow_cards_contre_moy", "shots_pour_moy", "shots_contre_moy"]


def vecteur(f):
    v = [f.get(k) for k in VARIABLES]
    for cote in ("home", "away"):
        v += [f[cote].get(k) for k in VARIABLES_EQUIPE]
    v.append(f["arbitre_cartons_moy"])
    return [0.0 if x is None else float(x) for x in v]


def _jeu(matchs, cfg):
    from moteur.modeles.registre import issue_reelle

    hist = Historique(matchs)
    lignes = []
    for m in matchs:
        if not est_termine(m):
            continue
        f = construire_features(m, hist, cfg.fenetre_forme)
        preds = {(p.marche, p.ligne, p.selection): p.probabilite for p in predire_match(f, cfg)}
        if not preds:
            continue
        cibles = {}
        for nom, (marche, ligne, sel) in CIBLES.items():
            issue = issue_reelle(m, marche, ligne, sel)
            if issue is not None and (marche, ligne, sel) in preds:
                cibles[nom] = (1 if issue == "gagne" else 0, preds[(marche, ligne, sel)])
        lignes.append({"saison": m.get("saison"), "x": vecteur(f), "cibles": cibles})
    return lignes


def comparer(matchs, cfg):
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        approches_ml = {
            "regression_logistique": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
            "gradient_boosting": lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200),
        }
    except ImportError:
        approches_ml = {}
    jeu = _jeu(matchs, cfg)
    saisons = sorted({ln["saison"] for ln in jeu})
    resultats = {"scikit_learn": bool(approches_ml), "saisons": saisons, "cibles": {}}
    for cible in CIBLES:
        points = {"poisson": []}
        points.update({nom: [] for nom in approches_ml})
        for s in saisons[1:]:
            train = [ln for ln in jeu if ln["saison"] < s and cible in ln["cibles"]]
            test = [ln for ln in jeu if ln["saison"] == s and cible in ln["cibles"]]
            if len(train) < 100 or not test or len({ln["cibles"][cible][0] for ln in train}) < 2:
                continue
            points["poisson"] += [(ln["cibles"][cible][1], ln["cibles"][cible][0]) for ln in test]
            for nom, fabrique in approches_ml.items():
                modele = fabrique().fit([ln["x"] for ln in train], [ln["cibles"][cible][0] for ln in train])
                probas = modele.predict_proba([ln["x"] for ln in test])[:, 1]
                points[nom] += [(float(p), ln["cibles"][cible][0]) for p, ln in zip(probas, test)]
        scores = {nom: {"n": len(pts), "brier": round(brier(pts), 4)} for nom, pts in points.items() if pts}
        meilleur = min(scores, key=lambda k: scores[k]["brier"]) if scores else None
        resultats["cibles"][cible] = {"scores": scores, "meilleur_hors_echantillon": meilleur}
    return resultats
