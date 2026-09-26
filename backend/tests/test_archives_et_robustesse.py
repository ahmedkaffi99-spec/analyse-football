from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from app import taches
from app.database import SessionLocal
from app.models import Run
from app.services.archives import archiver_run
from app.services.runs import cloturer_runs_interrompus


def _fausse_base(dialecte="postgresql", jeton="jeton-vault"):
    db = mock.Mock()
    db.get_bind.return_value.dialect.name = dialecte
    db.execute.return_value.scalar.return_value = jeton
    return db


def _faux_run():
    jambe = SimpleNamespace(libelle_match="A vs B", categorie="Total", marche="Total (2.5)", selection="Over",
                            cote=1.8, proba_modele_pct=60.0, edge_pct=5.0, resultat="en_attente")
    coupon = SimpleNamespace(profil="profil1", nom="🛡️ COUPON 1", jour=date(2026, 9, 26), statut="en_attente",
                             cote_totale=1.8, proba_combinee_pct=60.0, texte="⚽ A vs B", jambes=[jambe])
    return SimpleNamespace(id=7, lance_le=datetime(2026, 9, 26, 10, tzinfo=timezone.utc), coupons=[coupon])


def test_archivage_via_edge_function_avec_jeton_du_vault():
    appels = []

    def poster(url, headers, json, timeout):
        appels.append((url, headers, json))
        return SimpleNamespace(status_code=201, text="")

    chemins = archiver_run(_fausse_base(), _faux_run(), {"matchs": []}, poster=poster)
    assert chemins == ["2026-09-26/run_7_coupons.json", "2026-09-26/run_7_collecte.json"]
    url, headers, corps = appels[0]
    assert url == "https://fpwsitpdkruoknwmgjzr.supabase.co/functions/v1/api/archives"
    assert headers == {"X-API-Key": "jeton-vault"}
    assert corps["contenu"][0]["jambes"][0]["marche"] == "Total (2.5)"


def test_archivage_jamais_bloquant():
    def poster_en_panne(*a, **k):
        raise ConnectionError("réseau coupé ?apiKey=secret123")

    assert archiver_run(_fausse_base(), _faux_run(), {}, poster=poster_en_panne) == []
    assert archiver_run(_fausse_base(jeton=None), _faux_run(), {}, poster=poster_en_panne) == []
    assert archiver_run(_fausse_base("sqlite"), _faux_run(), {}, poster=poster_en_panne) == []


def test_runs_interrompus_clotures():
    maintenant = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add_all([Run(source="api", statut="en_cours", lance_le=maintenant - timedelta(hours=3)),
                    Run(source="api", statut="en_cours", lance_le=maintenant - timedelta(minutes=10))])
        db.commit()
        assert cloturer_runs_interrompus(db, maintenant) == 1
        statuts = [r.statut for r in db.query(Run).order_by(Run.id)]
    assert statuts == ["erreur", "en_cours"]


def test_run_bloque_ne_bloque_plus_le_suivant(monkeypatch):
    from tests.conftest import collecte_exemple, profils_exemple
    from tests.test_api import _faux_pipeline

    with SessionLocal() as db:
        db.add(Run(source="api", statut="en_cours", lance_le=datetime.now(timezone.utc) - timedelta(hours=5)))
        db.commit()
    _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    assert taches.main(["run", "--si-aucun-ticket-aujourdhui"]) == 0
    with SessionLocal() as db:
        assert [r.statut for r in db.query(Run).order_by(Run.id)] == ["erreur", "termine"]


def test_tester_api_signale_une_route_en_panne(monkeypatch):
    from app.taches import tache_tester_api

    class FausseSession:
        def __enter__(self):
            return _fausse_base(jeton="jeton-vault")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("app.taches.SessionLocal", FausseSession)

    def reponses(panne=None):
        def get(url, headers, timeout):
            route = url.split("/api", 1)[1]
            if headers.get("X-API-Key") != "jeton-vault":
                return SimpleNamespace(status_code=401, text="")
            if route == "/inconnue":
                return SimpleNamespace(status_code=404, text="")
            return SimpleNamespace(status_code=500 if route.startswith(panne or "@") else 200, text="panne")
        return SimpleNamespace(get=get)

    assert tache_tester_api(None, reponses()) == 0
    assert tache_tester_api(None, reponses(panne="/statistiques")) == 1


