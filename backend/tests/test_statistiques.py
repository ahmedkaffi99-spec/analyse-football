"""resume_pour_ia : bilan réel (coupons + catégories) injecté dans la mission de l'agent
pilote (bet_agent/agent_pilote.py) — demande explicite du 01/10/2026 ("l'IA doit se souvenir
du contexte") pour que l'IA pèse ses choix du jour à la lumière des résultats réels passés."""
from app.database import SessionLocal
from app.services import pipeline
from app.services.statistiques import resume_pour_ia
from tests.conftest import collecte_exemple, ticket_exemple


def test_aucun_coupon_clos_renvoie_none(client):
    with SessionLocal() as db:
        assert resume_pour_ia(db) is None


def test_bilan_global_apres_verification(client, monkeypatch):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    _, _, vr = pipeline.modules()
    monkeypatch.setattr(vr, "recuperer_fixtures_du_jour", lambda: {"idLENSAUX": {
        "statusName": "Finished", "participant1Name": "RC Lens", "participant2Name": "AJ Auxerre"}})
    monkeypatch.setattr(vr, "recuperer_score", lambda fid: (2, 1))  # Lens 2-1 Auxerre
    client.post("/api/coupons/verification")

    with SessionLocal() as db:
        texte = resume_pour_ia(db)
    assert texte is not None
    assert "1/2 coupon(s)" in texte  # profil1 gagné, profil2 perdu — profil3 (vide) jamais clos


def test_categories_faibles_et_solides_avec_assez_d_echantillon(client, monkeypatch):
    client.post("/api/imports", json={"collecte": collecte_exemple(), "ticket": ticket_exemple()})
    _, _, vr = pipeline.modules()
    monkeypatch.setattr(vr, "recuperer_fixtures_du_jour", lambda: {"idLENSAUX": {
        "statusName": "Finished", "participant1Name": "RC Lens", "participant2Name": "AJ Auxerre"}})
    monkeypatch.setattr(vr, "recuperer_score", lambda fid: (2, 1))
    client.post("/api/coupons/verification")

    with SessionLocal() as db:
        # min_jugees=1 : l'échantillon du fixture est minuscule (BTTS jugée 2 fois, Total 1
        # fois) — on abaisse le seuil juste pour ce test, le défaut (3) reste la valeur réelle
        # utilisée en production (voir test_bilan_global_apres_verification, aucune catégorie
        # listée avec le défaut sur ce même fixture).
        texte = resume_pour_ia(db, min_jugees=1)
    assert "BTTS" not in texte  # 1 gagné / 2 jugées = 50% : ni faible (<50) ni solide (>=70)
    assert "Total (1/1)" in texte  # 1 gagné / 1 jugée = 100% : solide
    assert "SOLIDE" in texte
