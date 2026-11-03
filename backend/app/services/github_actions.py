"""Active / désactive le workflow de vérification pour qu'il ne tourne QUE pendant la vie des coupons : activé dès
que les coupons sont envoyés et planifiés, désactivé après le rapport final. Évite des centaines de passages à vide.
Sans GITHUB_TOKEN (tests, exécution locale) : ne fait rien, jamais d'erreur bloquante."""

import os

import requests

WORKFLOW_VERIFICATION = "verification-resultats.yml"


def activer_workflow(nom=WORKFLOW_VERIFICATION, actif=True, poster=requests.put):
    jeton, depot = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not jeton or not depot:
        print(f"ℹ️ GITHUB_TOKEN/GITHUB_REPOSITORY absents — workflow {nom} laissé tel quel.")
        return False
    action = "enable" if actif else "disable"
    try:
        r = poster(f"https://api.github.com/repos/{depot}/actions/workflows/{nom}/{action}",
                   headers={"Authorization": f"Bearer {jeton}", "Accept": "application/vnd.github+json"}, timeout=15)
    except Exception as e:  # jamais bloquant
        print(f"⚠️ {action} {nom} impossible : {str(e)[:120]}")
        return False
    ok = r.status_code in (200, 204)
    print(f"{'✅' if ok else '⚠️'} Workflow {nom} {'activé' if actif else 'désactivé'} (HTTP {r.status_code})")
    return ok
