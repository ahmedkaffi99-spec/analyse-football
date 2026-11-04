"""Registre des sources de données et garde-fou juridique (Phase 2). Lecture/écriture additives uniquement."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models_historique import SourceDonnees

# Statuts initiaux (prudents) — tout ce qui n'est pas explicitement autorisé par écrit reste NON autorisé à l'automatisation.
SOURCES_INITIALES = [
    ("football-data", "https://www.football-data.co.uk", "a_verifier", True,
     "Données gratuites publiées pour consultation ; conditions propres du site non retrouvées ; les données anglaises/écossaises relèvent de "
     "Football DataCo (licence requise pour un usage commercial/paris). Usage actuel : recherche personnelle, faible volume (1 appel/6 h)."),
    ("api-football", "https://www.api-football.com", "autorisee", True,
     "Accès via abonnement et clé API de l'utilisateur, selon les conditions du fournisseur (quota respecté)."),
    ("oddspapi", "https://oddspapi.io", "autorisee", True, "Accès via clé API de l'utilisateur, quota respecté."),
    ("understat", "https://understat.com", "inconnue", False,
     "AUCUNE collecte automatisée tant qu'une confirmation écrite des conditions et droits n'est pas obtenue (décision du 2026-11-04). "
     "L'e-mail informel de 2018 rapporté par un tiers n'est pas une autorisation."),
]


class SourceNonAutorisee(RuntimeError):
    pass


def initialiser(db):
    """Crée les lignes manquantes (jamais d'écrasement d'un statut existant)."""
    for nom, url, statut, autorisee, notes in SOURCES_INITIALES:
        if db.get(SourceDonnees, nom) is None:
            db.add(SourceDonnees(nom=nom, url=url, licence_statut=statut, collecte_autorisee=autorisee, notes=notes[:500],
                                 verifie_le=datetime.now(timezone.utc)))
    db.commit()


def exiger_autorisation(db, nom):
    """Lève SourceNonAutorisee si la source est inconnue du registre ou non explicitement autorisée."""
    s = db.get(SourceDonnees, nom)
    if s is None or not s.collecte_autorisee or s.licence_statut == "refusee":
        raise SourceNonAutorisee(f"collecte automatisée de '{nom}' non autorisée (statut={getattr(s, 'licence_statut', 'absent')})")
    return s


def autoriser(db, nom, preuve_ref, statut="autorisee"):
    """À appeler UNIQUEMENT après décision humaine explicite ; la preuve (lien, e-mail, date) est obligatoire."""
    if not preuve_ref or len(preuve_ref.strip()) < 10:
        raise ValueError("preuve_ref obligatoire (référence de la confirmation écrite)")
    s = db.get(SourceDonnees, nom)
    if s is None:
        raise KeyError(nom)
    ancien = f"{s.licence_statut}/{s.collecte_autorisee}"
    s.licence_statut, s.collecte_autorisee, s.preuve_ref, s.verifie_le = statut, True, preuve_ref[:300], datetime.now(timezone.utc)
    s.historique = ((s.historique or "") + f"\n{s.verifie_le.isoformat(timespec='seconds')} {ancien} -> {statut}/True ({preuve_ref[:80]})")[-2000:]
    db.commit()
    return s


def lister(db):
    return list(db.execute(select(SourceDonnees).order_by(SourceDonnees.nom)).scalars())
