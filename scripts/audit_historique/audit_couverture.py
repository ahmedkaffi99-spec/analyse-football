"""Audit en LECTURE SEULE de la couverture historique réelle (hist_matchs, hist_cotes,
jambes/coupons) pour les 5 championnats prioritaires (docs/couverture_historique.md).

Ne modifie aucune donnée (aucun INSERT/UPDATE/DELETE), ne lance aucun import, ne déclenche
aucune migration. Réutilise la connexion déjà configurée du backend (DATABASE_URL, voir
backend/app/database.py) — à exécuter depuis backend/ (ou avec backend/ dans PYTHONPATH),
exactement comme les autres commandes de app.taches.

Usage :
    cd backend && python -m scripts_audit.audit_couverture     (si copié dans le backend)
ou, depuis la racine du dépôt, avec PYTHONPATH pointant vers backend/ :
    PYTHONPATH=backend python scripts/audit_historique/audit_couverture.py

Les 5 championnats prioritaires, par competition_id API-Football (utilisés aussi par
.github/workflows/backfill-historique.yml) :
"""

from __future__ import annotations

import sys
from pathlib import Path

LIGUES_PRIORITAIRES = {
    39: "Premier League",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
}

SAISONS_PRIORITAIRES = (2025, 2024, 2023)  # année de début de saison (API-Football)


def _preparer_chemin_backend():
    """Ajoute backend/ au PYTHONPATH si le script est lancé depuis la racine du dépôt, sans
    dépendre d'une installation préalable du package — jamais d'écriture sur le système."""
    racine = Path(__file__).resolve().parents[2]
    backend = racine / "backend"
    if backend.exists() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def detecter_doublons(lignes, cle):
    """Pure, sans dépendance base : regroupe `lignes` (liste de dict-like) par `cle` (tuple de
    noms de champs) et renvoie la liste des groupes de taille > 1 — testable indépendamment de
    toute connexion réelle (voir tests/test_audit_historique.py)."""
    groupes: dict[tuple, list] = {}
    for ligne in lignes:
        k = tuple(ligne.get(c) for c in cle)
        groupes.setdefault(k, []).append(ligne)
    return [(k, v) for k, v in groupes.items() if len(v) > 1]


def champs_manquants(lignes, champ):
    """Nombre de lignes où `champ` est absent ou None — pure, testable sans base réelle."""
    return sum(1 for ligne in lignes if ligne.get(champ) is None)


def matrice_couverture(db):
    """Interroge hist_matchs (lecture seule, SELECT uniquement) pour produire la matrice
    championnat x saison réellement en base, sans jamais estimer ou inventer une ligne absente."""
    from sqlalchemy import text

    lignes = db.execute(text(
        "SELECT competition_id, competition, saison, count(*) AS n, "
        "count(home_score) AS avec_score, "
        "count(stats) AS avec_bloc_stats "
        "FROM hist_matchs GROUP BY 1, 2, 3 ORDER BY 1, 3"
    )).mappings().all()

    presentes = {(l["competition_id"], l["saison"]): dict(l) for l in lignes}
    rapport = []
    for ligue_id, nom in LIGUES_PRIORITAIRES.items():
        for saison in SAISONS_PRIORITAIRES:
            donnee = presentes.get((ligue_id, saison))
            rapport.append({
                "ligue_id": ligue_id, "ligue": nom, "saison": saison,
                "matchs_importes": donnee["n"] if donnee else 0,
                "avec_score": donnee["avec_score"] if donnee else 0,
                "avec_bloc_stats": donnee["avec_bloc_stats"] if donnee else 0,
                "statut": "COLLECTÉ" if donnee else "NON COLLECTÉ",
            })
    return rapport


def verifier_doublons_hist_matchs(db):
    """SELECT uniquement : vérifie qu'aucune ligne hist_matchs ne partage (home_id, away_id,
    date) avec une autre — un vrai doublon de match, pas seulement un match_id différent."""
    from sqlalchemy import text

    lignes = db.execute(text(
        "SELECT home_id, away_id, date, count(*) AS n FROM hist_matchs "
        "GROUP BY 1, 2, 3 HAVING count(*) > 1"
    )).mappings().all()
    return list(lignes)


def main():
    _preparer_chemin_backend()
    from app.database import SessionLocal

    with SessionLocal() as db:
        print("=== Matrice de couverture (hist_matchs, 5 championnats prioritaires) ===")
        for ligne in matrice_couverture(db):
            print(f"  {ligne['ligue']:15s} {ligne['saison']}/{ligne['saison']+1} : "
                  f"{ligne['statut']:13s} matchs={ligne['matchs_importes']:4d} "
                  f"avec_score={ligne['avec_score']:4d} avec_stats={ligne['avec_bloc_stats']:4d}")

        print("\n=== Doublons hist_matchs (home_id, away_id, date) ===")
        doublons = verifier_doublons_hist_matchs(db)
        print(f"  {len(doublons)} groupe(s) en doublon détecté(s)" if doublons
              else "  aucun doublon détecté")


if __name__ == "__main__":
    main()
