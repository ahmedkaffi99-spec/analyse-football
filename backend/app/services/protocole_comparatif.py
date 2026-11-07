"""Phase 4.5 — protocole comparatif de 10 jours : mêmes matchs et mêmes informations pour les quatre modèles.
Module pur : il PRÉPARE et CONTRÔLE le protocole ; il n'appelle aucun modèle (les appels payants exigent une autorisation spécifique)."""

import hashlib
import json
from datetime import date, timedelta

from app.services.suivi_modeles import MODELES, SEUIL_ECHANTILLON

NB_JOURS = 10


def plan(debut, protocole="P4-2026-11"):
    """10 jours consécutifs à partir de `debut` (date ISO)."""
    d0 = date.fromisoformat(debut)
    return {"protocole": protocole, "jours": [str(d0 + timedelta(days=i)) for i in range(NB_JOURS)], "modeles": list(MODELES),
            "regles": ["catalogue de matchs figé une fois par jour (empreinte), identique pour les quatre modèles",
                       "mêmes règles de Python, mêmes profils, même prompt, même effort de raisonnement",
                       "aucun envoi Telegram, aucun vrai coupon : coupons de suivi uniquement",
                       "un tirage par modèle et par jour ; un re-tirage n'est jamais additionné",
                       f"objectif : {SEUIL_ECHANTILLON} coupons réglés par modèle ; sinon les insuffisances sont déclarées"]}


def empreinte_catalogue(catalogue):
    """Empreinte du catalogue figé (liste de jambes candidates) : preuve que les quatre modèles ont reçu les mêmes informations."""
    cles = sorted((c["match_id"], c["marche"], c["selection"], c.get("handicap"), c["cote"]) for c in catalogue)
    return hashlib.sha256(json.dumps(cles, default=str).encode()).hexdigest()[:16]


def controle_equite(tirages):
    """tirages : {modele: empreinte_catalogue} pour un jour donné. Renvoie la liste des anomalies (vide = protocole respecté pour ce jour)."""
    anomalies = []
    manquants = [m for m in MODELES if m not in tirages]
    if manquants:
        anomalies.append(f"modèles sans tirage : {', '.join(manquants)}")
    if len(set(tirages.values())) > 1:
        anomalies.append("catalogues différents entre modèles : jour non comparable")
    return anomalies


def couverture(registre, jours):
    """Coupons réglés par modèle et par jour du plan + manques par rapport à l'objectif."""
    res = {m: {j: 0 for j in jours} for m in MODELES}
    for c in registre.coupons:
        if c["protocole"] and c["jour"] in jours and c["statut"] in ("gagne", "perdu"):
            res[c["modele"]][c["jour"]] += 1
    total = {m: sum(v.values()) for m, v in res.items()}
    return {"par_jour": res, "total": total, "manque": {m: max(0, SEUIL_ECHANTILLON - t) for m, t in total.items()}}
