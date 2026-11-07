from app import taches
from app.database import SessionLocal
from app.models import Coupon, Run
from app.services import pipeline
from app.services.bilan import envoyer_bilans
from app.services.persistance import importer_fichiers
from tests.conftest import collecte_exemple, profils_exemple, ticket_exemple
from tests.test_api import _faux_pipeline


def test_tache_run_enregistre_et_relance_evitee(monkeypatch):
    envois = _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    assert taches.main(["run", "--telegram", "--moteur", "deterministe"]) == 0
    assert len(envois) == 1
    # Passage de secours : un ticket existe déjà aujourd'hui → rien n'est relancé
    assert taches.main(["run", "--si-aucun-ticket-aujourdhui", "--moteur", "deterministe"]) == 0
    with SessionLocal() as db:
        assert db.query(Run).count() == 1


def test_run_manuel_sans_telegram_ne_bloque_pas_le_passage_planifie(monkeypatch):
    envois = _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    assert taches.main(["run", "--moteur", "deterministe"]) == 0  # essai manuel, rien envoyé
    assert taches.main(["run", "--telegram", "--si-aucun-ticket-aujourdhui", "--moteur", "deterministe"]) == 0
    assert len(envois) == 1
    assert taches.main(["run", "--telegram", "--si-aucun-ticket-aujourdhui", "--moteur", "deterministe"]) == 0  # déjà envoyé
    with SessionLocal() as db:
        assert db.query(Run).count() == 2


def test_tache_run_en_erreur_code_retour_1(monkeypatch):
    _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple(), erreur=RuntimeError("panne"))
    assert taches.main(["run", "--moteur", "deterministe"]) == 1
    # Après une erreur, le passage de secours relance bien
    _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    assert taches.main(["run", "--si-aucun-ticket-aujourdhui", "--moteur", "deterministe"]) == 0
    with SessionLocal() as db:
        assert [r.statut for r in db.query(Run).order_by(Run.id)] == ["erreur", "termine"]


def _importer_et_juger(monkeypatch, score, run_envoye=True):
    with SessionLocal() as db:
        importer_fichiers(db, collecte_exemple(), ticket_exemple())
        for run in db.query(Run):   # un bilan n'existe que pour un run réellement envoyé sur Telegram
            run.envoye_telegram = run_envoye
        db.commit()
    _, _, vr = pipeline.modules()
    monkeypatch.setattr(vr, "recuperer_fixtures_du_jour", lambda: {"idLENSAUX": {
        "statusName": "Finished", "participant1Name": "RC Lens", "participant2Name": "AJ Auxerre"}})
    monkeypatch.setattr(vr, "recuperer_score", lambda fid: score)


def test_bilan_envoye_une_seule_fois(monkeypatch):
    _importer_et_juger(monkeypatch, (2, 1))
    messages = []
    notifier = lambda m: messages.append(m) or True  # noqa: E731
    fausse_ae = type("AE", (), {"notifier_telegram": staticmethod(notifier)})
    monkeypatch.setattr(pipeline, "modules", lambda real=pipeline.modules: (None, fausse_ae, real()[2]))

    assert taches.main(["verifier", "--telegram"]) == 0
    assert len(messages) == 1
    assert "RÉSULTATS DU JOUR" in messages[0] and "✅ GAGNÉ" in messages[0] and "❌ PERDU" in messages[0]
    assert "(2-1)" in messages[0]
    assert taches.main(["verifier", "--telegram"]) == 0
    assert len(messages) == 1  # pas de doublon


def test_pas_de_bilan_tant_que_des_matchs_ne_sont_pas_finis():
    with SessionLocal() as db:
        importer_fichiers(db, collecte_exemple(), ticket_exemple())
        messages = []
        assert envoyer_bilans(db, lambda m: messages.append(m) or True) == 0
        assert messages == []


