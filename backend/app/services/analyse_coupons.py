"""Analyse des coupons envoyés : idées qui ont influencé la sélection (raisons de l'agent, absences, forme, contexte),
lecture des cotes (cote contre probabilité du modèle, valeur), risques (jambes fragiles, matchs partagés entre coupons).

Les chiffres sont calculés en Python à partir de la base ; l'IA rédige l'analyse à partir de ces seuls faits (jamais
d'information inventée). Hors-service ou illisible, l'analyse déterministe est envoyée à la place."""

import json
import math
import re

from app.services import pipeline

SEUIL_FRAGILE_PCT = 65.0
MAX_CARACTERES_MESSAGE = 3800  # limite Telegram : 4096


def _journal(run):
    """Journal de l'agent (stratégies + raisons par pari) conservé dans runs.detail ; {} s'il est absent."""
    detail = (run.detail or "") if run is not None else ""
    if not detail.startswith("JOURNAL_AGENT "):
        return {}
    try:
        return json.loads(detail[len("JOURNAL_AGENT "):])
    except ValueError:
        return {}


def faits_coupons(coupons):
    """Faits chiffrés par coupon + matchs partagés. Aucune interprétation ici."""
    par_match = {}
    for c in coupons:
        for j in c.jambes:
            par_match.setdefault(j.libelle_match, set()).add(c.nom)
    journal = _journal(coupons[0].run) if coupons else {}
    strategies, raisons = journal.get("strategies", {}), journal.get("raisons", {})
    faits = []
    for c in sorted(coupons, key=lambda c: c.profil):
        jambes = []
        for j in c.jambes:
            proba = j.proba_modele_pct
            implicite = round(100 / j.cote, 1) if j.cote else None
            raison = next((r.get("raison", "") for r in raisons.get(c.profil, [])
                           if r.get("match") and j.libelle_match.startswith(r["match"].split(" vs ")[0][:8])
                           and (r.get("cote") == j.cote)), "")
            jambes.append({"match": j.libelle_match, "marche": j.marche, "selection": j.selection, "cote": j.cote,
                           "proba_modele_pct": proba, "proba_implicite_cote_pct": implicite,
                           "ecart_pts": round(proba - implicite, 1) if proba is not None and implicite is not None else None,
                           "edge_pct": j.edge_pct, "raison_agent": (raison or "")[:260],
                           "partage_avec": sorted(par_match[j.libelle_match] - {c.nom})})
        probas = [x["proba_modele_pct"] for x in jambes if x["proba_modele_pct"] is not None]
        combinee = round(math.prod(p / 100 for p in probas) * 100, 1) if probas and len(probas) == len(jambes) else None
        faits.append({"coupon": c.nom, "cle": c.profil, "cote_totale": c.cote_totale, "nb_jambes": len(jambes),
                      "proba_combinee_pct": combinee, "strategie_agent": strategies.get(c.profil, ""),
                      "jambes_fragiles": [x["match"] + " — " + x["marche"] + " " + x["selection"]
                                          for x in jambes if x["proba_modele_pct"] is not None
                                          and x["proba_modele_pct"] < SEUIL_FRAGILE_PCT],
                      "matchs_partages": sorted({x["match"] for x in jambes if x["partage_avec"]}),
                      "jambes": jambes})
    return faits


def analyse_deterministe(faits):
    blocs = []
    for f in faits:
        lignes = [f"{f['coupon']} — cote {f['cote_totale']}, {f['nb_jambes']} jambes"
                  + (f", chance de passer ≈ {f['proba_combinee_pct']} %" if f["proba_combinee_pct"] is not None else "")]
        if f["strategie_agent"]:
            lignes.append(f"Idée de sélection : {f['strategie_agent'][:380]}")
        valeur = sorted((x for x in f["jambes"] if x["ecart_pts"] is not None), key=lambda x: -x["ecart_pts"])
        if valeur:
            best = valeur[0]
            lignes.append(f"Cotes : meilleure valeur {best['match']} ({best['selection']} @{best['cote']}, modèle "
                          f"{best['proba_modele_pct']} % contre {best['proba_implicite_cote_pct']} % implicite).")
        if f["jambes_fragiles"]:
            lignes.append("⚠️ Jambes fragiles (< 65 %) : " + "; ".join(f["jambes_fragiles"][:3]))
        if f["matchs_partages"]:
            lignes.append("Matchs présents dans un autre coupon : " + ", ".join(f["matchs_partages"][:4]))
        blocs.append("\n".join(lignes))
    return "\n\n".join(blocs)


def _nettoyer(texte):
    """Retire ce qui casse le Markdown de Telegram."""
    return re.sub(r"[_*`\[\]]", "", texte or "").strip()


def analyse_par_ia(faits, appel_llm):
    donnees = json.dumps(faits, ensure_ascii=False, separators=(",", ":"))
    if len(donnees) > 24000:  # prompt borné : on retire le détail des raisons
        for f in faits:
            for x in f["jambes"]:
                x["raison_agent"] = x["raison_agent"][:90]
        donnees = json.dumps(faits, ensure_ascii=False, separators=(",", ":"))
    prompt = (
        "Tu analyses 3 coupons combinés de football déjà envoyés. Voici les FAITS (base de données et raisons de l'agent "
        "de sélection) :\n" + donnees + "\n\nRédige en français, 1500 caractères maximum, sans markdown, pour CHAQUE coupon "
        "(🟢 petite cote, 🟠 cote moyenne, 🔴 haute cote) : 1) les idées qui ont influencé la sélection (forme, absences, "
        "contexte, style de jeu — UNIQUEMENT ce qui figure dans les raisons ou la stratégie), 2) la lecture des cotes (cote "
        "contre probabilité du modèle, où est la valeur), 3) le risque principal (jambe fragile, match partagé avec un autre "
        "coupon). N'invente aucune information. Si une raison manque, dis simplement que l'idée vient du modèle statistique.")
    try:
        texte = _nettoyer(appel_llm(prompt, 1200))
        return texte if len(texte) > 80 else None
    except Exception as e:
        print(f"ℹ️ Analyse IA indisponible ({str(e)[:100]}) — analyse déterministe.")
        return None


def message_analyse(db_coupons, avec_ia=True):
    faits = faits_coupons(db_coupons)
    if not faits:
        return None
    texte = None
    if avec_ia:
        _, ae, _ = pipeline.modules()
        texte = analyse_par_ia(faits, ae.appel_llm)
    corps = texte or analyse_deterministe(faits)
    entete = f"🔎 ANALYSE DES {len(faits)} COUPONS — {db_coupons[0].jour.isoformat()}\\n\\n".replace("\\n", "\n")
    return (entete + corps)[:MAX_CARACTERES_MESSAGE]
