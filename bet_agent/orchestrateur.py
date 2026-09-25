"""
ORCHESTRATEUR AGENTIC — remplace l'enchaînement fixe (main() de collecte_donnees.py puis
analyser_et_envoyer.py) par un LLM qui pilote le pipeline via tool-calling (function
calling), en s'appuyant sur les fonctions Python existantes comme outils. Le LLM REÇOIT
l'état réel du pipeline à chaque étape (matchs trouvés, stats dispo ou non, coupons générés)
et DÉCIDE de la marche à suivre — collecter, générer/envoyer les 3 coupons, ou abandonner.

Les seuils par profil de risque (sûr/équilibré/audacieux) sont FIXES et calculés en pur
Python (PROFILS_COUPON dans analyser_et_envoyer.py) — le LLM ne les choisit jamais lui-même,
il décide seulement QUAND appeler chaque outil et QUAND abandonner. Aucun chiffre (cote,
edge, probabilité) n'est jamais inventé par le LLM : uniquement calculés en pur Python
(Agent 3). La sélection interdite "12" reste bannie (déjà appliqué dans evaluer_marches).
"""

import os
import json
import time
import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

import collecte_donnees
import analyser_et_envoyer as ae

load_dotenv("envi.local")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODELE_ORCHESTRATEUR = "openai/gpt-oss-120b"

MAX_ITERATIONS = 6

etat = {"donnees": None, "termine": False}


# ============================================================
# OUTILS — chacun encapsule une étape déjà existante du pipeline (collecte, calcul
# Poisson, rédaction IA, envoi Telegram) sans jamais réinventer leur logique interne.
# ============================================================

def tool_collecter_donnees():
    collecte_donnees.collecter_donnees()
    with open(collecte_donnees.SORTIE_JSON, "r", encoding="utf-8") as f:
        donnees = json.load(f)
    etat["donnees"] = donnees
    return {
        "matchs_avec_marches": donnees["nb_matchs_avec_marches"],
        "marches_total": donnees["nb_marches_total"],
        "equipes_avec_vraies_stats_historiques": donnees["nb_equipes_avec_stats"],
        "vraies_stats_disponibles": donnees["nb_equipes_avec_stats"] > 0,
    }


def tool_generer_et_envoyer_trois_coupons():
    """Les 3 profils de risque (sûr / équilibré / audacieux) sont des seuils FIXES —
    décision déterministe, pas besoin de jugement du LLM ici (voir PROFILS_COUPON dans
    analyser_et_envoyer.py). L'orchestrateur n'a qu'à décider QUAND appeler cet outil et
    quoi faire s'il échoue — pas à choisir les seuils lui-même."""
    if etat["donnees"] is None:
        return {"erreur": "Aucune donnée collectée — appelle collecter_donnees d'abord."}

    resultats_profils = ae.generer_trois_coupons(etat["donnees"])
    if not any(item["selections"] for item in resultats_profils):
        return {
            "statut": "aucune_selection",
            "detail": "Aucun profil (sûr/équilibré/audacieux) n'a trouvé de sélection valable — envoie un abandon.",
        }

    sections = ae.agent4_rediger_trois_coupons(resultats_profils)
    tout_envoye = ae.agent5_envoyer_trois_coupons(sections)
    ae.sauvegarder_ticket_du_jour(resultats_profils)
    etat["termine"] = True
    return {
        "statut": "envoyé" if tout_envoye else "envoyé_partiellement",
        "detail": None if tout_envoye else "Au moins un des 3 messages Telegram a échoué — voir cron.log pour l'erreur exacte.",
        "jambes_par_profil": {item["profil"]["cle"]: len(item["selections"]) for item in resultats_profils},
    }


def tool_abandonner(raison):
    ae.notifier_telegram(f"⚠️ *Pas de ticket aujourd'hui*\n{raison}")
    etat["termine"] = True
    return {"statut": "message d'abandon envoyé sur Telegram"}