def test_liste_des_modeles_gratuits(capsys, monkeypatch):
    from app.taches import tache_modeles_gratuits

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    donnees = {"data": [
        {"id": "nvidia/grand:free", "name": "Grand", "context_length": 1000000,
         "supported_parameters": ["tools", "response_format"], "architecture": {"output_modalities": ["text"]}},
        {"id": "payant/modele", "name": "Payant", "context_length": 5, "pricing": {"prompt": "0.001", "completion": "0.002"}},
        {"id": "image/gen:free", "name": "Image", "architecture": {"output_modalities": ["image"]}},
    ]}
    reponse = SimpleNamespace(raise_for_status=lambda: None, json=lambda: donnees)
    assert tache_modeles_gratuits(None, SimpleNamespace(get=lambda url, timeout: reponse)) == 0
    sortie = capsys.readouterr().out
    assert "MODELE | nvidia/grand:free | Grand | contexte 1000000 | outils oui | json oui" in sortie
    assert "payant/modele" not in sortie and "image/gen" not in sortie


def test_verification_de_la_cle_openrouter(capsys, monkeypatch):
    from app.taches import verifier_cle_openrouter

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secrete")
    refus = SimpleNamespace(status_code=401, json=lambda: {"error": {"message": "User not found."}})
    assert verifier_cle_openrouter(SimpleNamespace(get=lambda url, headers, timeout: refus)) is False
    ok = SimpleNamespace(status_code=200, json=lambda: {"data": {"is_free_tier": True, "limit": None, "usage": 0}})
    assert verifier_cle_openrouter(SimpleNamespace(get=lambda url, headers, timeout: ok)) is True
    sortie = capsys.readouterr().out
    assert "CLE | REFUSÉE (HTTP 401 : User not found.)" in sortie
    assert "CLE | valide | offre gratuite : oui" in sortie
    assert "sk-or-secrete" not in sortie


def test_telechargement_d_une_collecte_archivee():
    from app.services.archives import telecharger_collecte

    appels = []

    def lire(url, timeout, params=None, headers=None):
        appels.append((url, params, headers))
        if url.endswith("/api/archives/lien"):
            return SimpleNamespace(status_code=200, json=lambda: {"url": "https://signe/fichier"})
        return SimpleNamespace(status_code=200, json=lambda: {"matchs": [{"id": 1}]})

    assert telecharger_collecte(_fausse_base(), _faux_run(), lire=lire) == {"matchs": [{"id": 1}]}
    assert appels[0][1] == {"chemin": "2026-09-26/run_7_collecte.json"}
    assert appels[0][2] == {"X-API-Key": "jeton-vault"}
    assert appels[1][0] == "https://signe/fichier"


def test_reprise_seulement_depuis_un_run_du_jour():
    import pytest

    from app.services.runs import charger_collecte_du_jour

    with SessionLocal() as db:
        ancien = Run(source="api", statut="termine", lance_le=datetime.now(timezone.utc) - timedelta(days=1))
        du_jour = Run(source="api", statut="termine", lance_le=datetime.now(timezone.utc))
        db.add_all([ancien, du_jour])
        db.commit()
        telecharger = mock.Mock(return_value={"matchs": []})
        assert charger_collecte_du_jour(db, du_jour.id, telecharger=telecharger) == {"matchs": []}
        with pytest.raises(ValueError, match="périmées"):
            charger_collecte_du_jour(db, ancien.id, telecharger=telecharger)
        with pytest.raises(ValueError, match="introuvable"):
            charger_collecte_du_jour(db, 999, telecharger=telecharger)
        assert telecharger.call_count == 1


def test_tester_les_ia_groq_et_gemini(capsys, monkeypatch):
    from app.taches import tache_tester_ia

    monkeypatch.setenv("GROQ_API_KEY", "gsk-secrete")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-secrete")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    appels = []

    def get(url, headers, timeout, params=None):
        appels.append(url)
        if "groq" in url:
            return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "openai/gpt-oss-120b"}]})
        return SimpleNamespace(status_code=200, json=lambda: {"models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]}]})

    def post(url, headers, timeout, json):
        appels.append(url)
        if "groq" in url:
            assert json["model"] == "openai/gpt-oss-120b"
            return SimpleNamespace(status_code=200, json=lambda: {"choices": [{"message": {"content": '{"ok": true}'}}]})
        assert url.endswith("/models/gemini-3.8-flash:generateContent")
        return SimpleNamespace(status_code=200, json=lambda: {
            "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]})

    assert tache_tester_ia(None, SimpleNamespace(get=get, post=post)) == 0
    sortie = capsys.readouterr().out
    assert "GROQ | test openai/gpt-oss-120b : OK" in sortie
    assert "GEMINI | test gemini-3.8-flash : OK" in sortie
    assert "BILAN | groq OK | gemini OK | openrouter KO" in sortie
    assert "secrete" not in sortie and all("secrete" not in u for u in appels)
