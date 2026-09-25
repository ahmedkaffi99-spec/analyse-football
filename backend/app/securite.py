import hmac

from fastapi import Header, HTTPException

from app import config


def exiger_jeton(x_api_key: str | None = Header(default=None)):
    """Toute route qui écrit en base ou lance le pipeline exige l'en-tête X-API-Key. Sans
    API_TOKEN configuré, ces routes sont refusées plutôt qu'ouvertes à tous."""
    if not config.API_TOKEN:
        raise HTTPException(503, "API_TOKEN non configuré côté serveur — routes d'écriture désactivées.")
    if not x_api_key or not hmac.compare_digest(x_api_key, config.API_TOKEN):
        raise HTTPException(401, "En-tête X-API-Key manquant ou invalide.")
