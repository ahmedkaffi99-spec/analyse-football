from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL, DOSSIER_DONNEES

EST_SQLITE = DATABASE_URL.startswith("sqlite")
if EST_SQLITE:
    DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if EST_SQLITE else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 — enregistre les tables sur Base.metadata

    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        # Supabase expose le schéma public via son API REST : sans RLS, la clé publique "anon"
        # pourrait lire/modifier ces tables. Activé à chaque démarrage (sans effet si déjà
        # actif) ; le backend se connecte avec le rôle postgres, qui contourne le RLS.
        with engine.begin() as connexion:
            for table in Base.metadata.sorted_tables:
                connexion.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
