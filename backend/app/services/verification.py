"""Jugement des jambes à partir des scores réels (OddsPapi), en réutilisant les fonctions de
verifier_resultats.py (grader_pick & co) — même règles que le bilan Telegram du soir."""

from collections import Counter

from sqlalchemy import select

from app.models import Coupon, Jambe
from app.services import pipeline

VERDICT_VERS_RESULTAT = {"gagne": "gagne", "perdu": "perdu", "push": "push", None: "non_verifiable"}


def statut_coupon(resultats):
    """Un combiné est perdu dès qu'une jambe est perdue ; gagné seulement si toutes les
    jambes sont gagnées ou remboursées ; incertain si une jambe n'a pas pu être vérifiée."""
    if not resultats:
        return "vide"
    if "perdu" in resultats:
        return "perdu"
    if "en_attente" in resultats:
        return "en_attente"
    if "non_verifiable" in resultats:
        return "incertain"
    return "gagne"


def verifier_jambes(db, jambes):
    _, _, vr = pipeline.modules()
    a_juger = [j for j in jambes if j.resultat == "en_attente" and j.fixture_id_oddspapi]
    compte = Counter()
    if not a_juger:
        return compte

    fixtures = vr.recuperer_fixtures_du_jour()
    scores = {}
    for jambe in a_juger:
        fx = fixtures.get(jambe.fixture_id_oddspapi)
        if not fx or fx.get("statusName") != "Finished":
            compte["pas_termine"] += 1
            continue
        if jambe.fixture_id_oddspapi not in scores:
            scores[jambe.fixture_id_oddspapi] = vr.recuperer_score(jambe.fixture_id_oddspapi)
        score = scores[jambe.fixture_id_oddspapi]
        if score is None:
            jambe.resultat = "non_verifiable"
            compte["non_verifiable"] += 1
            continue
        p1, p2 = score
        domicile = jambe.domicile or jambe.libelle_match.split(" vs ")[0]
        if vr.home_est_participant1(domicile, fx.get("participant1Name"), fx.get("participant2Name")):
            but_dom, but_ext = p1, p2
        else:
            but_dom, but_ext = p2, p1
        pick = {"categorie": jambe.categorie, "selection": jambe.selection, "handicap": jambe.handicap}
        jambe.resultat = VERDICT_VERS_RESULTAT.get(vr.grader_pick(pick, but_dom, but_ext), "non_verifiable")
        compte[jambe.resultat] += 1
        if jambe.match:
            jambe.match.score_domicile, jambe.match.score_exterieur = but_dom, but_ext

    for coupon in {j.coupon for j in a_juger}:
        coupon.statut = statut_coupon([j.resultat for j in coupon.jambes])
    db.commit()
    return compte


def verifier_coupons_en_attente(db, run_id=None):
    requete = select(Jambe).join(Coupon).where(Jambe.resultat == "en_attente")
    if run_id is not None:
        requete = requete.where(Coupon.run_id == run_id)
    return verifier_jambes(db, list(db.scalars(requete)))
