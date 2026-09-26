from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Run
from app.schemas import RunCreate, RunDetail, RunOut, VerificationOut
from app.services import runs as service_runs
from app.services import verification

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("", response_model=list[RunOut])
def lister_runs(limite: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    return db.scalars(select(Run).order_by(Run.id.desc()).limit(limite)).all()


@router.get("/{run_id}", response_model=RunDetail)
def lire_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run introuvable")
    return run


@router.post("", response_model=RunOut, status_code=202)
def lancer_run(options: RunCreate, taches: BackgroundTasks, db: Session = Depends(get_db)):
    """Lance le pipeline en arrière-plan (plusieurs minutes : quotas API et LLM). Suivre
    l'avancement avec GET /api/runs/{id}."""
    service_runs.cloturer_runs_interrompus(db)
    if db.scalar(select(Run).where(Run.statut == "en_cours", Run.source == "api")):
        raise HTTPException(409, "Un run est déjà en cours.")
    run = Run(source="api", statut="en_cours")
    db.add(run)
    db.commit()
    taches.add_task(service_runs.executer_run, run.id, options.envoyer_telegram, options.rediger)
    return run


@router.post("/{run_id}/verification", response_model=VerificationOut)
def verifier_run(run_id: int, db: Session = Depends(get_db)):
    if not db.get(Run, run_id):
        raise HTTPException(404, "Run introuvable")
    return VerificationOut(**verification.verifier_coupons_en_attente(db, run_id))
