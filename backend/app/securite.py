import hmac

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app import config

# Déclaré comme schéma de sécurité : /docs (si activé) affiche un bouton "Authorize".
en_tete_cle = APIKeyHeader(name="X-API-Key", auto_error=False)


def exiger_jeton(x_api_key: str | None = Security(en_tete_cle)):
    """Appliqué à TOUTES les routes de l'API (lecture comme écriture) : sans l'en-tête
    X-API-Key valide, rien n'est accessible. Sans API_TOKEN configuré côté serveur, toutes
    les routes sont refusées plutôt qu'ouvertes à tous."""
    if not config.API_TOKEN:
        raise HTTPException(503, "API_TOKEN non configuré côté serveur — API désactivée.")
    if not x_api_key or not hmac.compare_digest(x_api_key, config.API_TOKEN):
        raise HTTPException(401, "En-tête X-API-Key manquant ou invalide.")
