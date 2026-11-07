"""Évaluation COMPARABLE des moteurs (agent, central, déterministe) — Brier, log loss, calibration, performance face au marché, comparaison sur les MÊMES
matchs, backtest chronologique hors échantillon, forces et faiblesses détectées automatiquement (07/11/2026).

Code pur. Aucune conclusion de supériorité sans échantillon suffisant : `comparer_moteurs` renvoie `classement_autorise = False` tant qu'un moteur a moins de
`N_MIN_COMPARAISON` paris réglés communs, et `verdict` le dit. Une « observation » est un dict :
    {"cle": (match, marche, selection), "jour": "AAAA-MM-JJ", "p": 0-1 (probabilité annoncée), "p_marche": 0-1 ou None (probabilité implicite sans marge),
     "cote": >1, "issue": 1 (gagné) / 0 (perdu) / None (non réglé), "marche": "famille de marché"}
Une observation non réglée ou sans probabilité valide est EXCLUE des statistiques principales (jamais comptée comme perdue)."""

import math
from collections import defaultdict

from moteur.calibration import Isotone, brier, log_loss, tableau_fiabilite

N_MIN_COMPARAISON = 100
N_MIN_MARCHE = 30


def _valide(o):
    return o.get("issue") in (0, 1) and o.get("p") is not None and 0.0 <= o["p"] <= 1.0 and (o.get("cote") or 0) > 1.0


def reglees(observations):
    return [o for o in observations if _valide(o)]


def metriques(observations):
    """Brier, log loss, calibration, ROI à mise 1 sur les paris réglés. Les observations non réglées sont comptées à part."""
    obs = reglees(observations)
    out = {"n_total": len(observations), "n_regle": len(obs), "n_exclu": len(observations) - len(obs)}
    if not obs:
        return dict(out, brier=None, log_loss=None, taux_reussite=None, proba_moyenne=None, ecart_calibration=None, roi=None, fiabilite=[])
    pts = [(o["p"], o["issue"]) for o in obs]
    out["brier"] = round(brier(pts), 5)
    out["log_loss"] = round(log_loss(pts), 5)
    out["taux_reussite"] = round(sum(y for _, y in pts) / len(pts), 4)
    out["proba_moyenne"] = round(sum(p for p, _ in pts) / len(pts), 4)
    out["ecart_calibration"] = round(out["taux_reussite"] - out["proba_moyenne"], 4)     # > 0 : le moteur est trop prudent ; < 0 : trop optimiste
    profit = sum((o["cote"] - 1) if o["issue"] == 1 else -1.0 for o in obs)
    out["roi"] = round(profit / len(obs), 4)
    out["fiabilite"] = tableau_fiabilite(pts)
    return out


def face_au_marche(observations):
    """Compare le moteur au marché SUR LES MÊMES observations (celles où p_marche existe) : un Brier plus bas que celui du marché = meilleure prévision."""
    obs = [o for o in reglees(observations) if o.get("p_marche") is not None and 0.0 <= o["p_marche"] <= 1.0]
    if not obs:
        return {"n": 0, "brier_moteur": None, "brier_marche": None, "gain_brier": None, "bat_le_marche": None}
    bm = brier([(o["p"], o["issue"]) for o in obs])
    bk = brier([(o["p_marche"], o["issue"]) for o in obs])
    return {"n": len(obs), "brier_moteur": round(bm, 5), "brier_marche": round(bk, 5), "gain_brier": round(bk - bm, 5),
            "bat_le_marche": bool(bm < bk), "significatif": len(obs) >= N_MIN_COMPARAISON}


def par_marche(observations):
    """Métriques par famille de marché ; une famille sous N_MIN_MARCHE paris réglés est signalée « échantillon insuffisant »."""
    groupes = defaultdict(list)
    for o in observations:
        groupes[o.get("marche") or "autre"].append(o)
    res = {}
    for m, obs in sorted(groupes.items()):
        mt = metriques(obs)
        mt["suffisant"] = mt["n_regle"] >= N_MIN_MARCHE
        res[m] = mt
    return res


