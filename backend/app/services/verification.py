"""Jugement des jambes à partir des scores réels (API-Football, repli OddsPapi), en réutilisant les fonctions de
verifier_resultats.py (grader_pick & co) — même règles que le bilan Telegram du soir."""

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Coupon, Jambe
from app.services import pipeline

VERDICT_VERS_RESULTAT = {"gagne": "gagne", "perdu": "perdu", "push": "push", None: "non_verifiable"}


def statut_coupon(resultats):
    """Un combiné est perdu dès qu'une jambe est perdue ; gagné seulement si toutes les jambes
    sont gagnées, remboursées (push) ou annulées (annule) ; incertain si une jambe n'a pas pu
    être vérifiée OU est périmée (délai de péremption dépassé sans verdict, voir
    verifier_resultats.jambe_perimee) — jamais compté comme gagné/perdu par défaut."""
    if not resultats:
        return "vide"
    if "perdu" in resultats:
        return "perdu"
    if "en_attente" in resultats:
        return "en_attente"
    if "non_verifiable" in resultats or "perime" in resultats:
        return "incertain"
    return "gagne"


def verifier_jambes(db, jambes):
    cd, _, vr = pipeline.modules()
    a_juger = [j for j in jambes if j.resultat == "en_attente" and j.fixture_id_oddspapi]
    compte = Counter()
    if not a_juger:
        return compte

    # API-Football d'abord (demande explicite du 03/10/2026 : "utilisation d'OddsPapi
    # diminuée") : quota de 7 500/jour contre 250 pour OddsPapi, et ce passage tourne chaque
    # heure de 15h à 23h. OddsPapi n'est appelé que pour un match introuvable côté
    # API-Football — jamais pour un match trouvé mais pas encore terminé.
    fixtures_af = vr.recuperer_fixtures_api_football_du_jour()
    fixtures = None  # OddsPapi, chargé à la demande (repli), une seule fois pour tout le passage
    scores = {}
    maintenant = datetime.now(timezone.utc)

    def _marquer_non_resolu(jambe):
        # Péremption (délai dépassé depuis le coup d'envoi, sans verdict) -> "perime", jamais
        # laissé en_attente pour toujours ; sinon, inchangé ("pas_termine", en_attente reste).
        coup_envoi = jambe.match.coup_envoi if jambe.match else None
        if vr.jambe_perimee(coup_envoi, maintenant):
            jambe.resultat = "perime"
            compte["perime"] += 1
        else:
            compte["pas_termine"] += 1

    for jambe in a_juger:
        domicile = jambe.domicile or jambe.libelle_match.split(" vs ")[0]
        exterieur = jambe.libelle_match.split(" vs ")[-1]
        but_dom = but_ext = None
        if vr.trouver_fixture_api_football(domicile, exterieur, fixtures_af, cd):
            etat, score = vr.trouver_score_api_football(domicile, exterieur, fixtures_af, cd)
            if etat == "annule":
                # Match reporté/annulé/abandonné (PST/CANC/ABD) : jamais un score deviné,
                # remboursement direct — convention standard, pas un gagné/perdu/push normal.
                jambe.resultat = "annule"
                compte["annule"] += 1
                continue
            if etat != "termine":
                # "indetermine" (suspendu/interrompu, peut reprendre) ou "pas_termine".
                _marquer_non_resolu(jambe)
                continue
            but_dom, but_ext = score
        else:
            if fixtures is None:
                fixtures = vr.recuperer_fixtures_du_jour()
            fx = fixtures.get(jambe.fixture_id_oddspapi)
            if not fx or fx.get("statusName") != "Finished":
                _marquer_non_resolu(jambe)
                continue
            if jambe.fixture_id_oddspapi not in scores:
                scores[jambe.fixture_id_oddspapi] = vr.recuperer_score(jambe.fixture_id_oddspapi)
            score = scores[jambe.fixture_id_oddspapi]
            if score is None:
                jambe.resultat = "non_verifiable"
                compte["non_verifiable"] += 1
                continue
            p1, p2 = score
            if vr.home_est_participant1(domicile, fx.get("participant1Name"), fx.get("participant2Name")):
                but_dom, but_ext = p1, p2
            else:
                but_dom, but_ext = p2, p1

        type_stat = vr.STAT_API_FOOTBALL_PAR_CATEGORIE.get(jambe.categorie)
        if type_stat:
            # Corners/cartons/fautes/tirs/hors-jeux : OddsPapi /v4/scores ne renvoie que les
            # buts (but_dom/but_ext ci-dessus, inutilisables ici) — statistiques finales
            # cherchées séparément via API-Football (03/10/2026, 55% des jambes étaient
            # "non_verifiable" pour cette seule raison avant ce correctif).
            fixture_af = jambe.match.fixture_id_api_football if jambe.match else None
            stats = vr.recuperer_statistiques_finales_api_football(fixture_af, domicile) if fixture_af else None
            if stats is None:
                jambe.resultat = "non_verifiable"
            else:
                bloc_dom, bloc_ext = stats
                val_dom = cd._valeur_stat(bloc_dom, type_stat)
                val_ext = cd._valeur_stat(bloc_ext, type_stat)
                verdict = vr.grader_pick_stat(jambe.categorie, jambe.handicap, jambe.selection, val_dom, val_ext)
                jambe.resultat = VERDICT_VERS_RESULTAT.get(verdict, "non_verifiable")
        else:
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


def etat_live_jambes(db, run_id=None):
    """Pour chaque jambe encore en_attente dont le match est EN COURS côté API-Football
    (STATUTS_EN_DIRECT), calcule ce que serait son verdict SI le match se terminait sur le
    score actuel — PUREMENT INFORMATIF, jamais écrit en base (jambe.resultat reste en_attente
    tant que le match n'est pas réellement terminé, jugé comme d'habitude par
    verifier_coupons_en_attente). Demande explicite de l'utilisateur (01/10/2026), suivant un
    pari en direct manuellement match par match : "on trouve pas un endpoint sur api football
    en match live" — un seul appel API-Football (quota séparé d'OddsPapi) pour TOUTES les
    jambes en attente d'un coup, pas un par match suivi manuellement."""
    cd, _, vr = pipeline.modules()
    requete = select(Jambe).join(Coupon).where(Jambe.resultat == "en_attente")
    if run_id is not None:
        requete = requete.where(Coupon.run_id == run_id)
    jambes = list(db.scalars(requete))
    if not jambes:
        return []

    fixtures_af = vr.recuperer_fixtures_api_football_du_jour()
    etats_par_match = {}
    resultats = []
    for jambe in jambes:
        domicile = jambe.domicile or jambe.libelle_match.split(" vs ")[0]
        exterieur = jambe.libelle_match.split(" vs ")[-1]
        cle = (domicile, exterieur)
        if cle not in etats_par_match:
            etats_par_match[cle] = vr.trouver_etat_live_api_football(domicile, exterieur, fixtures_af, cd)
        etat = etats_par_match[cle]
        if etat is None:
            continue
        but_dom, but_ext, minute, statut = etat
        pick = {"categorie": jambe.categorie, "selection": jambe.selection, "handicap": jambe.handicap}
        resultats.append({
            "coupon": jambe.coupon.nom, "match": jambe.libelle_match, "marche": jambe.marche,
            "selection": jambe.selection, "cote": jambe.cote, "score_actuel": f"{but_dom}-{but_ext}",
            "minute": minute, "statut": statut,
            "verdict_si_ca_finissait_maintenant": vr.grader_pick(pick, but_dom, but_ext) or "non_verifiable",
        })
    return resultats
