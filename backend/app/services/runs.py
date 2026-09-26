"""Exécution du pipeline depuis l'API. Même enchaînement que orchestrateur.py (collecte →
3 coupons → rédaction IA → Telegram), mais déterministe (pas de LLM pilote) et avec chaque
étape enregistrée en base. L'envoi Telegram est optionnel et désactivé par défaut."""

import json
from datetime import datetime, timezone

from app.config import DOSSIER_DONNEES
from app.database import SessionLocal
from app.models import Run
from app.services import pipeline
from app.services.persistance import enregistrer_collecte, enregistrer_coupons


def executer_run(run_id, envoyer_telegram=False, rediger=True):
    db = SessionLocal()
    run = db.get(Run, run_id)
    try:
        cd, ae, _ = pipeline.modules()
        pipeline.reinitialiser_caches(cd)
        DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)
        sortie = DOSSIER_DONNEES / f"collecte_run_{run_id}.json"
        cd.SORTIE_JSON = str(sortie)
        cd.collecter_donnees()
        with open(sortie, encoding="utf-8") as f:
            donnees = json.load(f)
        index = enregistrer_collecte(db, run, donnees)
        db.commit()

        if not donnees.get("nb_matchs_avec_marches"):
            run.statut, run.detail = "abandonne", "Aucun match avec marchés 1xBet exploitables."
            return

        resultats = ae.generer_trois_coupons(donnees)
        if not any(item["selections"] for item in resultats):
            run.statut, run.detail = "abandonne", "Aucun profil n'a trouvé de sélection valable."
            return

        textes = ae.agent4_rediger_trois_coupons(resultats) if rediger else None
        enregistrer_coupons(db, run, resultats, index, textes=textes)
        if envoyer_telegram and textes:
            run.envoye_telegram = bool(ae.agent5_envoyer_trois_coupons(textes))
        run.statut = "termine"
    except Exception as e:
        db.rollback()
        run = db.get(Run, run_id)
        run.statut, run.detail = "erreur", pipeline.masquer_secrets(f"{type(e).__name__}: {e}")[:2000]
    finally:
        run.termine_le = datetime.now(timezone.utc)
        db.commit()
        db.close()
