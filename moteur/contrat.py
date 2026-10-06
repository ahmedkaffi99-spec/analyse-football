"""Contrat commun entre les briques (collecte, modèles, sélection, coupon, base, rapports) :
chaque prédiction circule sous la forme d'un dict plat, jamais d'un objet interne d'un modèle.

    {
      "match_id": ..., "model": 4, "model_name": "buts_total", "market": "buts_total",
      "line": 2.5, "selection": "over",
      "raw_probability": 0.71, "probability": 0.69, "calibrated": True, "calibration_n": 412,
      "timestamp": "2026-10-06T10:00:00+00:00",
      "model_version": "1.0.0", "features_version": "1.0.0",
      # après ajout des cotes :
      "odds": 1.30, "bookmaker": "1xbet", "odds_timestamp": "...",
      "implied_probability": 0.7692, "edge": -0.103,
      # après sélection :
      "decision": "retenu" | "rejeté", "reasons": ["probabilité 69.0% < 70%"],
    }

Statut spécial d'un modèle sans données suffisantes : INSUFFICIENT_DATA (aucune probabilité
inventée)."""

from datetime import datetime, timezone

from moteur import cotes as mcotes
from moteur.features import VERSION_FEATURES
from moteur.modeles.registre import VERSION_MODELES

INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def prediction(match_id, p, proba=None, calibre=False, n_calibration=0, horodatage=None):
    """p : moteur.modeles.registre.Prediction."""
    return {
        "match_id": match_id, "model": p.modele, "model_name": p.nom_modele, "market": p.marche,
        "line": p.ligne, "selection": p.selection,
        "raw_probability": p.probabilite, "probability": p.probabilite if proba is None else proba,
        "calibrated": calibre, "calibration_n": n_calibration, "binary": p.binaire,
        "timestamp": (horodatage or datetime.now(timezone.utc)).isoformat(),
        "model_version": VERSION_MODELES, "features_version": VERSION_FEATURES,
        "parameters": p.parametres,
    }


def avec_cote(pred, cote, bookmaker=None, horodatage_cote=None):
    """Ajoute cote, probabilité implicite et edge. Cote invalide (None, <= 1) : champs à None,
    jamais d'edge calculé sur une cote absurde."""
    valide = cote is not None and cote > 1
    return {**pred, "odds": cote if valide else None, "bookmaker": bookmaker,
            "odds_timestamp": horodatage_cote.isoformat() if hasattr(horodatage_cote, "isoformat") else horodatage_cote,
            "implied_probability": mcotes.proba_implicite(cote) if valide else None,
            "edge": mcotes.edge(pred["probability"], cote) if valide else None}


def avec_decision(pred, retenu, raisons):
    return {**pred, "decision": "retenu" if retenu else "rejeté", "reasons": list(raisons)}


def insuffisant(match_id, modele, raison):
    return {"match_id": match_id, "model": modele, "status": INSUFFICIENT_DATA, "reason": raison,
            "timestamp": datetime.now(timezone.utc).isoformat(), "model_version": VERSION_MODELES}
