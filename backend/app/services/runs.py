"""Exécution du pipeline depuis l'API. Même enchaînement que orchestrateur.py (collecte →
coupon(s) → rédaction IA → Telegram), mais déterministe (pas de LLM pilote) et avec chaque
étape enregistrée en base. L'envoi Telegram est optionnel et désactivé par défaut."""

import json
import os
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
        # Incident réel du 10/10/2026 (run 129) : un coupon RÉELLEMENT envoyé sur Telegram a
        # disparu sans trace de la base parce qu'une erreur SQL dans un bloc purement
        # informatif plus bas (capture historique) a empoisonné la transaction encore ouverte,
        # faisant échouer le commit final qui aurait dû enregistrer ce coupon déjà envoyé. Le
        # coupon et le statut du run — déjà corrects et définitifs à ce point — sont donc
        # commités IMMÉDIATEMENT, avant tout bloc optionnel/informatif ci-dessous : leur échec
        # éventuel (et le rollback qu'il impose, voir plus bas) ne peut alors plus jamais
        # remonter jusqu'ici et effacer un coupon déjà envoyé.
        db.commit()

        # Comparaison PARALLÈLE bet_agent/moteur (10/10/2026, demande explicite : "faire
        # fonctionner le nouveau moteur en parallèle... sans modifier le coupon Telegram") —
        # désactivée par défaut (MOTEUR_COMPARAISON_ACTIVE), UNIQUEMENT journalisée, jamais
        # utilisée pour la sélection (déjà figée ci-dessus) ni pour envoyer_telegram (déjà
        # fait). Un recalcul séparé du pool (au lieu de réutiliser celui de generer_coupons)
        # pour ne RIEN changer au chemin existant — un échec ici ne doit jamais faire échouer
        # le run réel.
        pool_comparaison, comparaison = None, None
        if os.getenv("MOTEUR_COMPARAISON_ACTIVE", "").lower() in ("1", "true", "oui", "yes"):
            try:
                from app.services.comparaison_moteurs import comparer_candidats

                pool_comparaison = ae.agent3_calcul_pool_candidats(donnees)
                comparaison = comparer_candidats(db, pool_comparaison)
                disponibles = [c for c in comparaison if c["proba_moteur_pct"] is not None]
                print(f"\n   🔬 [Comparaison parallèle moteur] {len(comparaison)} candidat(s) comparé(s), "
                      f"{len(disponibles)} avec une prédiction moteur disponible.")
                for c in disponibles[:10]:
                    print(f"      {c['match']} — {c['marche_bet_agent']} {c['selection']} : "
                          f"bet_agent={c['proba_bet_agent_pct']}% vs moteur={c['proba_moteur_pct']}% "
                          f"({c['modele_moteur']}, {c['calibration']}) — {c['decision_moteur']}")
            except Exception as e:  # jamais faire échouer le vrai run pour une comparaison
                print(f"   ⚠️ Comparaison parallèle moteur indisponible ({pipeline.masquer_secrets(str(e))[:150]}).")
                # Incident réel du 10/10/2026 (run 129) : sans ce rollback, une erreur SQL ici
                # laisse la session dans l'état "transaction avortée" (Postgres l'exige après
                # toute erreur) — TOUT ce qui suit dans la même transaction échoue en cascade, y
                # compris le commit final qui enregistre le coupon déjà envoyé sur Telegram.
                # Un échec purement informatif ne doit jamais emporter la persistance réelle.
                db.rollback()

        # Capture PROSPECTIVE des cotes dans hist_cotes (10/10/2026, demande explicite :
        # "rendre possible une vraie mesure future du ROI... Implémente uniquement la capture
        # prospective des cotes") — à CHAQUE run réel, jamais derrière un indicateur (contrairement
        # à la comparaison ci-dessus, qui reste simplement journalisée) : ne modifie jamais la
        # sélection/les probabilités/la calibration déjà figées plus haut, écrit seulement des
        # lignes supplémentaires. Un échec ici ne doit jamais faire échouer le run réel.
        pool_central = pool_comparaison
        try:
            from app.services.capture_historique import capturer_predictions

            pool_central = pool_central if pool_central is not None else ae.agent3_calcul_pool_candidats(donnees)
            n_captures = capturer_predictions(db, run, pool_central, comparaison=comparaison)
            print(f"   📸 [Capture historique] {n_captures} cote(s) réelle(s) capturée(s) dans hist_cotes.")
        except Exception as e:  # jamais faire échouer le vrai run pour une capture
            print(f"   ⚠️ Capture historique indisponible ({pipeline.masquer_secrets(str(e))[:150]}).")
            # Même raison que ci-dessus (incident réel du 10/10/2026, run 129) : une erreur SQL
            # non suivie d'un rollback ici a fait échouer le commit final qui enregistre le
            # coupon déjà envoyé sur Telegram — aucune trace du coupon en base malgré l'envoi
            # réel. Ce rollback isole cet échec purement informatif de la persistance réelle.
            db.rollback()

        # Moteur CENTRAL, mode SHADOW (10/10/2026, demande explicite : "le moteur central
        # calcule ses décisions mais n'envoie rien et ne modifie pas le coupon Telegram") —
        # désactivé par défaut (MOTEUR_CENTRAL_SHADOW), uniquement journalisé dans
        # hist_decisions_centrales. MOTEUR_CENTRAL_ACTIVE (moteur_central/config.py) reste
        # false : aucun chemin de ce bloc ne peut encore piloter la sélection/Telegram
        # ci-dessus (déjà figées et envoyées avant ce point). Un échec ici ne doit jamais
        # faire échouer le run réel.
        if os.getenv("MOTEUR_CENTRAL_SHADOW", "").lower() in ("1", "true", "oui", "yes"):
            try:
                from app.services.comparaison_moteurs import comparer_candidats
                from app.services.decision_centrale import calculer_et_journaliser_shadow

                pool_central = pool_central if pool_central is not None else ae.agent3_calcul_pool_candidats(donnees)
                comparaison_central = comparaison if comparaison is not None else comparer_candidats(db, pool_central)
                ligne = calculer_et_journaliser_shadow(db, run, pool_central, comparaison_central)
                print(f"   🧭 [Moteur central — shadow] bet_agent={ligne.coupon_bet_agent['nb_jambes'] if ligne.coupon_bet_agent['genere'] else 'non généré'} "
                      f"jambe(s), moteur={ligne.coupon_moteur['nb_jambes'] if ligne.coupon_moteur['genere'] else 'non généré'} "
                      f"jambe(s), central={ligne.coupon_central['nb_jambes'] if ligne.coupon_central['genere'] else 'non généré'} "
                      f"jambe(s) (purement informatif, jamais envoyé).")
            except Exception as e:  # jamais faire échouer le vrai run pour le shadow
                print(f"   ⚠️ Moteur central (shadow) indisponible ({pipeline.masquer_secrets(str(e))[:150]}).")
                # Même raison que les deux blocs précédents (incident réel du 10/10/2026, run
                # 129) : isole cet échec purement informatif de la persistance réelle du coupon.
                db.rollback()
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
