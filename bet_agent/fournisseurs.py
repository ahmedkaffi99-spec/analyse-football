import os


def oddspapi_actif():
    """OddsPapi n'est interrogé QUE si FOURNISSEUR_COTES=oddspapi explicitement. Défaut
    api_football depuis le 13/10/2026 (demande explicite : "n'utilise pas oddspapi") : aucun
    appel réseau OddsPapi, donc aucun quota consommé, tant que cette variable n'est pas changée."""
    return (os.getenv("FOURNISSEUR_COTES") or "api_football").strip().lower() == "oddspapi"
