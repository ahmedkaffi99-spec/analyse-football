import os
import sys
from supabase import create_client

# Récupération des variables d'environnement
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Erreur critique : Les variables SUPABASE_URL et SUPABASE_KEY doivent être définies.")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def recuperer_donnees_supabase():
    print("Récupération des données depuis Supabase...")
    # Utilisation de 'matchs' au lieu de 'matches'
    reponse = supabase.table("matchs").select("*").execute()
    return reponse.data

if __name__ == "__main__":
    donnees_matchs = recuperer_donnees_supabase()
    print(f"Données récupérées avec succès : {donnees_matchs}")
