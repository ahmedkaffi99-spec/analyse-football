"""Capture PROSPECTIVE des cotes dans hist_cotes (demande explicite du 10/10/2026) : "rendre
possible une vraie mesure future du ROI... Utilise uniquement les cotes réellement récupérées
auprès d'OddsPapi au moment du run". Deux fonctions :

- capturer_predictions(db, run, pool) : appelée depuis CHAQUE run réel (runs.py), juste après
  que la sélection/les probabilités/le texte Telegram sont déjà figés — lecture seule du pool,
  écriture additive dans hist_cotes. Ne modifie JAMAIS la sélection, les probabilités, ni la
  calibration (non branchée ici), ne remplace jamais bet_agent, ne fabrique aucune cote.
- juger_cotes_en_attente(db) : une fois le match terminé, associe le résultat réel (même
  logique de jugement que backend/app/services/verification.py::verifier_jambes, réutilisant
  les fonctions pures de bet_agent/verifier_resultats.py — jamais de duplication de règles).

Dédoublonnage (contrainte explicite "évite les doublons si le même match/marché est traité
plusieurs fois") : une capture par (jour UTC, fixture_id_oddspapi, marché, ligne, sélection) —
le cron quotidien tourne plusieurs fois par jour (pipeline-quotidien.yml) et revoit souvent les
mêmes candidats avant qu'un coupon ne soit finalement envoyé ; seule la PREMIÈRE cote vue dans
la journée est conservée (ON CONFLICT DO NOTHING), jamais écrasée par un passage ultérieur."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models_historique import HistCote

VERDICT_VERS_RESULTAT = {"gagne": "gagne", "perdu": "perdu", "push": "push", None: "non_verifiable"}


def _coup_envoi(date_iso):
    if not date_iso:
        return None
    try:
        d = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _comparaison_moteur(db, pool):
    """proba_moteur_pct/edge_moteur_pct/modele_moteur par (match, marché affiché, sélection),
    quand le moteur a pu prédire (historique réel suffisant) — jamais inventé, voir
    comparaison_moteurs.py. Un échec ici ne doit jamais empêcher la capture bet_agent."""
    try:
        from app.services.comparaison_moteurs import comparer_candidats

        return comparer_candidats(db, pool)
    except Exception:
        return []


def capturer_predictions(db, run, pool, comparaison=None):
    """pool : {nom_match: [candidat, ...]} (bet_agent.agent3_calcul_pool_candidats). Capture
    TOUS les candidats vus (pas seulement les sélections finales du coupon) — c'est la
    population dont on veut un jour mesurer le ROI réel, pas seulement les paris retenus.
    comparaison : résultat déjà calculé de comparaison_moteurs.comparer_candidats(db, pool),
    pour éviter de le recalculer quand l'appelant (runs.py) l'a déjà fait pour ses propres
    logs — recalculé ici si omis. Renvoie le nombre de lignes réellement insérées (les
    doublons de la journée ne comptent pas)."""
    if not pool:
        return 0
    if comparaison is None:
        comparaison = _comparaison_moteur(db, pool)
    comparaison_par_cle = {(c["match"], c["marche_bet_agent"], c["selection"]): c for c in comparaison}

    jour = (run.lance_le or datetime.now(timezone.utc)).date()
    lignes, deja_vus = [], set()
    for nom_match, candidats in pool.items():
        for c in candidats:
            pick = c.get("pick") or {}
            cote = pick.get("cote")
            if cote is None:
                continue  # jamais une cote fabriquée — seulement ce qu'OddsPapi a réellement renvoyé
            marche = pick.get("marche_affichage") or pick.get("marche")
            ligne = pick.get("handicap")
            selection = pick.get("selection")
            fixture_id_oddspapi = c.get("fixture_id_oddspapi")
            cle = (fixture_id_oddspapi, marche, ligne, selection)
            if cle in deja_vus:
                continue
            deja_vus.add(cle)

            comp = comparaison_par_cle.get((nom_match, marche, selection))
            lignes.append({
                "run_id": run.id, "jour": jour,
                "fixture_id_oddspapi": fixture_id_oddspapi,
                "fixture_id_api_football": c.get("fixture_id_api_football"),
                "competition_id": c.get("competition_id"), "competition": c.get("competition"),
                "domicile": c.get("home_nom"), "exterieur": c.get("away_nom"),
                "coup_envoi": _coup_envoi(c.get("date_iso")),
                "marche": marche, "categorie": pick.get("categorie"), "ligne": ligne,
                "selection": selection, "cote": cote,
                "proba_bet_agent_pct": pick.get("proba_modele_pct"), "edge_bet_agent_pct": pick.get("edge_pct"),
                "proba_moteur_pct": comp.get("proba_moteur_pct") if comp else None,
                "edge_moteur_pct": comp.get("edge_moteur_pct") if comp else None,
                "modele_moteur": comp.get("modele_moteur") if comp else None,
            })
    if not lignes:
        return 0

    # Un run réel peut évaluer plusieurs milliers de candidats (centaines de marchés x dizaines
    # de matchs) : un seul INSERT multi-lignes dépasserait la limite Postgres de 65535
    # paramètres par requête (constaté en production le 10/10/2026, run 124 : échec silencieux,
    # capture entièrement perdue). Chaque ligne a 19 colonnes -> au plus ~3449 lignes/requête ;
    # TAILLE_LOT=1000 laisse une marge confortable.
    TAILLE_LOT = 1000
    moteur_insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    inserees = 0
    for debut in range(0, len(lignes), TAILLE_LOT):
        lot = lignes[debut:debut + TAILLE_LOT]
        stmt = moteur_insert(HistCote).values(lot)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["jour", "fixture_id_oddspapi", "marche", "ligne", "selection"])
        resultat = db.execute(stmt)
        inserees += resultat.rowcount or 0
    db.commit()
    return inserees


def juger_cotes_en_attente(db):
    """Associe le résultat réel (gagne/perdu/push/non_verifiable) à chaque hist_cotes non
    encore jugée dont le match est terminé — même règles que verification.py::verifier_jambes
    (API-Football d'abord, repli OddsPapi), réutilisées telles quelles, jamais redupliquées."""
    from app.services import pipeline

    cd, _, vr = pipeline.modules()
    a_juger = list(db.scalars(select(HistCote).where(HistCote.resultat.is_(None))))
    if not a_juger:
        return {"jugees": 0, "pas_termine": 0}

    fixtures_af = vr.recuperer_fixtures_api_football_du_jour()
    fixtures_op = None
    scores = {}
    compte = {"jugees": 0, "pas_termine": 0}
    for row in a_juger:
        domicile, exterieur = row.domicile, row.exterieur
        but_dom = but_ext = None
        if vr.trouver_fixture_api_football(domicile, exterieur, fixtures_af, cd):
            resultat_af = vr.trouver_score_api_football(domicile, exterieur, fixtures_af, cd)
            if resultat_af is None:
                compte["pas_termine"] += 1
                continue
            but_dom, but_ext = resultat_af
        elif row.fixture_id_oddspapi:
            if fixtures_op is None:
                fixtures_op = vr.recuperer_fixtures_du_jour()
            fx = fixtures_op.get(row.fixture_id_oddspapi)
            if not fx or fx.get("statusName") != "Finished":
                compte["pas_termine"] += 1
                continue
            if row.fixture_id_oddspapi not in scores:
                scores[row.fixture_id_oddspapi] = vr.recuperer_score(row.fixture_id_oddspapi)
            score = scores[row.fixture_id_oddspapi]
            if score is None:
                row.resultat, row.juge_le = "non_verifiable", datetime.now(timezone.utc)
                compte["jugees"] += 1
                continue
            p1, p2 = score
            if vr.home_est_participant1(domicile, fx.get("participant1Name"), fx.get("participant2Name")):
                but_dom, but_ext = p1, p2
            else:
                but_dom, but_ext = p2, p1
        else:
            compte["pas_termine"] += 1
            continue

        type_stat = vr.STAT_API_FOOTBALL_PAR_CATEGORIE.get(row.categorie)
        if type_stat:
            stats = (vr.recuperer_statistiques_finales_api_football(row.fixture_id_api_football, domicile)
                     if row.fixture_id_api_football else None)
            if stats is None:
                verdict = None
            else:
                bloc_dom, bloc_ext = stats
                val_dom, val_ext = cd._valeur_stat(bloc_dom, type_stat), cd._valeur_stat(bloc_ext, type_stat)
                verdict = vr.grader_pick_stat(row.categorie, row.ligne, row.selection, val_dom, val_ext)
        else:
            pick = {"categorie": row.categorie, "selection": row.selection, "handicap": row.ligne}
            verdict = vr.grader_pick(pick, but_dom, but_ext)
        row.resultat = VERDICT_VERS_RESULTAT.get(verdict, "non_verifiable")
        row.juge_le = datetime.now(timezone.utc)
        compte["jugees"] += 1

    db.commit()
    return compte
