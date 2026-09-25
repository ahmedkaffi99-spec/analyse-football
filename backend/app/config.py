"""Configuration du backend, lue depuis l'environnement.

Les clés API du pipeline restent dans bet_agent/envi.local (jamais committé) ; les réglages
propres au backend (DATABASE_URL, API_TOKEN) peuvent aller dans backend/.env ou dans
envi.local — les deux sont chargés, sans écraser une variable déjà définie."""

import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parents[2]
DOSSIER_PIPELINE = RACINE / "bet_agent"
DOSSIER_DONNEES = RACINE / "backend" / "data"

load_dotenv(RACINE / "backend" / ".env")
load_dotenv(DOSSIER_PIPELINE / "envi.local")

# Projet Supabase "analyse-football" (Session pooler, IPv4 — compatible GitHub Actions). Ce ne
# sont pas des secrets : seul le mot de passe l'est.
SUPABASE_DB_HOTE = os.getenv("SUPABASE_DB_HOTE") or "aws-0-eu-central-1.pooler.supabase.com"
SUPABASE_DB_UTILISATEUR = os.getenv("SUPABASE_DB_UTILISATEUR") or "postgres.fpwsitpdkruoknwmgjzr"


def construire_database_url(environ=os.environ):
    """Trois façons de configurer la base, de la plus simple à la plus complète :
    1. SUPABASE_DB_PASSWORD seul : l'adresse Supabase est construite automatiquement
       (le mot de passe est encodé, donc tous les caractères spéciaux sont acceptés) ;
    2. DATABASE_URL copiée telle quelle depuis Supabase ("postgresql://..." est accepté,
       le pilote psycopg est ajouté automatiquement) ;
    3. rien : SQLite local, pour développer."""
    url = (environ.get("DATABASE_URL") or "").strip()
    if url:
        for prefixe in ("postgresql://", "postgres://"):
            if url.startswith(prefixe):
                return "postgresql+psycopg://" + url[len(prefixe):]
        return url
    mot_de_passe = (environ.get("SUPABASE_DB_PASSWORD") or "").strip()
    if mot_de_passe:
        return (f"postgresql+psycopg://{SUPABASE_DB_UTILISATEUR}:{quote(mot_de_passe, safe='')}"
                f"@{SUPABASE_DB_HOTE}:5432/postgres")
    return f"sqlite:///{DOSSIER_DONNEES / 'bet_agent.db'}"


DATABASE_URL = construire_database_url()

# Schéma PostgreSQL où vivent les tables (ignoré en SQLite). Par défaut "public" : le projet
# Supabase est entièrement dédié à l'analyse. Un autre nom (ex. DB_SCHEMA=analyse_football)
# permet de partager un projet existant sans toucher à ses autres données.
DB_SCHEMA = os.getenv("DB_SCHEMA") or "public"

# Jeton exigé (en-tête X-API-Key) sur toutes les routes qui écrivent ou lancent le pipeline.
API_TOKEN = os.getenv("API_TOKEN")

# /docs, /redoc et /openapi.json décrivent toute l'API (routes, paramètres, formats) : désactivés
# par défaut pour que rien ne soit visible sans jeton. ACTIVER_DOCS=true les réactive (ils ne
# contiennent aucune donnée ; chaque appel depuis /docs exige quand même le jeton).
ACTIVER_DOCS = os.getenv("ACTIVER_DOCS", "").lower() in ("1", "true", "oui", "yes")
