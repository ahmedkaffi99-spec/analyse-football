from app import taches
from app.database import SessionLocal
from app.models import Run
from app.services import pipeline
from app.services.bilan import envoyer_bilans
from app.services.persistance import importer_fichiers
from tests.conftest import collecte_exemple, profils_exemple, ticket_exemple
from tests.test_api import _faux_pipeline


def test_tache_run_enregistre_et_relance_evitee(monkeypatch):
    envois = _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    assert taches.main(["run", "--telegram"]) == 0
    assert len(envois) == 1
    # Passage de secours : un ticket existe déjà aujourd'hui → rien n'est relancé
    assert taches.main(["run", "--si-aucun-ticket-aujourdhui"]) == 0
    with SessionLocal() as db:
        assert db.query(Run).count() == 1


def test_tache_run_en_erreur_code_retour_1(monkeypatch):
    _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple(), erreur=RuntimeError("panne"))
    assert taches.main(["run"]) == 1
    # Après une erreur, le passage de secours relance bien
    _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    assert taches.main(["run", "--si-aucun-ticket-aujourdhui"]) == 0
    with SessionLocal() as db:
        assert [r.statut for r in db.query(Run).order_by(Run.id)] == ["erreur", "termine"]


def _importer_et_juger(monkeypatch, score):
    with SessionLocal() as db:
        importer_fichiers(db, collecte_exemple(), ticket_exemple())
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
    assert taches.main(["run"]) == 0  # essai sans Telegram
    assert envois == []
    assert taches.main(["envoyer"]) == 0  # envoi des coupons déjà rédigés, sans nouvelle collecte
    assert envois == [["ticket profil1", "ticket profil2", "ticket profil3"]]
    assert taches.main(["envoyer"]) == 0  # déjà envoyé : pas de doublon
    assert len(envois) == 1
    assert taches.main(["envoyer", "--forcer"]) == 0
    assert len(envois) == 2


def test_envoyer_sans_run_termine():
    assert taches.main(["envoyer"]) == 1
