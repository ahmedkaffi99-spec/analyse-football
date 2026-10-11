"""Backtest walk-forward RÉEL de moteur/backtest.py sur les 20 combinaisons championnat x saison
désormais présentes dans hist_matchs (5 championnats x 4 saisons, voir docs/couverture_historique.md).

LECTURE SEULE : aucune écriture dans Supabase, aucun secret affiché ni journalisé (seules les
métriques agrégées — comptages, Brier, log loss, calibration — sont imprimées, jamais une
variable d'environnement ni une chaîne de connexion).

Deux sources de données, explicites, jamais mélangées silencieusement :
  1. "db"    (par défaut) — accès direct à la base via backend/app/database.SessionLocal
             (DATABASE_URL / SUPABASE_DB_PASSWORD, exactement le même mécanisme sécurisé que le
             reste du backend) + backend/app/services/historique.charger_matchs. C'est le chemin
             prévu pour une exécution en CI ou sur un poste avec backend/.env configuré.
  2. "cache" — relit des fichiers JSON déjà extraits de hist_matchs (un fichier par championnat
             x saison, format {"payload": [...]} ou une liste nue), pour les environnements sans
             accès direct à la base (ex. cette session d'audit, voir docs/ pour le détail). Named
             explicitly to never be confused with une vraie connexion DB.

Usage :
    cd backend && python -m scripts_audit.backtest_complet --source db
    python scripts/audit_historique/backtest_complet.py --source cache --cache-dir /chemin/vers/json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LIGUES_PRIORITAIRES = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
SAISONS_PRIORITAIRES = (2022, 2023, 2024, 2025)


def _preparer_chemin_backend():
    racine = Path(__file__).resolve().parents[2]
    if str(racine) not in sys.path:
        sys.path.insert(0, str(racine))  # pour "moteur" (racine du dépôt)
    backend = racine / "backend"
    if backend.exists() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))  # pour "app" (backend/app)


def charger_depuis_db(ligue_id, saison):
    """Accès direct DB (lecture seule) — aucun secret manipulé ici, SessionLocal gère la
    connexion exactement comme le reste du backend (voir backend/app/database.py)."""
    _preparer_chemin_backend()
    from app.database import SessionLocal
    from app.services.historique import charger_matchs

    with SessionLocal() as db:
        return charger_matchs(db, competition_id=ligue_id, saisons=[saison])


def charger_depuis_cache(cache_dir, ligue_id, saison):
    """Relit un fichier JSON déjà extrait (voir docs/audit_moteur_unique.md pour la provenance
    exacte dans cette session). Fichier attendu : <cache_dir>/<ligue_id>_<saison>.json,
    contenant soit une liste de matchs, soit {"payload": [...]} (format brut d'un export SQL)."""
    chemin = Path(cache_dir) / f"{ligue_id}_{saison}.json"
    if not chemin.exists():
        return None
    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)
    if isinstance(donnees, dict) and "payload" in donnees:
        donnees = donnees["payload"] if isinstance(donnees["payload"], list) else json.loads(donnees["payload"])
    return donnees


def executer_grille(charger_matchs_fn, cfg, ligues=LIGUES_PRIORITAIRES, saisons=SAISONS_PRIORITAIRES):
    """Boucle les 20 combinaisons, exécute moteur.backtest.executer sur chacune (si les matchs
    sont disponibles), renvoie {(ligue_id, saison): resultat | {"indisponible": raison}}."""
    from moteur.backtest import executer as backtest_executer

    resultats = {}
    for ligue_id, nom in ligues.items():
        for saison in saisons:
            cle = f"{nom} {saison}/{saison + 1}"
            matchs = charger_matchs_fn(ligue_id, saison)
            if not matchs:
                resultats[cle] = {"indisponible": "aucun match trouvé pour cette combinaison"}
                continue
            termines = [m for m in matchs if m.get("home_score") is not None and m.get("away_score") is not None]
            if len(termines) < 10:
                resultats[cle] = {"indisponible": f"seulement {len(termines)} match(s) terminé(s), trop peu pour un backtest"}
                continue
            debut = min(m["date"] for m in termines)
            fin_matchs = max(m["date"] for m in termines)
            # fin EXCLUSIVE dans generer_lignes (debut <= date < fin) : il faut strictement
            # dépasser la date du dernier match connu, sinon celui-ci est silencieusement exclu.
            fin = str(fin_matchs)[:10] + "T23:59:59+00:00" if isinstance(fin_matchs, str) else fin_matchs
            try:
                r = backtest_executer(matchs, cotes_par_match={}, cfg=cfg, debut=debut, fin=fin)
                r.pop("_lignes", None)
                r["n_matchs"] = len(matchs)
                r["n_matchs_termines"] = len(termines)
                resultats[cle] = r
            except Exception as e:  # jamais interrompre la grille pour une combinaison en échec
                resultats[cle] = {"indisponible": f"{type(e).__name__}: {e}"}
    return resultats


def resume(resultats):
    lignes = []
    for cle, r in resultats.items():
        if "indisponible" in r:
            lignes.append(f"{cle:30s} INDISPONIBLE — {r['indisponible']}")
            continue
        g = r["global"]
        lignes.append(f"{cle:30s} n_matchs={r['n_matchs']:4d} n_predictions={g['n_predictions']:6d} "
                      f"brier={g['brier']:.4f} log_loss={g['log_loss']:.4f}")
    return "\n".join(lignes)


def main():
    _preparer_chemin_backend()
    from moteur.config import Config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["db", "cache"], default="db")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--sortie-json", default=None, help="chemin où écrire le résultat complet (JSON)")
    args = parser.parse_args()

    if args.source == "cache":
        if not args.cache_dir:
            parser.error("--cache-dir est requis avec --source cache")
        charger = lambda ligue_id, saison: charger_depuis_cache(args.cache_dir, ligue_id, saison)  # noqa: E731
    else:
        charger = charger_depuis_db

    cfg = Config()
    resultats = executer_grille(charger, cfg)
    print(resume(resultats))
    if args.sortie_json:
        with open(args.sortie_json, "w", encoding="utf-8") as f:
            json.dump(resultats, f, ensure_ascii=False, default=str)
        print(f"\nRésultat complet écrit dans {args.sortie_json}")


if __name__ == "__main__":
    main()
