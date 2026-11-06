"""Prépare le run du « Pipeline quotidien » à partir du formulaire « Run workflow » (06/11/2026). Pur Python (aucune dépendance) : lu par
le job `preparer` du workflow, qui écrit les sorties dans $GITHUB_OUTPUT. Chaque liste déroulante vaut « defaut » quand on n'y touche pas :
le run garde alors exactement le comportement smart habituel (3 coupons, bandes 5-10 / 12-18 / 20-35, aucun plancher ni plafond par jambe)."""
import json
import os
import sys

BANDES_DEFAUT = [(5, 10), (12, 18), (20, 35)]
COULEURS = ["🟢", "🟠", "🔴", "🔵", "🟣"]
MODELES = {"deepseek": "", "gpt-6.1-sol": "openai/gpt-6.1-sol", "gemini-4-argon": "google/gemini-4-argon",
           "claude-sonnet-5.5": "anthropic/claude-sonnet-5.5"}
VOTE_DEFAUT = "openai/gpt-6.1-sol,google/gemini-4-argon"
CONSIGNE = ("Smart coupon : tu choisis LIBREMENT les paris et le nombre de jambes les plus probables et les mieux valorisés ; seule "
            "contrainte : la cote totale doit être dans la bande de ce profil (une seule sélection par match dans un coupon).")


def _choix(valeur, defaut="defaut"):
    v = (valeur or "").strip()
    return "" if v in ("", defaut) else v


def _nombre(valeur):
    v = _choix(valeur)
    return int(v) if v.isdigit() else None


def _bande(texte):
    """« 12-18 » -> (12.0, 18.0)."""
    a, _, b = texte.partition("-")
    return float(a), float(b)


def profils(nb_coupons=None, cotes=None, nb_min=None, nb_max=None, un_pari_par_match=True):
    """Liste de profils. `cotes` : une bande (« 12-18 ») ou None par coupon ; sans choix, bande smart du rang du coupon (5-10, 12-18,
    20-35, puis on recommence). Les choix au-delà du nombre de coupons sont ignorés."""
    n = nb_coupons or 3
    cotes = list(cotes or [])
    bandes = [_bande(cotes[i]) if i < len(cotes) and cotes[i] else BANDES_DEFAUT[i % 3] for i in range(n)]
    maximum = nb_max or 12
    minimum = min(nb_min or 1, maximum)
    sortie = []
    for i, (bas, haut) in enumerate(bandes):
        b0, b1 = f"{bas:g}", f"{haut:g}"
        sortie.append({
            "cle": f"coupon{i + 1}", "nom": f"{COULEURS[i % 5]} SMART COUPON — cote {b0} à {b1}",
            "cote_min": bas, "cote_max": haut, "cote_totale_min": bas, "cote_totale_max": haut,
            "nb_jambes_min": minimum, "nb_jambes": maximum, "proba_min_pct": 30, "proba_max_pct": 100,
            "jambes_max_par_match": 1 if un_pari_par_match else 3, "match_repete_autorise": True,
            "max_coupons_par_match": 3, "un_seul_pari_par_event": True, "consigne": CONSIGNE})
    return sortie


def construire(env):
    evenement = env.get("EVENEMENT", "")
    moteur = _choix(env.get("MOTEUR"), "") or "agent"
    modele = _choix(env.get("MODELE"), "") or "deepseek"
    if modele not in MODELES:
        raise ValueError(f"modèle inconnu : {modele}")
    telegram = (env.get("TELEGRAM_IN") or "").strip().lower() == "true"
    ombre = (env.get("OMBRE_IN") or "").strip()
    vote = "aucun"
    if moteur != "agent":            # les autres moteurs ne connaissent ni pilote IA, ni profils personnalisés
        matrice = [{"etiquette": moteur, "pilote": ""}]
    else:
        matrice = [{"etiquette": modele, "pilote": MODELES[modele]}]
        if modele == "deepseek":     # vote final : seul le pilote DeepSeek est comparé aux autres modèles
            vote = (env.get("VOTE_VAR") or "").strip() or VOTE_DEFAUT
        else:
            ombre = ombre or "aucun"
    sortie = {"matrice": json.dumps(matrice, ensure_ascii=False, separators=(",", ":")), "moteur": moteur,
              "telegram": "true" if telegram else "", "ombre": ombre, "vote": vote, "date_debut": "", "date_fin": "", "ttl": ""}
    if evenement == "workflow_dispatch":
        sortie["ttl"] = "43200"
        sortie["date_debut"] = (env.get("DATE_DEBUT") or "").strip()
        sortie["date_fin"] = (env.get("DATE_FIN") or "").strip()
    cote_min, cote_max = _choix(env.get("COTE_MIN_JAMBE")), _choix(env.get("COTE_MAX_JAMBE"))
    sortie["cote_min_jambe"] = cote_min or "1.01"       # smart coupon : aucun plancher par jambe
    sortie["cote_max_jambe"] = cote_max or "0"          # 0 = aucun plafond par jambe
    sortie["depuis_run"] = (env.get("DEPUIS_RUN") or "").strip()
    sortie["ignorer_diversite"] = "true" if (env.get("IGNORER_DIVERSITE") or "").strip().lower() == "true" else ""
    if moteur == "agent":
        liste = profils(_nombre(env.get("NB_COUPONS")), [_choix(env.get(f"COTE_COUPON_{i}")) or None for i in range(1, 6)],
                        _nombre(env.get("NB_JAMBES_MIN")), _nombre(env.get("NB_JAMBES_MAX")),
                        un_pari_par_match=_choix(env.get("UN_PARI_PAR_MATCH"), "actif") != "desactive")
        sortie["profils"] = json.dumps(liste, ensure_ascii=False, separators=(",", ":"))
    else:
        sortie["profils"] = ""
    return sortie


def ecrire(sortie, chemin):
    with open(chemin, "a", encoding="utf-8") as f:
        for cle, valeur in sortie.items():
            f.write(f"{cle}={valeur}\n")


if __name__ == "__main__":
    resultat = construire(os.environ)
    ecrire(resultat, os.environ.get("GITHUB_OUTPUT") or os.devnull)
    print(f"Moteur {resultat['moteur']} · matrice {resultat['matrice']} · Telegram {resultat['telegram'] or 'non'} · "
          f"vote {resultat['vote']} · ombre {resultat['ombre'] or 'défaut'} · reprise {resultat['depuis_run'] or 'non'}")
    sys.exit(0)
