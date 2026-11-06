"""Mémoire d'apprentissage de l'agent (06/11/2026, demande explicite : « une mémoire pour qu'il étudie les erreurs d'hier,
devienne pro de cette tâche et améliore avec le temps sa capacité de raisonnement »).

Cycle : après la vérification des résultats, `etudier_jour` analyse les coupons d'un jour (jambes perdues, jambes tueuses,
fiabilité des probabilités annoncées par tranche) et enregistre une étude (IA + repli déterministe) dans `memoire_agent` ;
à chaque run, `memoire_pour_prompt` renvoie les dernières études et les statistiques réelles glissantes, injectées dans la
mission de l'agent. Les chiffres sont toujours calculés en Python ; l'IA ne fait que rédiger les leçons à partir d'eux."""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Coupon, Jambe, MemoireAgent
from app.services import pipeline

TRANCHES_PROBA = ((0, 60, "moins de 60 %"), (60, 70, "60-70 %"), (70, 80, "70-80 %"), (80, 101, "80 % et plus"))
TRANCHES_COTE = ((0, 1.3, "cote < 1,30"), (1.3, 1.5, "cote 1,30-1,50"), (1.5, 2.0, "cote 1,50-2,00"), (2.0, 10**6, "cote 2,00 et plus"))
MIN_ECHANTILLON = 3          # en dessous : aucune leçon tirée (bruit)
MIN_ECHANTILLON_STATS = 5    # statistiques glissantes affichées à l'agent
LONGUEUR_ETUDE_MAX = 1400


def _tranche(valeur, tranches):
    for bas, haut, nom in tranches:
        if bas <= valeur < haut:
            return nom
    return None


def jambes_jugees(db, depuis=None, jour=None):
    requete = select(Jambe).join(Coupon, Jambe.coupon_id == Coupon.id).where(Jambe.resultat.in_(("gagne", "perdu")))
    if jour is not None:
        requete = requete.where(Coupon.jour == jour)
    if depuis is not None:
        requete = requete.where(Coupon.jour >= depuis)
    return list(db.scalars(requete))


def statistiques(jambes):
    """Fiabilité réelle par tranche de probabilité annoncée, par tranche de cote et par catégorie."""
    def vide():
        return {"n": 0, "gagnees": 0, "proba_annoncee_somme": 0.0}
    par_proba, par_cote, par_categorie = defaultdict(vide), defaultdict(vide), defaultdict(vide)
    for j in jambes:
        gagne = j.resultat == "gagne"
        cibles = [(par_categorie, j.categorie)]
        if j.proba_modele_pct is not None:
            cibles.append((par_proba, _tranche(j.proba_modele_pct, TRANCHES_PROBA)))
        if j.cote:
            cibles.append((par_cote, _tranche(j.cote, TRANCHES_COTE)))
        for dico, cle in cibles:
            if cle is None:
                continue
            dico[cle]["n"] += 1
            dico[cle]["gagnees"] += gagne
            dico[cle]["proba_annoncee_somme"] += j.proba_modele_pct or 0.0
    def finir(dico):
        sortie = {}
        for cle, v in dico.items():
            sortie[cle] = {"n": v["n"], "gagnees": v["gagnees"], "reussite_pct": round(100 * v["gagnees"] / v["n"], 1),
                           "annoncee_pct": round(v["proba_annoncee_somme"] / v["n"], 1)}
        return sortie
    return {"par_proba": finir(par_proba), "par_cote": finir(par_cote), "par_categorie": finir(par_categorie),
            "jambes_jugees": len(jambes)}


