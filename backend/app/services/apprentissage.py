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
from app.services.envoyes import condition_coupon_envoye

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


def _pct(valeur):
    """« 77.4 % » ou, quand la probabilité n'a pas été enregistrée, « probabilité non enregistrée » (jamais « None % »)."""
    return "probabilité non enregistrée" if valeur is None else f"{valeur} %"


def _cle_jambe(j):
    return (j.libelle_match, j.marche, j.selection, j.handicap)


def jambes_jugees(db, depuis=None, jour=None):
    """Jambes jugées, DÉDOUBLONNÉES : une même jambe (match, marché, sélection) présente dans plusieurs coupons du même jour
    ne compte qu'une fois — sinon une seule défaite pèse autant que le nombre de coupons qui la contiennent (06/11/2026)."""
    requete = select(Jambe, Coupon.jour).join(Coupon, Jambe.coupon_id == Coupon.id).where(
        Jambe.resultat.in_(("gagne", "perdu")), condition_coupon_envoye())   # jamais les coupons d'un run non envoyé
    if jour is not None:
        requete = requete.where(Coupon.jour == jour)
    if depuis is not None:
        requete = requete.where(Coupon.jour >= depuis)
    vues, uniques = set(), []
    for j, jour_coupon in db.execute(requete):
        cle = (jour_coupon,) + _cle_jambe(j)
        if cle not in vues:
            vues.add(cle)
            uniques.append(j)
    return uniques


def statistiques(jambes):
    """Fiabilité réelle par tranche de probabilité annoncée, par tranche de cote et par catégorie."""
    def vide():
        return {"n": 0, "gagnees": 0, "n_proba": 0, "proba_annoncee_somme": 0.0}
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
            if j.proba_modele_pct is not None:   # une jambe SANS probabilité enregistrée ne compte jamais comme « 0 % annoncé » (07/11/2026)
                dico[cle]["n_proba"] += 1
                dico[cle]["proba_annoncee_somme"] += j.proba_modele_pct
    def finir(dico):
        sortie = {}
        for cle, v in dico.items():
            sortie[cle] = {"n": v["n"], "gagnees": v["gagnees"], "reussite_pct": round(100 * v["gagnees"] / v["n"], 1),
                           # moyenne annoncée calculée sur les SEULES jambes qui ont une probabilité ; None si aucune
                           "annoncee_pct": round(v["proba_annoncee_somme"] / v["n_proba"], 1) if v["n_proba"] else None}
            if v["n_proba"] < v["n"]:
                sortie[cle]["sans_proba"] = v["n"] - v["n_proba"]
        return sortie
    return {"par_proba": finir(par_proba), "par_cote": finir(par_cote), "par_categorie": finir(par_categorie),
            "jambes_jugees": len(jambes), **({"jambes_sans_proba": sum(1 for j in jambes if j.proba_modele_pct is None)}
                                             if any(j.proba_modele_pct is None for j in jambes) else {})}


def faits_du_jour(db, jour):
    """Coupons du jour entièrement jugés, avec leurs jambes ; [] s'il en reste d'en attente.
    `jambes_uniques` : chaque jambe une seule fois, avec le nombre de coupons qui la contenaient ;
    `matchs_pieges` : matchs où au moins 2 jambes DIFFÉRENTES ont perdu (un seul scénario inattendu)."""
    coupons = [c for c in db.scalars(select(Coupon).where(Coupon.jour == jour, condition_coupon_envoye())) if c.jambes]
    if not coupons or any(j.resultat == "en_attente" for c in coupons for j in c.jambes):
        return []
    faits, uniques = [], {}
    for c in coupons:
        jambes = []
        for j in c.jambes:
            x = {"match": j.libelle_match, "marche": j.marche, "selection": j.selection, "cote": j.cote,
                 "proba_pct": j.proba_modele_pct, "edge_pct": j.edge_pct, "resultat": j.resultat, "categorie": j.categorie}
            jambes.append(x)
            u = uniques.setdefault(_cle_jambe(j), {**x, "nb_coupons": 0})
            u["nb_coupons"] += 1
        perdues = [x for x in jambes if x["resultat"] == "perdu"]
        faits.append({"coupon": c.nom, "statut": c.statut, "cote_totale": c.cote_totale, "nb_jambes": len(jambes),
                      "jambes_perdues": len(perdues), "jambes": jambes,
                      "perdu_par_une_jambe": c.statut == "perdu" and len(perdues) == 1})
    pieges = defaultdict(list)
    for u in uniques.values():
        if u["resultat"] == "perdu":
            pieges[u["match"]].append(f"{u['marche']} {u['selection']}")
    return {"coupons": faits, "jambes_uniques": list(uniques.values()),
            "matchs_pieges": {m: v for m, v in pieges.items() if len(v) >= 2}}