TOOL_IMPLS = {
    "collecter_donnees": tool_collecter_donnees,
    "generer_et_envoyer_trois_coupons": tool_generer_et_envoyer_trois_coupons,
    "abandonner": tool_abandonner,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "collecter_donnees",
            "description": (
                "Lance la collecte des matchs du jour (API-Football + OddsPapi + Serper). "
                "TOUJOURS le premier outil à appeler. Retourne combien de matchs ont des marchés "
                "1xbet exploitables et si les VRAIES stats historiques d'équipe sont disponibles "
                "(le quota API-Football gratuit peut être épuisé certains jours)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generer_et_envoyer_trois_coupons",
            "description": (
                "Calcule les 3 coupons à seuils fixes (🛡️ sûr / ⚖️ équilibré / 🔥 audacieux) à partir "
                "des données déjà collectées, fait rédiger chaque coupon par l'IA, envoie le tout en "
                "UN message Telegram, et sauvegarde le ticket pour la vérification des résultats du "
                "soir. Si aucun des 3 profils ne trouve de sélection valable, renvoie "
                "statut='aucune_selection' — dans ce cas, appelle abandonner ensuite. Termine le "
                "pipeline en cas de succès."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "abandonner",
            "description": (
                "Aucun pari fiable trouvé (collecte vide, ou generer_et_envoyer_trois_coupons a "
                "renvoyé statut='aucune_selection'). Envoie un message Telegram expliquant pourquoi "
                "et termine le pipeline."
            ),
            "parameters": {
                "type": "object",
                "properties": {"raison": {"type": "string"}},
                "required": ["raison"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "Tu es le chef de service du pipeline de paris combinés 1xBet. Réponds UNIQUEMENT en "
    "français dans tes messages, mais pilote le pipeline UNIQUEMENT via des appels d'outils "
    "(tool calls), jamais en texte libre.\n\n"
    "OBJECTIF : produire les 3 coupons du jour (sûr/équilibré/audacieux) si c'est "
    "raisonnablement possible, sinon abandonner proprement plutôt que d'inventer de la "
    "valeur. Les seuils de chaque profil sont FIXES et calculés en pur Python — tu n'as "
    "aucun seuil à choisir toi-même, seulement à décider de la marche à suivre.\n\n"
    "RÈGLES ABSOLUES :\n"
    "1. Appelle TOUJOURS collecter_donnees en premier.\n"
    "2. Si des matchs avec marchés ont été trouvés, appelle generer_et_envoyer_trois_coupons.\n"
    "3. Si collecter_donnees ne renvoie AUCUN match avec marché exploitable, ou si "
    "generer_et_envoyer_trois_coupons renvoie statut='aucune_selection', appelle abandonner "
    "avec une raison claire.\n"
    "4. Ne recalcule et n'invente JAMAIS toi-même une cote, un edge ou une probabilité — ces "
    "chiffres viennent uniquement des outils.\n"
    "5. Une fois generer_et_envoyer_trois_coupons (en cas de succès) ou abandonner appelé, "
    "arrête-toi : ne rappelle plus aucun outil."
)


def _est_erreur_transitoire(e):
    return isinstance(e, requests.exceptions.HTTPError) and e.response is not None and e.response.status_code in (429, 500, 502, 503)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=5, max=40),
       retry=retry_if_exception(_est_erreur_transitoire), reraise=True)
def appel_groq_tools(messages):
    payload = {
        "model": MODELE_ORCHESTRATEUR,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 1500,
    }
    r = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def main():
    print("🤖 Orchestrateur agentic démarré (modèle : Groq / " + MODELE_ORCHESTRATEUR + ")")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Lance le pipeline de paris combinés pour aujourd'hui."},
    ]

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n— Itération {iteration}/{MAX_ITERATIONS} —")
        try:
            data = appel_groq_tools(messages)
        except Exception as e:
            print(f"❌ Appel orchestrateur (Groq) échoué : {e}")
            break

        choix = data.get("choices", [{}])[0]
        msg = choix.get("message", {})
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            print("⚠️ L'orchestrateur a répondu sans appeler d'outil — arrêt de sécurité.")
            print("   Contenu :", msg.get("content"))
            break

        for tc in tool_calls:
            fname = tc.get("function", {}).get("name")
            try:
                fargs = json.loads(tc.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                fargs = {}
            print(f"🔧 Outil appelé : {fname}({fargs})")
            impl = TOOL_IMPLS.get(fname)
            if impl is None:
                resultat = {"erreur": f"Outil inconnu : {fname}"}
            else:
                try:
                    resultat = impl(**fargs)
                except Exception as e:
                    resultat = {"erreur": f"Échec de l'outil {fname} : {e}"}
            if isinstance(resultat, dict) and "selections" in resultat:
                apercu = dict(resultat)
                apercu["selections"] = f"{len(resultat['selections'])} sélection(s)"
                print(f"   → {apercu}")
            else:
                print(f"   → {resultat}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id"),
                "name": fname,
                "content": json.dumps(resultat, ensure_ascii=False),
            })

        if etat["termine"]:
            break

        time.sleep(3)  # évite de rafaler l'API Groq (429) entre deux décisions de l'orchestrateur
    else:
        print("⚠️ Limite d'itérations atteinte sans décision finale de l'orchestrateur.")

    if not etat["termine"]:
        print("🛑 Filet de sécurité : envoi d'un message d'abandon (l'orchestrateur n'a pas conclu).")
        tool_abandonner(
            "Le pilote agentic n'a pas abouti à une décision claire (limite d'itérations ou "
            "erreur) — vérifie les logs (cron.log) pour comprendre pourquoi."
        )

    print("\n✅ Orchestrateur terminé.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Erreur fatale de l'orchestrateur : {e}")
        try:
            ae.notifier_telegram(f"⚠️ *Orchestrateur échoué* — erreur inattendue : {e}")
        except Exception:
            pass
