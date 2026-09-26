"""Régénère schema.sql (PostgreSQL / Supabase) depuis les modèles : python -m app.generer_schema_sql"""

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from sqlalchemy import MetaData

from app import models  # noqa: F401
from app.config import DB_SCHEMA
from app.database import Base

# Toujours généré pour PostgreSQL (Supabase), même si le backend local tourne en SQLite.
# Pour "public", pas de préfixe dans les noms d'index : mêmes noms que ceux créés par le backend.
SCHEMA = None if DB_SCHEMA == "public" else DB_SCHEMA
metadata = MetaData(schema=SCHEMA)
for table in Base.metadata.sorted_tables:
    table.to_metadata(metadata, schema=SCHEMA)

lignes = ["-- Généré depuis app/models.py par `python -m app.generer_schema_sql` — ne pas éditer à la main.",
          "-- À exécuter dans Supabase (SQL Editor) ; le backend crée aussi les tables au démarrage.",
          "-- Sécurité : RLS sans policy + aucun droit pour les rôles publics (anon / authenticated) :",
          "-- seul le backend (rôle postgres) lit et écrit ces tables.", ""]
if SCHEMA:
    lignes += [f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}";', f'REVOKE ALL ON SCHEMA "{SCHEMA}" FROM anon, authenticated;', ""]
for table in metadata.sorted_tables:
    lignes.append(str(CreateTable(table, if_not_exists=True).compile(dialect=postgresql.dialect())).strip() + ";")
    for index in sorted(table.indexes, key=lambda i: i.name):
        lignes.append(str(CreateIndex(index, if_not_exists=True).compile(dialect=postgresql.dialect())).strip() + ";")
    # Supabase expose le schéma public via son API REST : RLS + retrait des droits des rôles
    # publics. Le backend se connecte avec le rôle postgres, qui n'est pas concerné.
    nom = f"{table.schema or 'public'}.{table.name}"
    lignes.append(f"ALTER TABLE {nom} ENABLE ROW LEVEL SECURITY;")
    lignes.append(f"REVOKE ALL ON TABLE {nom} FROM anon, authenticated;")
    lignes.append("")
Path(__file__).resolve().parents[1].joinpath("schema.sql").write_text("\n".join(lignes), encoding="utf-8")
print("schema.sql régénéré")
