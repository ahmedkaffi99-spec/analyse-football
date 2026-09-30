"""
Diagnostic rapide : teste séparément chaque source de données utilisée par
collecte_donnees.py / abdi.py, pour trouver précisément pourquoi API-Football,
TheSportsDB et ClubElo sont revenus vides (0/30 équipes) lors de la dernière
collecte, alors qu'OddsPapi fonctionnait.

Lance-le depuis le dossier bet_agent (là où se trouve envi.local) :
    python diagnostic.py
"""
import os
import requests
import urllib3
from dotenv import load_dotenv

load_dotenv("envi.local")

# Vérification du certificat OddsPapi : ACTIVE par défaut (GitHub Actions, serveur, PC).
# ODDSPAPI_SSL_NON_VERIFIE=true seulement sur un réseau qui intercepte le certificat (boîtier
# Fortinet constaté sur l'ancien environnement Termux) — jamais pour les autres APIs.
VERIFIER_SSL_ODDSPAPI = os.getenv("ODDSPAPI_SSL_NON_VERIFIE", "").lower() not in ("1", "true", "oui")
if not VERIFIER_SSL_ODDSPAPI:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
ODDSPAPI_KEY = os.getenv("ODDSPAPI_KEY")


def ligne(titre):
    print(f"\n{'=' * 60}\n{titre}\n{'=' * 60}")


def test_cle(nom, valeur):
    if not valeur:
        print(f"   ❌ {nom} absente de envi.local")
    else:
        print(f"   ✓ {nom} présente ({len(valeur)} caractères)")


ligne("1) Clés présentes dans envi.local ?")
for nom in ["API_FOOTBALL_KEY", "ODDSPAPI_KEY", "SERPER_API_KEY",
            "GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
            "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]:
    test_cle(nom, os.getenv(nom))

ligne("2) API-Football (/status — 1 seul appel, ne consomme pas le quota /fixtures)")
try:
    r = requests.get("https://v3.football.api-sports.io/status",
                      headers={"x-apisports-key": API_FOOTBALL_KEY or ""}, timeout=15)
    print(f"   status_code = {r.status_code}")
    print(f"   corps = {r.text[:500]}")
except Exception as e:
    print(f"   ❌ ÉCHEC RÉSEAU : {type(e).__name__} : {e}")

ligne("3) API-Football (/leagues?team= — vérifie que le compte peut résoudre une équipe)")
try:
    r = requests.get("https://v3.football.api-sports.io/leagues",
                      headers={"x-apisports-key": API_FOOTBALL_KEY or ""},
                      params={"team": 541}, timeout=15)  # 541 = Real Madrid
    print(f"   status_code = {r.status_code}")
    print(f"   corps = {r.text[:500]}")
except Exception as e:
    print(f"   ❌ ÉCHEC RÉSEAU : {type(e).__name__} : {e}")

ligne("4) ClubElo (endpoint public, HTTP, aucune clé)")
try:
    from datetime import datetime
    d = datetime.now().strftime("%Y-%m-%d")
    r = requests.get(f"http://api.clubelo.com/{d}", timeout=15)
    print(f"   status_code = {r.status_code}")
    print(f"   1ère ligne = {r.text.splitlines()[0] if r.text else '(vide)'}")
    print(f"   nb lignes total = {len(r.text.splitlines())}")
except Exception as e:
    print(f"   ❌ ÉCHEC RÉSEAU : {type(e).__name__} : {e}")

ligne("5) OddsPapi (certificat vérifié sauf si ODDSPAPI_SSL_NON_VERIFIE=true)")
try:
    r = requests.get("https://api.oddspapi.io/v4/sports",
                      params={"apiKey": ODDSPAPI_KEY or ""}, timeout=15, verify=VERIFIER_SSL_ODDSPAPI)
    print(f"   status_code = {r.status_code}")
    print(f"   corps = {r.text[:300]}")
except Exception as e:
    print(f"   ❌ ÉCHEC RÉSEAU : {type(e).__name__} : {e}")

ligne("6) Understat (HTML, aucune clé)")
try:
    from datetime import datetime
    maintenant = datetime.now()
    saison = maintenant.year if maintenant.month >= 7 else maintenant.year - 1
    r = requests.get(f"https://understat.com/league/Ligue_1/{saison}", timeout=15,
                      headers={"User-Agent": "Mozilla/5.0"})
    print(f"   status_code = {r.status_code}, taille corps = {len(r.text)} caractères")
except Exception as e:
    print(f"   ❌ ÉCHEC RÉSEAU : {type(e).__name__} : {e}")

print("\n\nEnvoie-moi la sortie complète de ce script (copier-coller le terminal) —")
print("ça me dira exactement laquelle des 4 sources échoue et pourquoi (clé, quota,")
print("certificat SSL intercepté, ou blocage réseau pur).")
