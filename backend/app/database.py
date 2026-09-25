from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL, DB_SCHEMA, DOSSIER_DONNEES

EST_SQLITE = DATABASE_URL.startswith("sqlite")
if EST_SQLITE:
    DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if EST_SQLITE else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# SQLite n'a pas de schémas, et "public" est le schéma par défaut de PostgreSQL : dans ces deux
# cas, les tables restent sans préfixe.
SCHEMA = None if EST_SQLITE or DB_SCHEMA == "public" else DB_SCHEMA
ROLES_PUBLICS_SUPABASE = ("anon", "authenticated")


class Base(DeclarativeBase):
    # Les clés étrangères écrites "runs.id" se résolvent automatiquement dans ce schéma.
    metadata = MetaData(schema=SCHEMA)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 — enregistre les tables sur Base.metadata

    if SCHEMA:
        with engine.begin() as connexion:
            connexion.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        # Supabase expose le schéma public via son API REST et donne par défaut des droits aux
        # rôles "anon" (clé publique) et "authenticated" sur les nouvelles tables. Double
        # protection, réappliquée à chaque démarrage (sans effet si déjà en place) :
        # RLS sans policy (aucune ligne visible) + retrait de tous les droits de ces rôles.
        # Le backend se connecte avec le rôle postgres, qui n'est pas concerné.
        with engine.begin() as connexion:
            roles = [r for (r,) in connexion.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
                {"roles": list(ROLES_PUBLICS_SUPABASE)})]
            for table in Base.metadata.sorted_tables:
                nom = f'"{table.schema}"."{table.name}"' if table.schema else f'"{table.name}"'
                connexion.execute(text(f"ALTER TABLE {nom} ENABLE ROW LEVEL SECURITY"))
                for role in roles:
                    connexion.execute(text(f'REVOKE ALL ON TABLE {nom} FROM "{role}"'))