def faits_du_jour(db, jour):
    """Coupons du jour entièrement jugés, avec leurs jambes ; [] s'il en reste d'en attente."""
    coupons = [c for c in db.scalars(select(Coupon).where(Coupon.jour == jour)) if c.jambes]
    if not coupons or any(j.resultat == "en_attente" for c in coupons for j in c.jambes):
        return []
    faits = []
    for c in coupons:
        jambes = [{"match": j.libelle_match, "marche": j.marche, "selection": j.selection, "cote": j.cote,
                   "proba_pct": j.proba_modele_pct, "edge_pct": j.edge_pct, "resultat": j.resultat,
                   "categorie": j.categorie} for j in c.jambes]
        perdues = [x for x in jambes if x["resultat"] == "perdu"]
        faits.append({"coupon": c.nom, "statut": c.statut, "cote_totale": c.cote_totale, "nb_jambes": len(jambes),
                      "jambes_perdues": len(perdues), "jambes": jambes,
                      "perdu_par_une_jambe": c.statut == "perdu" and len(perdues) == 1})
    return faits


def lecons_deterministes(faits, stats):
    lecons = []
    perdus = [f for f in faits if f["statut"] == "perdu"]
    gagnes = [f for f in faits if f["statut"] == "gagne"]
    lecons.append(f"Bilan du jour : {len(gagnes)} coupon(s) gagné(s), {len(perdus)} perdu(s) sur {len(faits)}.")
    une = [f for f in perdus if f["perdu_par_une_jambe"]]
    if une:
        tueuses = "; ".join(f"{x['match']} — {x['marche']} {x['selection']} @{x['cote']} (annoncé {x['proba_pct']} %)"
                            for f in une for x in f["jambes"] if x["resultat"] == "perdu")
        lecons.append(f"{len(une)} coupon(s) perdu(s) par UNE seule jambe : {tueuses}. Une jambe de plus dans un coupon est une chance de plus de perdre.")
    for f in faits:
        for x in f["jambes"]:
            if x["resultat"] == "perdu" and (x["proba_pct"] or 0) >= 75:
                lecons.append(f"Jambe annoncée à {x['proba_pct']} % PERDUE : {x['match']} — {x['marche']} {x['selection']} : "
                              "une probabilité élevée ne protège pas ; vérifier si le contexte du match contredisait le modèle.")
    for tranche, v in stats["par_proba"].items():
        if v["n"] >= MIN_ECHANTILLON and v["annoncee_pct"] - v["reussite_pct"] >= 12:
            lecons.append(f"Jambes annoncées {tranche} (moyenne {v['annoncee_pct']} %) : réussite réelle {v['reussite_pct']} % "
                          f"({v['gagnees']}/{v['n']}) — le modèle est trop optimiste sur cette tranche.")
    return lecons


def _etude_par_ia(faits, stats, precedentes, appel_llm):
    donnees = json.dumps({"coupons": faits, "statistiques_du_jour": stats}, ensure_ascii=False, separators=(",", ":"))[:20000]
    memo = "\n".join(f"- {m}" for m in precedentes[:4]) or "(aucune)"
    prompt = (
        "Tu es l'analyste qui étudie les ERREURS d'un système de coupons combinés de football pour qu'il s'améliore. "
        "Voici les FAITS vérifiés d'un jour (coupons, jambes gagnées/perdues, probabilités annoncées) :\n" + donnees +
        "\n\nÉtudes précédentes (ne pas répéter ce qui y figure déjà) :\n" + memo +
        "\n\nRédige en français, 1200 caractères maximum, sans markdown : 1) ce qui a fait perdre ou gagner chaque coupon "
        "(jambe tueuse, marché, contexte), 2) trois RÈGLES CONCRÈTES et vérifiables pour les prochains coupons, fondées "
        "UNIQUEMENT sur ces chiffres (aucune règle tirée d'un échantillon de moins de 3 jambes ; ne dis jamais qu'un marché est "
        "« mauvais » sur 1 ou 2 cas), 3) une question à vérifier la prochaine fois. N'invente aucune information.")
    try:
        texte = (appel_llm(prompt, 1000) or "").strip()
        return texte if len(texte) > 120 else None
    except Exception as e:
        print(f"ℹ️ Étude IA indisponible ({str(e)[:100]}) — leçons déterministes.")
        return None