def lecons_deterministes(faits, stats):
    coupons = faits["coupons"]
    lecons = []
    perdus = [f for f in coupons if f["statut"] == "perdu"]
    gagnes = [f for f in coupons if f["statut"] == "gagne"]
    lecons.append(f"Bilan du jour : {len(gagnes)} coupon(s) gagné(s), {len(perdus)} perdu(s) sur {len(coupons)}.")
    une = [f for f in perdus if f["perdu_par_une_jambe"]]
    vus = set()   # jambes déjà citées : jamais répétées dans une autre leçon
    if une:
        tueuses = []
        for f in une:
            for x in f["jambes"]:
                cle = (x["match"], x["marche"], x["selection"])
                if x["resultat"] == "perdu" and cle not in vus:
                    vus.add(cle)
                    tueuses.append(f"{x['match']} — {x['marche']} {x['selection']} @{x['cote']} (annoncé {_pct(x['proba_pct'])})")
        lecons.append(f"{len(une)} coupon(s) perdu(s) par UNE seule jambe ({len(tueuses)} jambe(s) différente(s)) : "
                      + "; ".join(tueuses[:5]) + ". Une jambe de plus dans un coupon est une chance de plus de perdre.")
    for match, jambes in faits["matchs_pieges"].items():
        lecons.append(f"Match piège : {match} — {len(jambes)} jambes DIFFÉRENTES perdues ({'; '.join(jambes[:3])}) : plusieurs "
                      "paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.")
    fortes = sorted((u for u in faits["jambes_uniques"] if u["resultat"] == "perdu" and (u["proba_pct"] or 0) >= 75),
                    key=lambda u: -(u["proba_pct"] or 0))[:4]
    for u in fortes:
        if (u["match"], u["marche"], u["selection"]) in vus:
            continue
        lecons.append(f"Jambe annoncée à {u['proba_pct']} % perdue : {u['match']} — {u['marche']} {u['selection']} "
                      f"(dans {u['nb_coupons']} coupon(s)).")
    for tranche, v in stats["par_proba"].items():
        if v["n"] >= MIN_ECHANTILLON and v["annoncee_pct"] is not None and v["annoncee_pct"] - v["reussite_pct"] >= 12:
            lecons.append(f"Jambes annoncées {tranche} (moyenne {v['annoncee_pct']} %) : réussite réelle {v['reussite_pct']} % "
                          f"(n={v['n']}) — le modèle est trop optimiste sur cette tranche.")
    return lecons


def _etude_par_ia(faits, stats, precedentes, appel_llm):
    donnees = json.dumps({"coupons": [{k: v for k, v in f.items() if k != "jambes"} for f in faits["coupons"]],
                          "jambes_uniques": faits["jambes_uniques"], "matchs_pieges": faits["matchs_pieges"],
                          "statistiques_du_jour": stats}, ensure_ascii=False, separators=(",", ":"))[:20000]
    memo = "\n".join(f"- {m[:500]}" for m in precedentes[:4]) or "(aucune)"
    prompt = (
        "Tu es l'analyste qui étudie les ERREURS d'un système de coupons combinés de football pour qu'il s'améliore. "
        "Voici les FAITS vérifiés d'un jour (chaque jambe est comptée UNE seule fois, nb_coupons = nombre de coupons qui la "
        "contenaient) :\n" + donnees + "\n\nÉtudes précédentes (ne pas répéter ce qui y figure déjà) :\n" + memo +
        "\n\nRédige en français, 1200 caractères maximum, sans markdown : 1) ce qui a fait perdre ou gagner chaque coupon "
        "(jambe tueuse, match piège, marché), 2) au plus TROIS règles concrètes pour les prochains coupons. RÈGLES DE "
        "RIGUEUR : chaque règle doit citer entre parenthèses l'effectif sur lequel elle repose, sous la forme (n=NOMBRE) "
        "avec NOMBRE >= 3 jambes ou matchs comparables pris dans les faits ci-dessus ; n'écris AUCUNE règle sur un marché, "
        "une équipe ou un « biais du modèle » à partir de 1 ou 2 cas — dans ce cas écris seulement « à surveiller » ; un "
        "edge élevé sur une jambe perdue n'est pas la preuve d'un biais ; 3) une question à vérifier la prochaine fois. "
        "N'invente aucune information.")
    try:
        texte = (appel_llm(prompt, 1000) or "").strip()
    except Exception as e:
        print(f"ℹ️ Étude IA indisponible ({str(e)[:100]}) — leçons déterministes.")
        return None
    if len(texte) <= 120:
        return None
    if "n=" not in texte.replace(" ", ""):   # aucune règle chiffrée : texte écarté plutôt que mémorisé
        print("ℹ️ Étude IA sans effectif chiffré (n=…) — écartée, leçons déterministes conservées.")
        return None
    return texte


