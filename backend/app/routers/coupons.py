from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Coupon
from app.schemas import CouponOut, VerificationOut
from app.services import verification

router = APIRouter(prefix="/api/coupons", tags=["coupons"])


@router.get("", response_model=list[CouponOut])
def lister_coupons(jour: date | None = None, profil: str | None = None, statut: str | None = None,
                   limite: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    requete = select(Coupon).order_by(Coupon.jour.desc(), Coupon.run_id.desc(), Coupon.profil)
    if jour:
        requete = requete.where(Coupon.jour == jour)
    if profil:
        requete = requete.where(Coupon.profil == profil)
    if statut:
        requete = requete.where(Coupon.statut == statut)
    return db.scalars(requete.limit(limite)).all()


@router.post("/verification", response_model=VerificationOut)
def verifier_tous(db: Session = Depends(get_db)):
    """Juge toutes les jambes encore en attente dont le match est terminé (à appeler par cron le soir)."""
    return VerificationOut(**verification.verifier_coupons_en_attente(db))


@router.get("/{coupon_id}", response_model=CouponOut)
def lire_coupon(coupon_id: int, db: Session = Depends(get_db)):
    coupon = db.get(Coupon, coupon_id)
    if not coupon:
        raise HTTPException(404, "Coupon introuvable")
    return coupon
