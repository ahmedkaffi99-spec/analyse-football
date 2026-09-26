from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Match
from app.schemas import MatchDetail, MatchOut

router = APIRouter(prefix="/api/matchs", tags=["matchs"])


@router.get("", response_model=list[MatchOut])
def lister_matchs(jour: date | None = None, run_id: int | None = None,
                  limite: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    requete = select(Match).order_by(Match.coup_envoi.desc(), Match.id.desc())
    if run_id is not None:
        requete = requete.where(Match.run_id == run_id)
    if jour:
        debut = datetime.combine(jour, time.min)
        requete = requete.where(Match.coup_envoi >= debut, Match.coup_envoi < debut + timedelta(days=1))
    return db.scalars(requete.limit(limite)).all()


@router.get("/{match_id}", response_model=MatchDetail)
def lire_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match introuvable")
    return match
