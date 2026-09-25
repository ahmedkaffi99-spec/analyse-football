"""Configuration du backend, lue depuis l'environnement.

Les clés API du pipeline restent dans bet_agent/envi.local (jamais committé) ; les réglages
propres au backend (DATABASE_URL, API_TOKEN) peuvent aller dans backend/.env ou dans
envi.local — les deux sont chargés, sans écraser une variable déjà définie."""

import os
from pathlib import Path

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parents[2]
DOSSIER_PIPELINE = RACINE / "bet_agent"
DOSSIER_DONNEES = RACINE / "backend" / "data"

load_dotenv(RACINE / "backend" / ".env")
load_dotenv(DOSSIER_PIPELINE / "envi.local")

# SQLite par défaut (aucune installation) ; en production, la chaîne PostgreSQL de Supabase
# (Project Settings → Database → Connection string), ex. :
# postgresql+psycopg://postgres.xxxx:MOT_DE_PASSE@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DOSSIER_DONNEES / 'bet_agent.db'}"

# Jeton exigé (en-tête X-API-Key) sur toutes les routes qui écrivent ou lancent le pipeline.
API_TOKEN = os.getenv("API_TOKEN")

# /docs, /redoc et /openapi.json décrivent toute l'API (routes, paramètres, formats) : désactivés
# par défaut pour que rien ne soit visible sans jeton. ACTIVER_DOCS=true les réactive (ils ne
# contiennent aucune donnée ; chaque appel depuis /docs exige quand même le jeton).
ACTIVER_DOCS = os.getenv("ACTIVER_DOCS", "").lower() in ("1", "true", "oui", "yes")
