"""Import en ligne de commande des fichiers JSON du pipeline (sans passer par l'API) :

    python -m app.importer --collecte ../bet_agent/donnees_collectees.json --ticket ../bet_agent/ticket_du_jour.json
"""

import argparse
import json

from app.database import SessionLocal, init_db
from app.services.persistance import importer_fichiers


def charger(chemin):
    if not chemin:
        return None
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Importe les JSON du pipeline dans la base.")
    parser.add_argument("--collecte", help="chemin de donnees_collectees.json")
    parser.add_argument("--ticket", help="chemin de ticket_du_jour.json")
    args = parser.parse_args()
    if not args.collecte and not args.ticket:
        parser.error("indique --collecte et/ou --ticket")

    init_db()
    db = SessionLocal()
    try:
        run = importer_fichiers(db, charger(args.collecte), charger(args.ticket))
        print(f"✅ Import terminé : run {run.id} — {len(run.matchs)} match(s), {len(run.coupons)} coupon(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
