import os
import requests
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def recuperer_donnees_supabase():
    reponse = supabase.table("matches").select("*").execute()
    return reponse.data

def analyser_avec_deepseek(donnees):
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"Voici les données des matchs récupérées de Supabase : {donnees}. Agis en tant qu'expert en paris sportifs, analyse ces données et génère le meilleur coupon stratégique sous format JSON."

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    resultat = response.json()
    return resultat["choices"][0]["message"]["content"]

if __name__ == "__main__":
    print("Récupération des données depuis Supabase...")
    donnees_matchs = recuperer_donnees_supabase()
    
    print("Envoi des données à DeepSeek...")
    strategie = analyser_avec_deepseek(donnees_matchs)
    
    print("Résultat :")
    print(strategie)

