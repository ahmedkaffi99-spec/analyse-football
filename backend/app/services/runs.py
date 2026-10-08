"""Exécution du pipeline depuis l'API. Même enchaînement que orchestrateur.py (collecte →
coupon(s) → rédaction IA → Telegram), mais déterministe (pas de LLM pilote) et avec chaque
étape enregistrée en base. L'envoi Telegram est optionnel et désactivé par défaut."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import config
from app.config import DOSSIER_DONNEES
from app.database import SessionLocal
from app.models import Run
from app.services import pipeline
from app.services.archives import archiver_run, telecharger_collecte
from app.services.persistance import enregistrer_collecte, enregistrer_coupons
from app.services.qualite_marches import qualite_marches
from app.services.statistiques import resume_pour_ia


def cloturer_runs_interrompus(db, maintenant=None):
    """Un run resté "en_cours" plus de HEURES_MAX_RUN heures a été tué (délai du job GitHub,
    coupure réseau...) : il est clôturé en erreur, sinon il bloquerait pour toujours les
    nouveaux runs (409) et le passage de secours ("ticket déjà en cours")."""
    maintenant = maintenant or datetime.now(timezone.utc)
    limite = maintenant - timedelta(hours=config.HEURES_MAX_RUN)
    clotures = 0
    for run in db.scalars(select(Run).where(Run.statut == "en_cours")):
        lance_le = run.lance_le if run.lance_le.tzinfo else run.lance_le.replace(tzinfo=timezone.utc)
        if lance_le < limite:
            run.statut = "erreur"
            run.detail = f"Interrompu : toujours en cours après {config.HEURES_MAX_RUN:g} h (job arrêté ou coupure)."
            run.termine_le = maintenant
            clotures += 1
    if clotures:
        db.commit()
        print(f"🧹 {clotures} run(s) interrompu(s) clôturé(s) en erreur.")
    return clotures


def charger_collecte_du_jour(db, run_source_id, telecharger=telecharger_collecte):
    """Collecte d'un run précédent du JOUR (les cotes d'un autre jour sont périmées)."""
    source = db.get(Run, run_source_id)
    if source is None:
        raise ValueError(f"Run {run_source_id} introuvable")
    if source.lance_le.date() != datetime.now(timezone.utc).date():
        raise ValueError(f"Run {run_source_id} du {source.lance_le.date()} : cotes périmées, reprise refusée")
    print(f"♻️ Reprise de la collecte du run {run_source_id} (aucun appel aux API sportives)")
    return telecharger(db, source)


def executer_run(run_id, envoyer_telegram=False, rediger=True, depuis_run=None, moteur="deterministe",
                 profils_personnalises=None, ignorer_diversite_croisee=False):
    """moteur="deterministe" (officiel depuis le 03/10/2026, demande explicite : "diminue le
    travail de l'IA, seulement en rédaction") : collecte -> calcul Python -> composition
    automatique Monte Carlo (Python choisit SEUL les paris, voir ae.UTILISER_STRATEGE_IA=false
    par défaut) -> rédaction LLM du texte final uniquement. Seul moteur supportant
    --depuis-run (reprise d'une collecte archivée).
    moteur="agent" : agent pilote DeepSeek autonome, décide lui-même quand collecter, chercher
    du web, proposer/rédiger/envoyer (bet_agent/agent_pilote.py) — choisit aussi les paris
    lui-même, pas seulement la rédaction. Officiel du 30/09 au 03/10/2026, reste disponible.

    profils_personnalises/ignorer_diversite_croisee (01/10/2026, run PONCTUEL demandé
    explicitement — n'affecte jamais le pipeline quotidien par défaut, qui garde ae.
    PROFILS_COUPON et la diversité croisée) : voir bet_agent.agent_pilote.executer."""
    db = SessionLocal()
    run = db.get(Run, run_id)
    donnees = None
    try:
        cd, ae, _ = pipeline.modules()
        pipeline.reinitialiser_caches(cd, ae)

        if moteur == "agent":
            if depuis_run:
                raise ValueError("--depuis-run n'est pas supporté avec le moteur agent (il pilote "
                                 "sa propre collecte, il n'y a pas de fichier à reprendre)")
            agent_pilote = pipeline.charger_agent_pilote()
            DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)
            cd.SORTIE_JSON = str(DOSSIER_DONNEES / f"collecte_run_{run_id}.json")
            # Bilan réel des coupons/catégories déjà jugés (demande explicite du 01/10/2026 :
            # "l'IA doit se souvenir du contexte") — prépendu à la mission par défaut de l'agent
            # pilote pour qu'il pèse ses choix du jour à la lumière des résultats réels passés,
            # pas seulement du catalogue du jour. None tant qu'aucun coupon n'est encore clos.
            bilan = resume_pour_ia(db)
            resultat_agent = agent_pilote.executer(telegram=envoyer_telegram, profils=profils_personnalises,
                                                   ignorer_diversite_croisee=ignorer_diversite_croisee,
                                                   contexte_supplementaire=bilan)
            donnees = resultat_agent.get("donnees")
            index = enregistrer_collecte(db, run, donnees) if donnees is not None else {}
            if donnees is not None:
                db.commit()
            resultats = resultat_agent.get("resultats_profils") or []
            if any(item["selections"] for item in resultats):
                enregistrer_coupons(db, run, resultats, index, textes=resultat_agent.get("textes"))
                run.envoye_telegram = bool(resultat_agent.get("envoye"))
                run.statut = "termine"
            else:
                run.statut = "abandonne"
                run.detail = (resultat_agent.get("raison_abandon") or resultat_agent.get("arret")
                              or "Agent pilote : aucune sélection retenue.")
            return

        if depuis_run:
            donnees = charger_collecte_du_jour(db, depuis_run)
        else:
            DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)
            sortie = DOSSIER_DONNEES / f"collecte_run_{run_id}.json"
            cd.SORTIE_JSON = str(sortie)
            cd.collecter_donnees()
            with open(sortie, encoding="utf-8") as f:
                donnees = json.load(f)
        index = enregistrer_collecte(db, run, donnees)
        db.commit()

        if not donnees.get("nb_matchs_avec_marches"):
            run.statut, run.detail = "abandonne", "Aucun match avec marchés 1xBet exploitables."
            return

        # Agent 3.5 (raisonnement IA, pas un calcul de plus) : vrais taux de réussite mesurés
        # par marché sur les paris déjà jugés — voir ae.agent35_validation_ia.
        resultats = ae.generer_coupons(donnees, qualite_marches=qualite_marches(db))
        if not any(item["selections"] for item in resultats):
            run.statut, run.detail = "abandonne", "Aucun profil n'a trouvé de sélection valable."
            return

        textes = ae.agent4_rediger_coupons(resultats) if rediger else None
        enregistrer_coupons(db, run, resultats, index, textes=textes)
        if envoyer_telegram and textes:
            run.envoye_telegram = bool(ae.agent5_envoyer_coupons(textes))
        run.statut = "termine"
    except Exception as e:
        db.rollback()
        run = db.get(Run, run_id)
        run.statut, run.detail = "erreur", pipeline.masquer_secrets(f"{type(e).__name__}: {e}")[:2000]
    finally:
        run.termine_le = datetime.now(timezone.utc)
        db.commit()
        if donnees is not None:
            try:
                archiver_run(db, run, donnees)
            except Exception as e:  # l'archivage ne doit jamais faire échouer un run
                print(f"   ⚠️ Archivage impossible : {pipeline.masquer_secrets(str(e))[:150]}")
        db.close()
