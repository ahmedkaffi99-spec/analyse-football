"""Régénère schema.sql (PostgreSQL / Supabase) depuis les modèles : python -m app.generer_schema_sql"""

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app import models  # noqa: F401
from app.database import Base

lignes = ["-- Généré depuis app/models.py par `python -m app.generer_schema_sql` — ne pas éditer à la main.",
          "-- À exécuter dans Supabase (SQL Editor) ; le backend crée aussi les tables au démarrage.", ""]
for table in Base.metadata.sorted_tables:
    lignes.append(str(CreateTable(table, if_not_exists=True).compile(dialect=postgresql.dialect())).strip() + ";")
    for index in sorted(table.indexes, key=lambda i: i.name):
        lignes.append(str(CreateIndex(index, if_not_exists=True).compile(dialect=postgresql.dialect())).strip() + ";")
    # Supabase expose le schéma public via son API REST : sans RLS, n'importe qui possédant la
    # clé "anon" (publique) pourrait lire/modifier ces tables. Le backend se connecte avec le
    # rôle postgres, qui contourne le RLS — il n'est donc pas gêné.
    lignes.append(f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY;")
    lignes.append("")
Path(__file__).resolve().parents[1].joinpath("schema.sql").write_text("\n".join(lignes), encoding="utf-8")
print("schema.sql régénéré")
