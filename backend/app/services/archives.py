"""Archivage de chaque run dans le bucket Storage PRIVÉ "archives" de Supabase, via l'Edge
Function "api" (POST /archives). Conserve durablement la collecte brute et les coupons —
les artefacts GitHub Actions, eux, disparaissent au bout de 7 jours.

Le jeton de l'API est lu directement dans le Vault Supabase (vault.decrypted_secrets) avec
la connexion PostgreSQL du pipeline : aucun secret GitHub supplémentaire n'est nécessaire.
L'archivage ne bloque jamais un run : en cas d'échec, un simple avertissement est affiché."""

import requests
from sqlalchemy import text

from app import config
from app.services.pipeline import masquer_secrets

REQUETE_JETON = text("SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = 'api_token' LIMIT 1")


def contenu_coupons(run):
    return [
        {
            "profil": c.profil, "nom": c.nom, "jour": c.jour.isoformat(), "statut": c.statut,
            "cote_totale": c.cote_totale, "proba_combinee_pct": c.proba_combinee_pct, "texte": c.texte,
            "jambes": [
                {"match": j.libelle_match, "categorie": j.categorie, "marche": j.marche, "selection": j.selection,
                 "cote": j.cote, "proba_modele_pct": j.proba_modele_pct, "edge_pct": j.edge_pct,
                 "resultat": j.resultat}
                for j in c.jambes
            ],
        }
        for c in run.coupons
    ]


def archiver_run(db, run, donnees_collecte=None, poster=requests.post):
    """Renvoie la liste des chemins archivés (vide si l'archivage n'est pas disponible)."""
    if db.get_bind().dialect.name != "postgresql":
        return []
    try:
        jeton = db.execute(REQUETE_JETON).scalar()
    except Exception as e:
        db.rollback()
        print(f"   ⚠️ Archivage ignoré : jeton de l'API introuvable dans le Vault ({masquer_secrets(str(e))[:150]})")
        return []
    if not jeton:
        print("   ⚠️ Archivage ignoré : aucun secret 'api_token' dans le Vault.")
        return []

    jour = run.lance_le.date().isoformat()
    fichiers = {f"{jour}/run_{run.id}_coupons.json": contenu_coupons(run)}
    if donnees_collecte is not None:
        fichiers[f"{jour}/run_{run.id}_collecte.json"] = donnees_collecte

    archives = []
    for chemin, contenu in fichiers.items():
        try:
            r = poster(f"{config.SUPABASE_FONCTIONS_URL}/api/archives",
                       headers={"X-API-Key": jeton}, json={"chemin": chemin, "contenu": contenu}, timeout=60)
            if r.status_code == 201:
                archives.append(chemin)
            else:
                print(f"   ⚠️ Archivage de {chemin} refusé : HTTP {r.status_code} {r.text[:150]}")
        except Exception as e:
            print(f"   ⚠️ Archivage de {chemin} impossible : {masquer_secrets(str(e))[:150]}")
    if archives:
        print(f"   🗄️ Archivé dans Supabase Storage (bucket privé 'archives') : {', '.join(archives)}")
    return archives