def etudier_jour(db, jour, avec_ia=True):
    """Étudie un jour de coupons et enregistre l'étude. Idempotent : une étude par jour. Renvoie le texte ou None."""
    if db.scalar(select(MemoireAgent.id).where(MemoireAgent.jour == jour, MemoireAgent.type == "etude")) is not None:
        return None
    faits = faits_du_jour(db, jour)
    if not faits:
        return None
    stats = statistiques(jambes_jugees(db, jour=jour))
    deterministes = lecons_deterministes(faits, stats)
    texte = None
    if avec_ia:
        _, ae, _ = pipeline.modules()
        precedentes = [m.contenu for m in db.scalars(select(MemoireAgent).order_by(MemoireAgent.jour.desc()).limit(4))]
        texte = _etude_par_ia(faits, stats, precedentes, ae.appel_llm)
    contenu = (("\n".join(deterministes) + "\nLEÇONS : " + texte) if texte else "\n".join(deterministes))[:LONGUEUR_ETUDE_MAX]
    db.add(MemoireAgent(jour=jour, type="etude", contenu=contenu, stats=stats))
    db.commit()
    return contenu


def etudier_recents(db, jours=7, avec_ia=True):
    """Étudie tous les jours récents entièrement jugés et pas encore étudiés."""
    faits = []
    aujourd_hui = datetime.now(timezone.utc).date()
    for decalage in range(jours, -1, -1):
        jour = aujourd_hui - timedelta(days=decalage)
        try:
            texte = etudier_jour(db, jour, avec_ia=avec_ia)
        except Exception as e:
            print(f"⚠️ Étude du {jour} impossible : {str(e)[:120]}")
            continue
        if texte:
            faits.append(jour)
    return faits


def memoire_pour_prompt(db, max_etudes=6, jours_stats=21):
    """Texte de mémoire injecté dans la mission de l'agent ; None si rien n'a encore été appris."""
    etudes = list(db.scalars(select(MemoireAgent).where(MemoireAgent.type == "etude").order_by(MemoireAgent.jour.desc()).limit(max_etudes)))
    depuis = datetime.now(timezone.utc).date() - timedelta(days=jours_stats)
    stats = statistiques(jambes_jugees(db, depuis=depuis))
    lignes = []
    for tranche, v in sorted(stats["par_proba"].items()):
        if v["n"] >= MIN_ECHANTILLON_STATS:
            lignes.append(f"- Jambes annoncées {tranche} : réussite réelle {v['reussite_pct']} % ({v['gagnees']}/{v['n']}), "
                          f"probabilité annoncée moyenne {v['annoncee_pct']} %.")
    for cat, v in sorted(stats["par_categorie"].items(), key=lambda kv: kv[1]["reussite_pct"]):
        if v["n"] >= MIN_ECHANTILLON_STATS and (v["reussite_pct"] < 45 or v["reussite_pct"] >= 75):
            lignes.append(f"- Catégorie {cat} : {v['reussite_pct']} % de réussite réelle ({v['gagnees']}/{v['n']}).")
    if not etudes and not lignes:
        return None
    blocs = ["MÉMOIRE D'APPRENTISSAGE (études de TES erreurs et réussites des jours précédents, vérifiées sur les résultats réels). "
             "Applique ces leçons : ne répète pas une erreur déjà étudiée ; si une leçon contredit ton analyse d'un match précis, "
             "justifie-le en une phrase."]
    if lignes:
        blocs.append(f"FIABILITÉ RÉELLE sur les {jours_stats} derniers jours ({stats['jambes_jugees']} jambes jugées) :\n" + "\n".join(lignes))
    for e in etudes:
        blocs.append(f"ÉTUDE DU {e.jour.isoformat()} :\n{e.contenu}")
    return "\n\n".join(blocs)
