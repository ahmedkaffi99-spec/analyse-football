"""Pont vers le pipeline existant (bet_agent/) : ses modules sont importés tels quels, sans
dupliquer leur logique. Import paresseux pour que le backend démarre même si une
dépendance du pipeline manque."""

import re
import sys

from app.config import DOSSIER_PIPELINE


def modules():
    if str(DOSSIER_PIPELINE) not in sys.path:
        sys.path.insert(0, str(DOSSIER_PIPELINE))
    import analyser_et_envoyer
    import collecte_donnees
    import verifier_resultats

    return collecte_donnees, analyser_et_envoyer, verifier_resultats


def charger_agent_pilote():
    """Agent pilote DeepSeek (fusionné comme moteur officiel le 30/09/2026, demande explicite
    de l'utilisateur) : même pont que modules(), pour ne pas dupliquer le sys.path.insert."""
    if str(DOSSIER_PIPELINE) not in sys.path:
        sys.path.insert(0, str(DOSSIER_PIPELINE))
    import agent_pilote

    return agent_pilote


def reinitialiser_caches(cd, ae=None):
    """Les modules du pipeline gardent des caches au niveau module, prévus pour un script
    lancé une fois par jour. Dans un serveur qui tourne plusieurs jours, ils serviraient les
    données de la veille (classements, marchés OddsPapi) — on les vide avant chaque run."""
    cd._cache_classement_api_football.clear()
    cd._cache_stats_equipes.clear()
    cd.MARKET_NAMES_CACHE.clear()
    if hasattr(ae, "reinitialiser_budget_ia"):
        ae.reinitialiser_budget_ia()  # budget IA neuf ; la clé a pu être corrigée depuis


_MOTIF_SECRET = re.compile(r"((?:apiKey|api_key|key|token)=)[^&\s'\")]+", re.IGNORECASE)


def masquer_secrets(texte):
    """Les erreurs réseau de requests contiennent l'URL complète, clé API comprise
    (constaté dans cron.log) — jamais stockée telle quelle en base."""
    return _MOTIF_SECRET.sub(r"\1***", texte or "")