def comparer_moteurs(observations_par_moteur):
    """Comparaison sur les MÊMES paris : seules les clés présentes chez TOUS les moteurs (et réglées) sont retenues, pour qu'aucun moteur ne soit avantagé par un
    échantillon différent. Renvoie métriques, face au marché, forces/faiblesses et un verdict prudent."""
    ensembles = [{o["cle"] for o in reglees(obs)} for obs in observations_par_moteur.values()]
    communes = set.intersection(*ensembles) if ensembles else set()
    communes_par = {m: [o for o in obs if o["cle"] in communes] for m, obs in observations_par_moteur.items()}
    resultat = {"n_communs": len(communes), "moteurs": {}}
    for m, obs in communes_par.items():
        resultat["moteurs"][m] = {"global": metriques(obs), "face_au_marche": face_au_marche(obs), "par_marche": par_marche(obs),
                                  "toutes_observations": metriques(observations_par_moteur[m])}
        resultat["moteurs"][m]["forces_faiblesses"] = forces_faiblesses(resultat["moteurs"][m])
    suffisant = len(communes) >= N_MIN_COMPARAISON
    resultat["classement_autorise"] = suffisant
    if not suffisant:
        resultat["verdict"] = (f"AUCUN CLASSEMENT : {len(communes)} pari(s) réglé(s) commun(s) < {N_MIN_COMPARAISON}. "
                               "Aucun moteur ne peut être déclaré meilleur.")
    else:
        classement = sorted(((m, v["global"]["brier"]) for m, v in resultat["moteurs"].items() if v["global"]["brier"] is not None), key=lambda x: x[1])
        resultat["classement_brier"] = classement
        resultat["verdict"] = ("Échantillon suffisant : classement par Brier indicatif " + " < ".join(f"{m} ({b})" for m, b in classement)
                               + ". Un écart faible n'est pas significatif (voir les intervalles et la stabilité par jour).")
    return resultat


def forces_faiblesses(bilan_moteur):
    """Constats automatiques, chiffrés, à partir du bilan d'un moteur. Jamais de jugement sans échantillon."""
    g, mk, pm = bilan_moteur["global"], bilan_moteur["face_au_marche"], bilan_moteur["par_marche"]
    forces, faiblesses = [], []
    if g["n_regle"] < N_MIN_MARCHE:
        return {"forces": [], "faiblesses": [f"échantillon insuffisant ({g['n_regle']} paris réglés)"]}
    if mk["n"] >= N_MIN_MARCHE and mk["bat_le_marche"]:
        forces.append(f"Brier meilleur que le marché ({mk['brier_moteur']} contre {mk['brier_marche']}, n={mk['n']})")
    elif mk["n"] >= N_MIN_MARCHE:
        faiblesses.append(f"Brier moins bon que le marché ({mk['brier_moteur']} contre {mk['brier_marche']}, n={mk['n']})")
    ec = g["ecart_calibration"]
    if abs(ec) <= 0.03:
        forces.append(f"calibration correcte (écart {ec:+.3f})")
    elif ec < 0:
        faiblesses.append(f"trop optimiste (taux réel {g['taux_reussite']:.3f} pour {g['proba_moyenne']:.3f} annoncé)")
    else:
        faiblesses.append(f"trop prudent (taux réel {g['taux_reussite']:.3f} pour {g['proba_moyenne']:.3f} annoncé)")
    for marche, mt in pm.items():
        if not mt["suffisant"]:
            continue
        if mt["roi"] is not None and mt["roi"] < -0.2:
            faiblesses.append(f"marché {marche} : ROI {mt['roi']:+.1%} (n={mt['n_regle']})")
        elif mt["roi"] is not None and mt["roi"] > 0.05:
            forces.append(f"marché {marche} : ROI {mt['roi']:+.1%} (n={mt['n_regle']})")
    return {"forces": forces, "faiblesses": faiblesses}


def backtest_chronologique(observations, part_apprentissage=0.5, min_n_calibration=100):
    """Backtest HORS ÉCHANTILLON : la calibration isotone est ajustée sur la première partie chronologique et évaluée sur la seconde — jamais sur les mêmes données.
    Renvoie le Brier et le log loss de la probabilité brute et de la probabilité calibrée sur la période de test, et une décision prudente sur l'utilité de calibrer."""
    obs = sorted(reglees(observations), key=lambda o: str(o.get("jour") or ""))
    n_app = int(len(obs) * part_apprentissage)
    app, test = obs[:n_app], obs[n_app:]
    if len(app) < min_n_calibration or len(test) < N_MIN_MARCHE:
        return {"disponible": False, "raison": f"échantillon insuffisant (apprentissage {len(app)}, test {len(test)})", "n_app": len(app), "n_test": len(test)}
    iso = Isotone([(o["p"], o["issue"]) for o in app])
    brut = [(o["p"], o["issue"]) for o in test]
    cal = [(iso(o["p"]), o["issue"]) for o in test]
    gain = brier(brut) - brier(cal)
    return {"disponible": True, "n_app": len(app), "n_test": len(test), "brier_brut": round(brier(brut), 5), "brier_calibre": round(brier(cal), 5),
            "log_loss_brut": round(log_loss(brut), 5), "log_loss_calibre": round(log_loss(cal), 5), "gain_brier": round(gain, 5),
            "calibration_utile": bool(gain > 0.001), "jours_test": [str(test[0].get("jour")), str(test[-1].get("jour"))]}


def stabilite_par_jour(observations):
    """Taux de réussite et Brier par jour : un résultat porté par une seule journée n'est pas stable."""
    jours = defaultdict(list)
    for o in reglees(observations):
        jours[str(o.get("jour"))].append(o)
    return {j: {"n": len(v), "brier": round(brier([(o["p"], o["issue"]) for o in v]), 4), "taux": round(sum(o["issue"] for o in v) / len(v), 3)}
            for j, v in sorted(jours.items())}
