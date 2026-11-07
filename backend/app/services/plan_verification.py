"""Agent de planification des vérifications : après l'envoi des coupons, analyse les matchs (coups d'envoi, écarts
entre matchs, matchs qui se terminent en même temps), planifie l'heure exacte des vérifications et l'heure du
rapport final, et l'annonce sur Telegram.

Les vagues et les bornes sont calculées en Python (déterministe) ; l'IA affine la première vérification et la cadence
de chaque vague et rédige l'analyse. Sa réponse est VALIDÉE : hors bornes ou illisible, on garde le plan déterministe."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Coupon, Jambe, PlanVerification
from app.services import pipeline

DJIBOUTI = timezone(timedelta(hours=3))  # heure d'affichage de l'utilisateur (UTC+3)
ECART_MEME_VAGUE_MIN = 20     # coups d'envoi à moins de 20 min : ils se terminent ensemble, vérifiés ensemble
PREMIERE_VERIF_MIN = 90       # 21h45 -> 23h15 (demande de l'utilisateur)
FIN_ESTIMEE_MIN = 115         # 90 min + mi-temps + arrêts de jeu
CADENCE_MIN = 15              # 23h15, 23h30, 23h45, 00h00... (quarts d'heure, comme le cron)
LIMITE_HEURES = 4             # au-delà : rapport final partiel
BORNES_PREMIERE_MIN = (90, 90)    # 21h45 -> 23h15 exactement : l'IA n'y touche pas
BORNES_CADENCE_MIN = (15, 30)


def _utc(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt):
    return _utc(dt).isoformat()


def hhmm(dt):
    """Heure de Djibouti, ex. '23h15'."""
    d = _utc(dt).astimezone(DJIBOUTI)
    return f"{d:%Hh%M}"


def analyser_matchs(coupons):
    """Matchs distincts des coupons : [{match_id, libelle, coup_envoi, nb_jambes}], triés par coup d'envoi, plus
    la liste des matchs sans coup d'envoi connu (vérifiés par le rattrapage horaire)."""
    par_match, sans_heure = {}, {}
    for c in coupons:
        for j in c.jambes:
            m = j.match
            if m is None or m.coup_envoi is None:
                sans_heure.setdefault(j.libelle_match, 0)
                sans_heure[j.libelle_match] += 1
                continue
            e = par_match.setdefault(m.id, {"match_id": m.id, "libelle": j.libelle_match,
                                            "coup_envoi": _utc(m.coup_envoi), "nb_jambes": 0})
            e["nb_jambes"] += 1
    return sorted(par_match.values(), key=lambda e: e["coup_envoi"]), sorted(sans_heure)


def construire_vagues(matchs):
    """Regroupe les matchs dont les coups d'envoi sont proches (ils se terminent en même temps)."""
    vagues, courante = [], []
    for m in matchs:
        if courante and (m["coup_envoi"] - courante[-1]["coup_envoi"]) > timedelta(minutes=ECART_MEME_VAGUE_MIN):
            vagues.append(courante)
            courante = []
        courante.append(m)
    if courante:
        vagues.append(courante)
    plan = []
    for i, v in enumerate(vagues):
        debut, dernier = v[0]["coup_envoi"], v[-1]["coup_envoi"]
        plan.append({
            "numero": i + 1, "match_ids": [m["match_id"] for m in v], "matchs": [m["libelle"] for m in v],
            "coup_envoi_premier": _iso(debut), "coup_envoi_dernier": _iso(dernier),
            "premiere_verif": _iso(debut + timedelta(minutes=PREMIERE_VERIF_MIN)),
            "cadence_min": CADENCE_MIN,
            "fin_estimee": _iso(dernier + timedelta(minutes=FIN_ESTIMEE_MIN)),
            "limite": _iso(dernier + timedelta(hours=LIMITE_HEURES)),
        })
    return plan


def finaliser(vagues, sans_heure, analyse):
    fin = max((datetime.fromisoformat(v["fin_estimee"]) for v in vagues), default=None)
    limite = max((datetime.fromisoformat(v["limite"]) for v in vagues), default=None)
    return {"vagues": vagues, "sans_heure": sans_heure, "analyse": analyse,
            "rapport_final_estime": _iso(fin + timedelta(minutes=CADENCE_MIN)) if fin else None,
            "echeance_rapport_final": _iso(limite) if limite else None}


def analyse_automatique(vagues):
    if not vagues:
        return "Aucun coup d'envoi connu : vérification de rattrapage chaque heure."
    morceaux = []
    for i, v in enumerate(vagues):
        morceaux.append(f"vague {v['numero']} : {len(v['match_ids'])} match(s) à {hhmm(datetime.fromisoformat(v['coup_envoi_premier']))}")
        if i:
            ecart = datetime.fromisoformat(v["coup_envoi_premier"]) - datetime.fromisoformat(vagues[i - 1]["coup_envoi_dernier"])
            morceaux[-1] += f" (+{int(ecart.total_seconds() // 60)} min après la précédente)"
    return "; ".join(morceaux)


