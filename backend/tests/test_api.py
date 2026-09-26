import json
from types import SimpleNamespace

from app.services import pipeline
from app.services.verification import statut_coupon
from tests.conftest import collecte_exemple, profils_exemple, ticket_exemple


def test_sante(client):
    assert client.get("/api/sante").json() == {"statut": "ok", "base": "sqlite"}


ROUTES_LECTURE = ["/api/sante", "/api/runs", "/api/runs/1", "/api/coupons", "/api/coupons/1",
                  "/api/matchs", "/api/matchs/1", "/api/statistiques"]
ROUTES_ECRITURE = ["/api/runs", "/api/runs/1/verification", "/api/coupons/verification", "/api/imports"]


def test_toute_l_api_est_privee(anonyme):
    for route in ROUTES_LECTURE:
        assert anonyme.get(route).status_code == 401, route
        assert anonyme.get(route, headers={"X-API-Key": "faux"}).status_code == 401, route
    for route in ROUTES_ECRITURE:
        assert anonyme.post(route, json={}).status_code == 401, route


def test_documentation_desactivee_par_defaut(anonyme):
    for route in ("/docs", "/redoc", "/openapi.json"):
        assert anonyme.get(route).status_code == 404, route


def test_api_fermee_sans_api_token_configure(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "API_TOKEN", None)
    assert client.get("/api/coupons").status_code == 503


def test_import_collecte_et_ticket(client):
    r = client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    assert r.status_code == 201
    run = client.get(f"/api/runs/{r.json()['id']}").json()
    assert run["source"] == "import" and run["nb_marches"] == 2
    coupons = {c["profil"]: c for c in run["coupons"]}
    assert coupons["profil1"]["cote_totale"] == round(1.8 * 1.7, 2)
    assert coupons["profil3"]["statut"] == "vide"
    # Les jambes sont rattachées au match importé
    match_id = coupons["profil1"]["jambes"][0]["match_id"]
    match = client.get(f"/api/matchs/{match_id}").json()
    assert (match["domicile"], match["exterieur"], match["ligue"]) == ("Lens", "Auxerre", "Ligue 1")
    assert len(match["cotes"]) == 4
    assert len(client.get("/api/coupons", params={"jour": "2026-09-25"}).json()) == 3
    assert len(client.get("/api/matchs", params={"jour": "2026-09-25"}).json()) == 1


def test_import_vide_refuse(client):
    assert client.post("/api/imports", json={}).status_code == 422


def _faux_pipeline(monkeypatch, collecte, profils, erreur=None):
    envois = []

    def collecter():
        if erreur:
            raise erreur
        with open(cd.SORTIE_JSON, "w", encoding="utf-8") as f:
            json.dump(collecte, f)

    cd = SimpleNamespace(SORTIE_JSON=None, collecter_donnees=collecter, _cache_clubelo=None,
                         _cache_understat_par_ligue={}, _cache_classement_football_data={},
                         _cache_stats_equipes={},
                         saison_en_cours=lambda: 2026, UNDERSTAT_SAISON=2025)
    ae = SimpleNamespace(
        generer_coupons=lambda donnees: profils,
        agent4_rediger_coupons=lambda res: [f"ticket {p['profil']['cle']}" for p in res],
        agent5_envoyer_coupons=lambda textes: envois.append(textes) or True,
    )
    monkeypatch.setattr(pipeline, "modules", lambda: (cd, ae, None))
    return envois


def test_run_complet_sans_telegram(client, monkeypatch):
    envois = _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    r = client.post("/api/runs", json={})
    assert r.status_code == 202
    run = client.get(f"/api/runs/{r.json()['id']}").json()  # la tâche de fond est terminée
    assert run["statut"] == "termine" and not run["envoye_telegram"]
    assert [c["texte"] for c in run["coupons"]] == ["ticket profil1", "ticket profil2", "ticket profil3"]
    assert envois == []


def test_run_avec_telegram(client, monkeypatch):
    envois = _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple())
    r = client.post("/api/runs", json={"envoyer_telegram": True})
    assert client.get(f"/api/runs/{r.json()['id']}").json()["envoye_telegram"] is True
    assert len(envois) == 1


def test_run_abandonne_sans_marche(client, monkeypatch):
    collecte = collecte_exemple()
    collecte["nb_matchs_avec_marches"] = 0
    _faux_pipeline(monkeypatch, collecte, profils_exemple())
    r = client.post("/api/runs", json={})
    assert client.get(f"/api/runs/{r.json()['id']}").json()["statut"] == "abandonne"


def test_run_en_erreur_masque_les_cles(client, monkeypatch):
    _faux_pipeline(monkeypatch, collecte_exemple(), profils_exemple(),
                   erreur=ConnectionError("Max retries /v4/fixtures?apiKey=c1ccd0b3-secret&sportId=10"))
    r = client.post("/api/runs", json={})
    run = client.get(f"/api/runs/{r.json()['id']}").json()
    assert run["statut"] == "erreur"
    assert "c1ccd0b3" not in run["detail"] and "apiKey=***" in run["detail"]


def test_un_seul_run_a_la_fois(client):
    from app.database import SessionLocal
    from app.models import Run

    with SessionLocal() as db:
        db.add(Run(source="api", statut="en_cours"))
        db.commit()
    assert client.post("/api/runs", json={}).status_code == 409


def test_verification_et_statistiques(client, monkeypatch):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    _, _, vr = pipeline.modules()  # vrai module : vraie logique de jugement (grader_pick)
    monkeypatch.setattr(vr, "recuperer_fixtures_du_jour", lambda: {"idLENSAUX": {
        "statusName": "Finished", "participant1Name": "RC Lens", "participant2Name": "AJ Auxerre"}})
    monkeypatch.setattr(vr, "recuperer_score", lambda fid: (2, 1))  # Lens 2-1 Auxerre

    resultat = client.post("/api/coupons/verification").json()
    assert resultat["gagne"] == 2 and resultat["perdu"] == 1  # Over 2.5 ✓, BTTS oui ✓, BTTS non ✗

    coupons = {c["profil"]: c for c in client.get("/api/coupons").json()}
    assert coupons["profil1"]["statut"] == "gagne"
    assert coupons["profil2"]["statut"] == "perdu"
    match = client.get(f"/api/matchs/{coupons['profil1']['jambes'][0]['match_id']}").json()
    assert (match["score_domicile"], match["score_exterieur"]) == (2, 1)

    stats = {p["profil"]: p for p in client.get("/api/statistiques").json()["profils"]}
    assert stats["profil1"]["gain_net_unites"] == round(1.8 * 1.7 - 1, 2)
    assert stats["profil2"]["gain_net_unites"] == -1.0


def test_statut_coupon():
    assert statut_coupon(["gagne", "push"]) == "gagne"
    assert statut_coupon(["gagne", "en_attente"]) == "en_attente"
    assert statut_coupon(["gagne", "non_verifiable"]) == "incertain"
    assert statut_coupon(["en_attente", "perdu"]) == "perdu"
    assert statut_coupon([]) == "vide"
