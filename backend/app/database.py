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


DELAI_VERROU_DDL = "8s"   # attente maximale d'un verrou de schéma : jamais bloqué par une session zombie (job annulé, connexion restée ouverte)


def _ddl_tolerant(instruction, journal=print):
    """Exécute UNE instruction de schéma (transaction à part) avec un délai de verrou court. Si la table est verrouillée par une autre session, l'instruction est
    abandonnée avec un avertissement : le démarrage du pipeline ne doit JAMAIS rester bloqué sur de l'ENTRETIEN de schéma (constaté le 07/11/2026 : un job annulé
    gardait un verrou, `ALTER TABLE runs ENABLE ROW LEVEL SECURITY` attendait le délai de la base et tout run suivant, y compris la finalisation, échouait)."""
    try:
        with engine.begin() as connexion:
            connexion.execute(text(f"SET LOCAL lock_timeout = '{DELAI_VERROU_DDL}'"))
            connexion.execute(text(instruction))
        return True
    except Exception as e:
        journal(f"⚠️ Entretien du schéma ignoré ({str(e).splitlines()[0][:120]}) : {instruction[:90]}")
        return False


def colonnes_manquantes(connexion, ajouts):
    """ajouts : ((table, colonne, type), ...). Renvoie ceux qui n'existent pas encore (lecture seule : aucun verrou de schéma)."""
    existantes = {(t, c) for t, c in connexion.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()"))}
    return [a for a in ajouts if (a[0], a[1]) not in existantes]


def durcissements_manquants(connexion, tables, roles):
    """Instructions de durcissement RÉELLEMENT nécessaires (RLS non activé, droits encore accordés aux rôles publics). En régime établi : liste vide,
    donc aucun DDL, aucun verrou. `tables` : [(schema|None, nom)]."""
    rls = {nom: actif for nom, actif in connexion.execute(text(
        "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' AND n.nspname = COALESCE(CAST(:schema AS text), current_schema()::text)"), {"schema": SCHEMA})}
    instructions = []
    for schema, nom in tables:
        cible = f'"{schema}"."{nom}"' if schema else f'"{nom}"'
        if not rls.get(nom, False):
            instructions.append(f"ALTER TABLE {cible} ENABLE ROW LEVEL SECURITY")
        for role in roles:
            if connexion.execute(text("SELECT has_table_privilege(:role, :cible, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"),
                                 {"role": role, "cible": cible}).scalar():
                instructions.append(f'REVOKE ALL ON TABLE {cible} FROM "{role}"')
    return instructions


def init_db():
    from app import models, models_historique  # noqa: F401 — enregistre les tables sur Base.metadata

    if SCHEMA:
        with engine.begin() as connexion:
            connexion.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        # Migrations ADDITIVES et idempotentes (create_all ne modifie pas une table existante). Lecture d'abord : seules les colonnes ABSENTES déclenchent un
        # ALTER (et donc un verrou) ; en régime établi, aucun DDL n'est exécuté au démarrage.
        ajouts = (("cotes", "capture_le", "TIMESTAMPTZ"), ("jambes", "proba_modele_seul_pct", "DOUBLE PRECISION"),
                  ("jambes", "proba_marche_pct", "DOUBLE PRECISION"), ("jambes", "collecte_le", "TIMESTAMPTZ"))
        with engine.connect() as connexion:
            manquantes = colonnes_manquantes(connexion, ajouts)
        for table, col, typ in manquantes:
            _ddl_tolerant(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}")
        # Supabase expose le schéma public via son API REST et donne par défaut des droits aux rôles « anon » et « authenticated » : RLS sans policy + retrait des
        # droits, appliqués seulement quand ils manquent (avant : réappliqués à chaque démarrage, avec un verrou exclusif par table). Le backend se connecte avec le
        # rôle postgres, qui n'est pas concerné.
        with engine.connect() as connexion:
            roles = [r for (r,) in connexion.execute(text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
                                                     {"roles": list(ROLES_PUBLICS_SUPABASE)})]
            instructions = durcissements_manquants(connexion, [(t.schema, t.name) for t in Base.metadata.sorted_tables], roles)
        for instruction in instructions:
            _ddl_tolerant(instruction)