def test_configuration_de_la_base_sans_rien_editer():
    from app.config import construire_database_url

    # Mot de passe seul (secret SUPABASE_DB_PASSWORD) : adresse construite et encodée
    url = construire_database_url({"SUPABASE_DB_PASSWORD": " ab@c:d/e#1 "})
    assert url == ("postgresql+psycopg://postgres.fpwsitpdkruoknwmgjzr:ab%40c%3Ad%2Fe%231"
                   "@aws-0-eu-central-1.pooler.supabase.com:5432/postgres")
    # Chaîne copiée telle quelle depuis Supabase : le pilote est ajouté
    assert construire_database_url({"DATABASE_URL": "postgresql://u:p@h:5432/postgres"}) == \
        "postgresql+psycopg://u:p@h:5432/postgres"
    assert construire_database_url({"DATABASE_URL": "postgresql+psycopg://u:p@h/x"}) == "postgresql+psycopg://u:p@h/x"
    # Rien : SQLite local
    assert construire_database_url({}).startswith("sqlite:///")


def test_envoyer_les_coupons_d_un_run_deja_calcule(monkeypatch):
    envois = _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    assert taches.main(["run", "--moteur", "deterministe"]) == 0  # essai sans Telegram
    assert envois == []
    assert taches.main(["envoyer"]) == 0  # envoi des coupons déjà rédigés, sans nouvelle collecte
    assert envois == [["ticket profil1", "ticket profil2", "ticket profil3"]]
    assert taches.main(["envoyer"]) == 0  # déjà envoyé : pas de doublon
    assert len(envois) == 1
    assert taches.main(["envoyer", "--forcer"]) == 0
    assert len(envois) == 2


def test_envoyer_sans_run_termine():
    assert taches.main(["envoyer"]) == 1


def test_garde_ticket_du_jour_couvert_par_coupons_envoyes_la_veille():
    """Coupons préparés et envoyés la veille pour les matchs d'aujourd'hui : pas de second envoi ; sans eux, le passage a lieu."""
    from datetime import datetime, timedelta, timezone
    from app.database import SessionLocal
    from app.models import Match, Run
    from app.taches import ticket_deja_produit_aujourdhui

    maintenant = datetime.now(timezone.utc)
    hier = maintenant - timedelta(days=1)
    with SessionLocal() as db:
        assert ticket_deja_produit_aujourdhui(db) is False
        run = Run(source="api", statut="termine", envoye_telegram=True, lance_le=hier)
        db.add(run)
        db.flush()
        db.add(Match(run_id=run.id, domicile="A", exterieur="B", coup_envoi=maintenant))
        db.commit()
        assert ticket_deja_produit_aujourdhui(db) is True
    with SessionLocal() as db:
        db.query(Match).delete()
        db.add(Match(run_id=run.id, domicile="A", exterieur="B", coup_envoi=maintenant + timedelta(days=3)))
        db.commit()
        assert ticket_deja_produit_aujourdhui(db) is False


def test_aucun_bilan_pour_un_run_non_envoye_sur_telegram(monkeypatch):
    """06/11/2026 : les runs d'essai (jamais reçus) ne doivent jamais produire un « résultat du jour » sur Telegram."""
    _importer_et_juger(monkeypatch, (2, 1), run_envoye=False)
    messages = []
    fausse_ae = type("AE", (), {"notifier_telegram": staticmethod(lambda m: messages.append(m) or True)})
    monkeypatch.setattr(pipeline, "modules", lambda real=pipeline.modules: (None, fausse_ae, real()[2]))

    assert taches.main(["verifier", "--telegram"]) == 0
    assert messages == []
    with SessionLocal() as db:
        assert all(not c.bilan_envoye for c in db.query(Coupon))   # laissés tels quels, jamais marqués envoyés
        for run in db.query(Run):
            run.envoye_telegram = True                              # une fois le run réellement envoyé : bilan normal
        db.commit()
    assert taches.main(["verifier", "--telegram"]) == 0
    assert len(messages) == 1 and "RÉSULTATS DU JOUR" in messages[0]
