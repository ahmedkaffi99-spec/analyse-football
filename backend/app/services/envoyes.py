"""Définition UNIQUE d'un « résultat réel » (Phase 2, 06/11/2026) : seuls les coupons d'un run réellement envoyé sur Telegram comptent.
Utilisée par les statistiques, la mémoire d'apprentissage, les bilans et la qualité des marchés, pour qu'ils restent toujours cohérents
entre eux. Les coupons des runs d'essai (jamais reçus) restent en base, intacts, mais ne sont jamais des résultats réels."""
from sqlalchemy import select

from app.models import Coupon, Jambe, Run


def condition_coupon_envoye():
    """Condition SQL sur Coupon : son run a réellement été envoyé (envoi complet ou partiel)."""
    return Coupon.run_id.in_(select(Run.id).where(Run.envoye_telegram.is_(True)))


def condition_jambe_envoyee():
    """Même condition sur Jambe (via son coupon)."""
    return Jambe.coupon_id.in_(select(Coupon.id).where(condition_coupon_envoye()))
