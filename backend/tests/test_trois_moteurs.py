"""Intégration des TROIS moteurs (agent, central, déterministe) sur le MÊME catalogue (07/11/2026) : mêmes données, trois profils (prudent, équilibré, risque), aucune cote
cible, mêmes règles de cohérence. Aucun réseau, aucun Telegram réel, aucun appel IA. Ces tests vérifient la STRUCTURE et la cohérence, pas la performance prédictive."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Coupon, Run
from app.services import pipeline
from app.services.runs import executer_run
from tests.test_runs_moteur_central import _faux_modules, _run, _FauxCollecteDonnees  # noqa: F401  (aides communes des tests du moteur central)

RACINE = Path(__file__).resolve().parents[2]
for chemin in (RACINE, RACINE / "bet_agent"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

import agent_strategie as st  # noqa: E402
import profils_smart  # noqa: E402
from moteur import profils_risque as pr  # noqa: E402

LIGUES = ("Premier League", "Liga", "Serie A", "Bundesliga")
MODELES_JAMBES = (("Total", "Over", 1.8, 56.0), ("Double Chance", "1X", 1.3, 74.0), ("BTTS", "Yes", 2.1, 48.0), ("Total Corners", "Under", 1.9, 52.0))


def _candidat(match, i, categorie, selection, cote, proba):
    home, away = match.split(" vs ")
    return {"match": match, "home_nom": home, "away_nom": away, "fixture_id_oddspapi": match, "competition": LIGUES[i % len(LIGUES)],
            "pick": {"categorie": categorie, "marche": f"{categorie} (2.5)", "marche_affichage": f"{categorie} (2.5)", "handicap": 2.5, "selection": selection,
                     "cote": cote, "proba_modele_pct": proba + (i % 4), "edge_pct": 2.0, "guide": "g", "onglet": "o"}}


def pool_commun(n=12):
    """Le MÊME catalogue pour les trois moteurs."""
    return {f"M{i} vs A{i}": [_candidat(f"M{i} vs A{i}", i, *m) for m in MODELES_JAMBES] for i in range(n)}


def _jambes(item):
    return item["selections"]


def _verifier_resultats(resultats, pool):
    """Contrôles communs : 3 profils dans l'ordre, rien d'inventé, un match dans un seul coupon, deux jambes minimum, aucune cote imposée."""
    assert [r["profil"]["niveau_risque"] for r in resultats] == ["prudent", "equilibre", "risque"]
    catalogue = {(m, c["pick"]["categorie"], c["pick"]["selection"]): c["pick"]["cote"] for m, cs in pool.items() for c in cs}
    vus = {}
    for r in resultats:
        for s in r["selections"]:
            cle = (s["match"], s["pick"]["categorie"], s["pick"]["selection"])
            assert cle in catalogue and catalogue[cle] == s["pick"]["cote"]            # aucune jambe ni cote inventée
            assert s["match"] not in vus or vus[s["match"]] == r["profil"]["cle"]       # un match dans un seul coupon
            vus[s["match"]] = r["profil"]["cle"]
        if r["selections"]:
            assert len(r["selections"]) >= 2
            assert len({s["match"] for s in r["selections"]}) == len(r["selections"])  # un pari par match
        else:
            assert r.get("abstention")                                                  # une abstention est toujours expliquée
    assert any(r["selections"] for r in resultats)
    for r in resultats:
        assert "cote_totale_min" not in r["profil"] and "cote_totale_max" not in r["profil"]


def test_les_profils_sont_identiques_pour_les_trois_moteurs():
    from app import preparer_formulaire as pf
    sorties = {m: json.loads(pf.construire({"EVENEMENT": "workflow_dispatch", "MOTEUR": m})["profils"]) for m in ("agent", "central", "deterministe")}
    assert sorties["agent"] == sorties["central"] == sorties["deterministe"] == profils_smart.profils()


# ---------- moteur déterministe ----------
def test_moteur_deterministe_via_generer_coupons_donne_trois_profils():
    import analyser_et_envoyer as ae
    pool = pool_commun()
    with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool):
        resultats = ae.generer_coupons({"matchs": []}, profils=profils_smart.profils(contraintes=False))
    _verifier_resultats(resultats, pool)
    assert all(r["selections"] for r in resultats)                                      # 12 matchs : les trois profils sont composés


def test_moteur_deterministe_sans_profils_garde_le_comportement_historique():
    import analyser_et_envoyer as ae
    pool = pool_commun(6)
    with mock.patch.object(ae, "agent3_calcul_pool_candidats", return_value=pool):
        resultats = ae.generer_coupons({"matchs": []})
    assert all(r["profil"].get("cote_min") is not None for r in resultats)              # profils dynamiques historiques (avec leurs bornes)


def test_deterministe_est_reproductible():
    import moteur_deterministe as md
    pool = pool_commun()
    a = md.composer(pool, profils_smart.profils(contraintes=False))
    b = md.composer(json.loads(json.dumps(pool)), profils_smart.profils(contraintes=False))
    cle = lambda res: [[(s["match"], s["pick"]["categorie"], s["pick"]["selection"]) for s in r["selections"]] for r in res]
    assert cle(a) == cle(b)                                                             # aucun hasard : mêmes entrées, mêmes coupons


# ---------- moteur central ----------
def test_moteur_central_via_executer_run_enregistre_trois_coupons():
    pool = pool_commun()
    with SessionLocal() as db:
        run = _run(db)
        run_id = run.id
        cd, ae = _faux_modules(pool)
        with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), mock.patch.object(pipeline, "reinitialiser_caches"), \
                mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
            executer_run(run_id, envoyer_telegram=False, moteur="central", profils_personnalises=profils_smart.profils(contraintes=False))
        ae.generer_coupons.assert_not_called()                                          # aucun autre moteur n'a tourné
    with SessionLocal() as db:
        assert db.get(Run, run_id).statut == "termine"
        coupons = list(db.scalars(select(Coupon).where(Coupon.run_id == run_id).order_by(Coupon.profil)))
        assert [c.profil for c in coupons] == ["coupon1", "coupon2", "coupon3"]
        assert all(len(c.jambes) >= 2 for c in coupons)
        matchs = [j.libelle_match for c in coupons for j in c.jambes]
        assert len(matchs) == len(set(matchs))                                          # un match dans un seul coupon


def test_moteur_central_sans_profils_garde_le_comportement_historique():
    pool = {f"M{i} vs A{i}": [_candidat(f"M{i} vs A{i}", i, "Total", "Over", 1.3, 70.0)] for i in range(6)}
    with SessionLocal() as db:
        run = _run(db)
        run_id = run.id
        cd, ae = _faux_modules(pool)
        with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), mock.patch.object(pipeline, "reinitialiser_caches"), \
                mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
            executer_run(run_id, envoyer_telegram=False, moteur="central")
    with SessionLocal() as db:
        assert [c.profil for c in db.scalars(select(Coupon).where(Coupon.run_id == run_id))] == ["central_1"]


def test_moteur_central_sans_aucun_coupon_leve_au_lieu_de_replier():
    pool = {"A vs B": [_candidat("A vs B", 0, "Total", "Over", 1.3, 70.0)]}               # un seul match : aucun coupon de 2 jambes possible
    with SessionLocal() as db:
        run = _run(db)
        run_id = run.id
        cd, ae = _faux_modules(pool)
        with mock.patch.object(pipeline, "modules", return_value=(cd, ae, None)), mock.patch.object(pipeline, "reinitialiser_caches"), \
                mock.patch("app.services.capture_historique.capturer_predictions", return_value=0):
            executer_run(run_id, envoyer_telegram=False, moteur="central", profils_personnalises=profils_smart.profils(contraintes=False))
        ae.generer_coupons.assert_not_called()                                          # jamais de repli vers un autre moteur
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run.statut == "erreur" and "aucun des trois profils" in run.detail


# ---------- même catalogue, mêmes règles, trois moteurs ----------
def _vers_ids(catalogue):
    return {(c["match"], c["pick"]["categorie"], c["pick"]["selection"]): cid for cid, c in catalogue.items()}


def test_les_sorties_des_trois_moteurs_passent_la_validation_python_de_l_agent():
    """Les coupons du déterministe et du central, proposés comme s'ils venaient de l'agent, sont acceptés par `agent_strategie.valider` : les trois moteurs obéissent aux mêmes règles."""
    import analyser_et_envoyer as ae
    import moteur_deterministe as md
    from moteur_central.profils import selectionner_profils
    from moteur_central.score_central import CandidatCentral
    pool = pool_commun()
    catalogue, _ = st.construire_catalogue(pool, seuil_proba=0)   # seuil 0 = configuration du workflow (SEUIL_PROBA_MIN=0)
    ids = _vers_ids(catalogue)
    profils = profils_smart.profils(contraintes=False)
    central_pool = [CandidatCentral(match=m, marche=c["pick"]["categorie"], selection=c["pick"]["selection"], cote=c["pick"]["cote"], moteur_responsable="bet_agent",
                                    proba_pct=c["pick"]["proba_modele_pct"], categorie=c["pick"]["categorie"], competition=c["competition"]) for m, cs in pool.items() for c in cs]
    sorties = {"deterministe": [(r["profil"], r["selections"]) for r in md.composer(pool, profils)],
               "central": [(r["profil"], [next(c for c in pool[j.match] if c["pick"]["categorie"] == j.categorie and c["pick"]["selection"] == j.selection) for j in r["jambes"]])
                           for r in selectionner_profils(central_pool, profils)]}
    for moteur, coupons in sorties.items():
        precedentes = []
        for profil, selections in coupons:
            proposition = {"coupons": [{"profil": profil["cle"], "strategie": "s", "jambes": [
                {"id": ids[(s["match"], s["pick"]["categorie"], s["pick"]["selection"])], "raison": "ok"} for s in selections]}]}
            acceptes, problemes, _ = st.valider(proposition, catalogue, [profil], selections_precedentes=precedentes)
            assert profil["cle"] in acceptes, (moteur, profil["cle"], problemes)
            precedentes += acceptes[profil["cle"]]["selections"]
    assert ae  # module chargé


def test_les_trois_moteurs_produisent_des_coupons_differencies_selon_le_risque():
    import moteur_deterministe as md
    from moteur_central.profils import selectionner_profils
    from moteur_central.score_central import CandidatCentral
    pool = pool_commun()
    profils = profils_smart.profils(contraintes=False)
    central_pool = [CandidatCentral(match=m, marche=c["pick"]["categorie"], selection=c["pick"]["selection"], cote=c["pick"]["cote"], moteur_responsable="bet_agent",
                                    proba_pct=c["pick"]["proba_modele_pct"], categorie=c["pick"]["categorie"], competition=c["competition"]) for m, cs in pool.items() for c in cs]
    det = md.composer(pool, profils)
    cen = selectionner_profils(central_pool, profils)
    det_p = [pr.proba_jointe([{"match": s["match"], "competition": s["competition"], "categorie": s["pick"]["categorie"], "selection": s["pick"]["selection"],
                               "p": s["pick"]["proba_modele_pct"] / 100, "cote": s["pick"]["cote"]} for s in r["selections"]]) for r in det]
    cen_p = [r["proba_jointe"] for r in cen]
    assert det_p[0] > det_p[2] and cen_p[0] > cen_p[2]                                  # le prudent est plus probable que le risque, pour les deux moteurs


def test_le_formulaire_permet_de_choisir_chacun_des_trois_moteurs():
    import yaml
    from app import taches
    wf = yaml.safe_load((RACINE / ".github" / "workflows" / "pipeline-quotidien.yml").read_text(encoding="utf-8"))
    champ = wf[True]["workflow_dispatch"]["inputs"]["moteur"]
    assert champ["type"] == "choice" and set(champ["options"]) == {"agent", "central", "deterministe"} and champ["default"] == "agent"
    for moteur in ("agent", "central", "deterministe"):
        with mock.patch.object(taches, "tache_run", return_value=0) as run:
            assert taches.main(["run", "--moteur", moteur]) == 0
        assert run.call_args.args[0].moteur == moteur                                   # la CLI accepte et transmet chaque moteur


def test_chaque_moteur_est_independant_des_autres():
    """Importer ou exécuter un moteur ne charge pas les autres : indépendance structurelle."""
    import subprocess
    for module, interdits in (("moteur_deterministe", ("agent_pilote", "moteur_central")), ("moteur_central.profils", ("agent_pilote", "moteur_deterministe"))):
        code = (f"import sys; sys.path[:0] = [{str(RACINE)!r}, {str(RACINE / 'bet_agent')!r}]; import {module}; "
                f"print([m for m in {interdits!r} if m in sys.modules])")
        sortie = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60).stdout.strip()
        assert sortie == "[]", (module, sortie)
