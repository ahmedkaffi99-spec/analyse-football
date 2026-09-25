from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.schemas import ImportIn, RunOut
from app.securite import exiger_jeton
from app.services import statistiques
from app.services.persistance import importer_fichiers

router = APIRouter(prefix="/api", tags=["divers"])


@router.get("/sante")
def sante(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"statut": "ok", "base": engine.dialect.name}


@router.get("/statistiques")
def lire_statistiques(db: Session = Depends(get_db)):
    return statistiques.calculer(db)


@router.post("/imports", response_model=RunOut, status_code=201, dependencies=[Depends(exiger_jeton)])
def importer(fichiers: ImportIn, db: Session = Depends(get_db)):
    """Importe donnees_collectees.json et/ou ticket_du_jour.json produits par le cron Termux."""
    try:
        return importer_fichiers(db, fichiers.collecte, fichiers.ticket)
    except (ValueError, KeyError, TypeError) as e:
        db.rollback()
        raise HTTPException(422, f"Fichier invalide : {e}")
