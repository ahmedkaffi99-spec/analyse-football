"""etat_live_jambes / `python -m app.taches live` : suivi en direct (API-Football) des jambes
encore en_attente — demande explicite de l'utilisateur (01/10/2026), en plein match réel suivi
manuellement : "on trouve pas un endpoint sur api football en match live". Purement
informatif : jamais persisté en base (jambe.resultat reste en_attente)."""
from app import taches
from app.database import SessionLocal
from app.services import pipeline
from app.services.verification import etat_live_jambes
from tests.conftest import collecte_exemple, ticket_exemple


def _fixture_af(home, away, statut_court, but_home, but_away, elapsed=None):
    return {"teams": {"home": {"name": home}, "away": {"name": away}},
            "fixture": {"status": {"short": statut_court, "elapsed": elapsed}},
            "goals": {"home": but_home, "away": but_away}}


def test_etat_live_pour_un_match_en_cours(client, monkeypatch):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    _, _, vr = pipeline.modules()
    monkeypatch.setattr(vr, "recuperer_fixtures_api_football_du_jour", lambda: [
        _fixture_af("RC Lens", "AJ Auxerre", "2H", 2, 0, 64)])

    with SessionLocal() as db:
        etats = etat_live_jambes(db)

    # profil1 : Total Over 2.5 -> perdant SI ça finissait maintenant (2 buts au total, il en
    # faudrait 3+). profil2 : BTTS No -> encore gagnant (Auxerre n'a toujours rien marqué).
    par_marche = {e["marche"]: e for e in etats}
    assert par_marche["Over Under Full Time (2.5)"]["score_actuel"] == "2-0"
    assert par_marche["Over Under Full Time (2.5)"]["minute"] == 64
    assert par_marche["Over Under Full Time (2.5)"]["verdict_si_ca_finissait_maintenant"] == "perdu"
    assert par_marche["Both Teams To Score (0.0)"]["verdict_si_ca_finissait_maintenant"] == "gagne"  # No, 0 but d'Auxerre

    # Rien n'est persisté : toujours en_attente en base.
    resultat = client.get("/api/coupons").json()
    assert all(j["resultat"] == "en_attente" for c in resultat for j in c["jambes"])


def test_etat_live_vide_si_aucun_match_en_cours(client, monkeypatch):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    _, _, vr = pipeline.modules()
    monkeypatch.setattr(vr, "recuperer_fixtures_api_football_du_jour", lambda: [
        _fixture_af("RC Lens", "AJ Auxerre", "NS", None, None)])

    with SessionLocal() as db:
        etats = etat_live_jambes(db)
    assert etats == []


def test_commande_cli_live_fonctionne_sans_telegram(client, monkeypatch, capsys):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    _, _, vr = pipeline.modules()
    monkeypatch.setattr(vr, "recuperer_fixtures_api_football_du_jour", lambda: [
        _fixture_af("RC Lens", "AJ Auxerre", "1H", 0, 0, 20)])

    assert taches.main(["live"]) == 0
    sortie = capsys.readouterr().out
    assert "Suivi en direct" in sortie
    assert "Lens" in sortie
