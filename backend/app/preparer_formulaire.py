"""Prépare le run du « Pipeline quotidien » à partir du formulaire « Run workflow » (06/11/2026 ; refonte du 07/11/2026). Pur Python (aucune dépendance) :
lu par le job `preparer` du workflow, qui écrit les sorties dans $GITHUB_OUTPUT. Le moteur agent produit TROIS coupons (prudent, équilibré, risque) ;
aucune cote totale cible ni cote par jambe n'est imposée : le formulaire n'a donc plus de nombre de coupons ni de bande de cote."""
import json
import os
import sys

# Les profils smart vivent à UN seul endroit (bet_agent/profils_smart.py, pur Python), partagé avec le profil de secours du moteur.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "bet_agent"))
from profils_smart import COULEURS, NIVEAUX, profils  # noqa: E402,F401

MODELES = {"deepseek": "", "deepseek-openrouter": "deepseek/deepseek-v4.1-flash", "gpt-6.1-sol": "openai/gpt-6.1-sol",
           "gemini-4-argon": "google/gemini-4-argon", "claude-sonnet-5.5": "anthropic/claude-sonnet-5.5"}
VOTE_DEFAUT = "openai/gpt-6.1-sol,google/gemini-4-argon"


def _choix(valeur, defaut="defaut"):
    v = (valeur or "").strip()
    return "" if v in ("", defaut) else v


def construire(env):
    evenement = env.get("EVENEMENT", "")
    moteur = _choix(env.get("MOTEUR"), "") or "agent"
    modele = _choix(env.get("MODELE"), "") or "deepseek"
    if modele not in MODELES:
        raise ValueError(f"modèle inconnu : {modele}")
    telegram = (env.get("TELEGRAM_IN") or "").strip().lower() == "true"
    vote = "aucun"
    if moteur != "agent":            # les autres moteurs ne connaissent ni pilote IA, ni profils personnalisés
        matrice = [{"etiquette": moteur, "pilote": ""}]
    else:
        matrice = [{"etiquette": modele, "pilote": MODELES[modele]}]
        if modele == "deepseek":     # vote final : seul le pilote DeepSeek est comparé aux autres modèles
            vote = (env.get("VOTE_VAR") or "").strip() or VOTE_DEFAUT
    sortie = {"matrice": json.dumps(matrice, ensure_ascii=False, separators=(",", ":")), "moteur": moteur,
              "telegram": "true" if telegram else "", "vote": vote, "date_debut": "", "date_fin": "", "ttl": ""}
    if evenement == "workflow_dispatch":
        sortie["ttl"] = "43200"
        sortie["date_debut"] = (env.get("DATE_DEBUT") or "").strip()
        sortie["date_fin"] = (env.get("DATE_FIN") or "").strip()
    sortie["cote_min_jambe"] = "0"   # plus de fourchette de cote par jambe (retirée le 06/11/2026) : 0 = aucune
    sortie["cote_max_jambe"] = "0"
    sortie["depuis_run"] = (env.get("DEPUIS_RUN") or "").strip()
    sortie["ignorer_diversite"] = "true"   # diversité de catégorie entre coupons retirée le 06/11/2026 (l'anti-doublon exact reste actif)
    # Les TROIS moteurs (agent, central, déterministe) reçoivent les mêmes trois profils de risque (07/11/2026) : comparaison équitable.
    liste = profils(un_pari_par_match=_choix(env.get("UN_PARI_PAR_MATCH"), "actif") != "desactive")
    sortie["profils"] = json.dumps(liste, ensure_ascii=False, separators=(",", ":"))
    return sortie


def ecrire(sortie, chemin):
    with open(chemin, "a", encoding="utf-8") as f:
        for cle, valeur in sortie.items():
            f.write(f"{cle}={valeur}\n")


if __name__ == "__main__":
    resultat = construire(os.environ)
    ecrire(resultat, os.environ.get("GITHUB_OUTPUT") or os.devnull)
    print(f"Moteur {resultat['moteur']} · matrice {resultat['matrice']} · Telegram {resultat['telegram'] or 'non'} · "
          f"vote {resultat['vote']} · reprise {resultat['depuis_run'] or 'non'}")
    sys.exit(0)