def etudier_jour(db, jour, avec_ia=True, refaire=False, ecrire=True):
    """Étudie un jour de coupons et enregistre l'étude. Idempotent : une étude par jour (refaire=True : recalcule et remplace
    l'étude de ce jour — la mémoire est une table dérivée, jamais une donnée d'origine). Renvoie le texte ou None.
    ecrire=False (aperçu, Phase 3) : calcule la nouvelle étude à partir des coupons envoyés SANS rien écrire ni supprimer en base."""
    existante = db.scalars(select(MemoireAgent).where(MemoireAgent.jour == jour, MemoireAgent.type == "etude")).all()
    if existante and not refaire:
        return None
    faits = faits_du_jour(db, jour)
    if not faits:
        return None
    if ecrire:
        for m in existante:
            db.delete(m)
    stats = statistiques(jambes_jugees(db, jour=jour))
    deterministes = lecons_deterministes(faits, stats)
    texte = None
    if avec_ia:
        _, ae, _ = pipeline.modules()
        precedentes = [m.contenu for m in db.scalars(select(MemoireAgent).order_by(MemoireAgent.jour.desc()).limit(4))]
        texte = _etude_par_ia(faits, stats, precedentes, ae.appel_llm)
    contenu = (("\n".join(deterministes) + "\nLEÇONS : " + texte) if texte else "\n".join(deterministes))[:LONGUEUR_ETUDE_MAX]
    if ecrire:
        db.add(MemoireAgent(jour=jour, type="etude", contenu=contenu, stats=stats))
        db.commit()
    return contenu


def exporter_memoire(db):
    """Copie intégrale de la mémoire (lecture seule) : liste de dicts sérialisables, pour la sauvegarde avant toute régénération."""
    return [{"id": m.id, "cree_le": m.cree_le.isoformat() if m.cree_le else None, "jour": m.jour.isoformat(), "type": m.type,
             "contenu": m.contenu, "stats": m.stats} for m in db.scalars(select(MemoireAgent).order_by(MemoireAgent.id))]


def etudier_recents(db, jours=7, avec_ia=True, refaire=False):
    """Étudie tous les jours récents entièrement jugés et pas encore étudiés."""
    faits = []
    aujourd_hui = datetime.now(timezone.utc).date()
    for decalage in range(jours, -1, -1):
        jour = aujourd_hui - timedelta(days=decalage)
        try:
            texte = etudier_jour(db, jour, avec_ia=avec_ia, refaire=refaire)
        except Exception as e:
            print(f"⚠️ Étude du {jour} impossible : {str(e)[:120]}")
            continue
        if texte:
            faits.append(jour)
    return faits


def memoire_pour_prompt(db, max_etudes=6, jours_stats=21):
    """Texte de mémoire injecté dans la mission de l'agent ; None si rien n'a encore été appris."""
    # Seules les études d'un jour ayant au moins un coupon RÉELLEMENT envoyé sont relues : une étude bâtie uniquement sur des runs d'essai
    # n'a jamais décrit un résultat réel (Phase 2, 06/11/2026). Les lignes restent en base, simplement ignorées.
    jours_envoyes = select(Coupon.jour).where(condition_coupon_envoye())
    etudes = list(db.scalars(select(MemoireAgent).where(MemoireAgent.type == "etude", MemoireAgent.jour.in_(jours_envoyes))
                             .order_by(MemoireAgent.jour.desc()).limit(max_etudes)))
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
