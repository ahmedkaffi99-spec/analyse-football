"""Paris déjà présents dans un coupon du jour d'un AUTRE run (plafond « un même pari dans un seul coupon par jour », 14/11/2026).

Lu avant chaque run de l'agent (voir runs.executer_run) puis transmis à bet_agent/agent_pilote.executer (paris_exclus) : ces paris sont retirés du catalogue et refusés par la
validation. PLAFOND_PARI_JOUR=0 désactive le plafond. Aucune écriture en base."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Coupon, Jambe
from app.services import pipeline


def paris_deja_pris(db, run_id, jour=None):
    """Ensemble de clés plafonds_coupon.cle_pari_jour des jambes de coupons NON VIDES du jour, d'un autre run que `run_id` (frozenset vide si le plafond est désactivé)."""
    pipeline.modules()
    import plafonds_coupon
    if not plafonds_coupon.plafond_actif():
        return frozenset()
    jour = jour or datetime.now(timezone.utc).date()
    requete = (select(Jambe.libelle_match, Jambe.categorie, Jambe.selection, Jambe.handicap)
               .join(Coupon, Coupon.id == Jambe.coupon_id)
               .where(Coupon.jour == jour, Coupon.statut != "vide", Coupon.run_id != run_id))
    return frozenset(plafonds_coupon.cle_pari_jour(*ligne) for ligne in db.execute(requete))