def valider_ajustements(vagues, ajust):
    """Applique les ajustements de l'IA vague par vague s'ils sont dans les bornes ; ignore le reste."""
    if not isinstance(ajust, dict):
        return vagues, None
    par_numero = {a.get("numero"): a for a in ajust.get("vagues", []) if isinstance(a, dict)}
    for v in vagues:
        a = par_numero.get(v["numero"])
        if not a:
            continue
        debut = datetime.fromisoformat(v["coup_envoi_premier"])
        try:
            premiere = int(a.get("premiere_verif_apres_coup_envoi_min", PREMIERE_VERIF_MIN))
            cadence = int(a.get("cadence_min", CADENCE_MIN))
        except (TypeError, ValueError):
            continue
        if BORNES_PREMIERE_MIN[0] <= premiere <= BORNES_PREMIERE_MIN[1]:
            v["premiere_verif"] = _iso(debut + timedelta(minutes=premiere))
        if BORNES_CADENCE_MIN[0] <= cadence <= BORNES_CADENCE_MIN[1]:
            v["cadence_min"] = cadence
    analyse = ajust.get("analyse")
    return vagues, (analyse.strip()[:700] if isinstance(analyse, str) and analyse.strip() else None)


def plan_par_ia(vagues, sans_heure, appel_llm):
    faits = [{"numero": v["numero"], "matchs": v["matchs"], "coup_envoi_premier_heure_djibouti": hhmm(datetime.fromisoformat(v["coup_envoi_premier"])),
              "coup_envoi_dernier_heure_djibouti": hhmm(datetime.fromisoformat(v["coup_envoi_dernier"])),
              "fin_estimee_heure_djibouti": hhmm(datetime.fromisoformat(v["fin_estimee"]))} for v in vagues]
    prompt = (
        "Tu planifies la vérification des résultats de paris de football. Voici les vagues de matchs (matchs dont les "
        "coups d'envoi sont proches, vérifiés ensemble), en heure de Djibouti :\n" + json.dumps(faits, ensure_ascii=False)
        + f"\nRègle par défaut : première vérification {PREMIERE_VERIF_MIN} min après le coup d'envoi, puis toutes les "
          f"{CADENCE_MIN} min. Tu peux ajuster pour chaque vague (premiere_verif_apres_coup_envoi_min entre "
          f"{BORNES_PREMIERE_MIN[0]} et {BORNES_PREMIERE_MIN[1]}, cadence_min entre {BORNES_CADENCE_MIN[0]} et "
          f"{BORNES_CADENCE_MIN[1]}) en tenant compte de l'écart avec la vague précédente et de l'heure de fin estimée. "
          "Réponds UNIQUEMENT en JSON : {\"vagues\":[{\"numero\":1,\"premiere_verif_apres_coup_envoi_min\":90,\"cadence_min\":15}],"
          "\"analyse\":\"2-3 phrases en français : écarts entre matchs, matchs qui finissent en même temps, "
          "pourquoi ces horaires\"}")
    try:
        brut = appel_llm(prompt, 700, json_attendu=True)
        ajust = json.loads(brut) if isinstance(brut, str) else brut
    except Exception as e:  # IA indisponible ou JSON invalide : plan déterministe
        print(f"ℹ️ Agent IA de planification indisponible ({str(e)[:120]}) — plan déterministe.")
        return vagues, None
    return valider_ajustements(vagues, ajust)


def message_plan(plan, jour):
    lignes = [f"🗓️ *PLAN DE VÉRIFICATION — {jour}* (heure de Djibouti)", ""]
    for v in plan["vagues"]:
        ph = datetime.fromisoformat(v["premiere_verif"])
        lignes.append(f"*Vague {v['numero']}* — {len(v['match_ids'])} match(s), coup d'envoi "
                      f"{hhmm(datetime.fromisoformat(v['coup_envoi_premier']))}"
                      + (f"–{hhmm(datetime.fromisoformat(v['coup_envoi_dernier']))}" if v["coup_envoi_dernier"] != v["coup_envoi_premier"] else ""))
        lignes.append("   " + ", ".join(v["matchs"]))
        lignes.append(f"   ⏱️ 1re vérification à *{hhmm(ph)}* pile, puis toutes les {v['cadence_min']} min "
                      f"({hhmm(ph + timedelta(minutes=v['cadence_min']))}, "
                      f"{hhmm(ph + timedelta(minutes=2 * v['cadence_min']))}…), une exécution par heure prévue qui enregistre ce qu'elle trouve puis s'arrête, "
                      f"fin dès que les 3 coupons sont jugés ; "
                      f"fin estimée {hhmm(datetime.fromisoformat(v['fin_estimee']))}, dernière tentative {hhmm(datetime.fromisoformat(v['limite']))}")
    if plan["sans_heure"]:
        lignes.append(f"\n⚠️ {len(plan['sans_heure'])} match(s) sans heure connue : vérifiés une fois par heure.")
    if plan["rapport_final_estime"]:
        lignes.append(f"\n🏁 *Rapport final* attendu vers *{hhmm(datetime.fromisoformat(plan['rapport_final_estime']))}* "
                      f"(au plus tard {hhmm(datetime.fromisoformat(plan['echeance_rapport_final']))}, même si un match manque).")
    if plan.get("analyse"):
        lignes.append(f"\n🧠 {plan['analyse']}")
    return "\n".join(lignes)


