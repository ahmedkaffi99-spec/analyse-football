"""
Filet de sécurité pour le cron de midi. Constaté le 2026-07-24 : une erreur SSL transitoire
(réseau) a fait échouer TOUTE la collecte OddsPapi pendant le run de midi, forçant un
abandon complet pour la journée alors que le réseau était de nouveau opérationnel quelques
minutes plus tard. Ce script est lancé un peu plus tard par cron et relance l'orchestrateur
UNIQUEMENT si aucun ticket n'a été généré pour aujourd'hui — jamais de double envoi si le
run de midi a réussi.
"""

import os
import json
from datetime import datetime

TICKET_JSON = "ticket_du_jour.json"


def ticket_du_jour_deja_genere():
    if not os.path.exists(TICKET_JSON):
        return False
    with open(TICKET_JSON, "r", encoding="utf-8") as f:
        ticket = json.load(f)
    return ticket.get("date") == datetime.now().strftime("%Y-%m-%d")


if __name__ == "__main__":
    if ticket_du_jour_deja_genere():
        print("ℹ️ Ticket du jour déjà généré — pas de relance nécessaire.")
    else:
        print("⚠️ Aucun ticket pour aujourd'hui — relance de l'orchestrateur "
              "(probable échec transitoire du run de midi, ex: panne réseau/SSL).")
        import orchestrateur
        orchestrateur.main()
