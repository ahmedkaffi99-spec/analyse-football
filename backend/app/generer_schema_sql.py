"""Régénère schema.sql (PostgreSQL / Supabase) depuis les modèles : python -m app.generer_schema_sql"""

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from sqlalchemy import MetaData

from app import models  # noqa: F401
from app.config import DB_SCHEMA
from app.database import Base

# Toujours généré pour PostgreSQL avec le schéma dédié, même si le backend local tourne en SQLite.
metadata = MetaData(schema=DB_SCHEMA)
for table in Base.metadata.sorted_tables:
    table.to_metadata(metadata, schema=DB_SCHEMA)

lignes = ["-- Généré depuis app/models.py par `python -m app.generer_schema_sql` — ne pas éditer à la main.",
          "-- À exécuter dans Supabase (SQL Editor) ; le backend crée aussi les tables au démarrage.", "",
          f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";',
          "-- Le schéma n'est pas exposé par l'API REST de Supabase ; on retire en plus tout accès",
          "-- aux rôles publics (anon / authenticated) : seul le backend (rôle postgres) y accède.",
          f'REVOKE ALL ON SCHEMA "{DB_SCHEMA}" FROM anon, authenticated;', ""]
for table in metadata.sorted_tables:
    lignes.append(str(CreateTable(table, if_not_exists=True).compile(dialect=postgresql.dialect())).strip() + ";")
    for index in sorted(table.indexes, key=lambda i: i.name):
        lignes.append(str(CreateIndex(index, if_not_exists=True).compile(dialect=postgresql.dialect())).strip() + ";")
    # Supabase expose le schéma public via son API REST : sans RLS, n'importe qui possédant la
    # clé "anon" (publique) pourrait lire/modifier ces tables. Le backend se connecte avec le
    # rôle postgres, qui contourne le RLS — il n'est donc pas gêné.
    lignes.append(f"ALTER TABLE {table.schema}.{table.name} ENABLE ROW LEVEL SECURITY;")
    lignes.append("")
Path(__file__).resolve().parents[1].joinpath("schema.sql").write_text("\n".join(lignes), encoding="utf-8")
print("schema.sql régénéré")