def planifier(db, run_id=None, coupon_ids=None, notifier=None, avec_ia=True):
    """Construit (et enregistre) le plan des coupons d'un run ou d'une liste de coupons ; l'annonce via notifier."""
    requete = select(Coupon)
    if coupon_ids:
        requete = requete.where(Coupon.id.in_(coupon_ids))
    elif run_id is not None:
        requete = requete.where(Coupon.run_id == run_id)
    else:
        raise ValueError("run_id ou coupon_ids requis")
    coupons = list(db.scalars(requete))
    coupons = [c for c in coupons if c.jambes]
    if not coupons:
        return None
    matchs, sans_heure = analyser_matchs(coupons)
    vagues = construire_vagues(matchs)
    analyse = None
    if avec_ia and vagues:
        _, ae, _ = pipeline.modules()
        vagues, analyse = plan_par_ia(vagues, sans_heure, ae.appel_llm)
    plan = finaliser(vagues, sans_heure, analyse or analyse_automatique(vagues))
    plan["coupon_ids"] = [c.id for c in coupons]
    run = coupons[0].run_id
    # Un seul plan actif par run : replanifier remplace l'ancien (jamais deux plans qui se chevauchent).
    for ancien in db.scalars(select(PlanVerification).where(PlanVerification.run_id == run,
                                                            PlanVerification.rapport_final_envoye.is_(False))):
        db.delete(ancien)
    db.add(PlanVerification(run_id=run, plan=plan))
    db.commit()
    if notifier:
        notifier(message_plan(plan, coupons[0].jour.isoformat()))
    return plan


def points_de_verification(vague):
    """Heures exactes de la grille : première vérification + k × cadence, jusqu'à la limite. Chacune est lancée comme
    UNE exécution à son heure (jamais un job qui attend) ; on s'arrête dès que tous les matchs de la vague sont jugés."""
    debut = datetime.fromisoformat(vague["premiere_verif"])
    limite = datetime.fromisoformat(vague["limite"])
    pas = timedelta(minutes=max(vague.get("cadence_min", CADENCE_MIN), 1))
    points, t = [], debut
    while t <= limite:
        points.append(t)
        t += pas
    return points


def vagues_actives(db, maintenant=None):
    """[(plan_id, vague)] dont la fenêtre [première vérification, limite] est ouverte et qui ont encore une jambe en
    attente — filet de sécurité du cron horaire si une exécution à l'heure exacte a été manquée."""
    maintenant = _utc(maintenant or datetime.now(timezone.utc))
    actives = []
    for pv in db.scalars(select(PlanVerification).where(PlanVerification.rapport_final_envoye.is_(False))):
        for v in pv.plan.get("vagues", []):
            if not (datetime.fromisoformat(v["premiere_verif"]) <= maintenant <= datetime.fromisoformat(v["limite"])):
                continue
            if db.scalar(select(Jambe.id).where(Jambe.resultat == "en_attente",
                                                Jambe.match_id.in_(v["match_ids"])).limit(1)) is not None:
                actives.append((pv.id, v))
    return actives


def echeances_depassees(db, maintenant=None):
    """Plans dont l'heure limite du rapport final est passée sans que le rapport ait été envoyé."""
    maintenant = _utc(maintenant or datetime.now(timezone.utc))
    return [pv for pv in db.scalars(select(PlanVerification).where(PlanVerification.rapport_final_envoye.is_(False)))
            if pv.plan.get("echeance_rapport_final")
            and datetime.fromisoformat(pv.plan["echeance_rapport_final"]) <= maintenant]


FENETRE_CRON_MIN = 15  # le cron passe tous les quarts d'heure : un point de la grille est traité au passage qui le suit


def points_dus(db, maintenant=None):
    """[(vague, heure_du_point)] : points de la grille tombés dans les FENETRE_CRON_MIN dernières minutes, pour les
    vagues qui ont encore une jambe en attente. Utilisé par le cron autonome (coupons du run automatique du midi,
    sans session pour lancer chaque vérification à la minute)."""
    maintenant = _utc(maintenant or datetime.now(timezone.utc))
    dus = []
    for _, v in vagues_actives(db, maintenant):
        for t in points_de_verification(v):
            if maintenant - timedelta(minutes=FENETRE_CRON_MIN) < t <= maintenant:
                dus.append((v, t))
    return dus


def plans_ouverts(db):
    """Plans dont le rapport final n'a pas encore été envoyé."""
    return list(db.scalars(select(PlanVerification).where(PlanVerification.rapport_final_envoye.is_(False))))
