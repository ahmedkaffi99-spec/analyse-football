import random
from datetime import datetime, timedelta

import phase2_comparaison as pc

ENTETE = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,PSH,PSD,PSA,PSCH,PSCD,PSCA,P>2.5,P<2.5,PC>2.5,PC<2.5,AHh,AHCh,PAHH,PAHA,PCAHH,PCAHA"


def csv_synthetique(n=700):
    random.seed(3)
    equipes = [f"T{i}" for i in range(8)]
    lignes, d0 = [ENTETE], datetime(2022, 8, 1)
    for i in range(n):
        a, b = random.sample(equipes, 2)
        gd, ge = random.choice([0, 1, 1, 2, 3]), random.choice([0, 0, 1, 2])
        d = (d0 + timedelta(days=i // 3)).strftime("%d/%m/%Y")
        lignes.append(f"E0,{d},{a},{b},{gd},{ge},2.1,3.4,3.6,2.0,3.5,3.8,1.9,1.95,1.9,1.95,-0.5,-0.5,1.95,1.95,1.9,2.0")
    return "\n".join(lignes)


def test_parser_et_pipeline_complet():
    matchs = pc.parser(csv_synthetique(), "E0")
    assert len(matchs) == 700 and matchs[0]["1x2_clo"]["1"] == 2.0
    tests = pc.predire(matchs, matchs[300]["date"])
    assert tests and "poisson" in tests[0]["p"]["1x2"]
    texte = pc.rapport(tests)
    assert "1X2" in texte and "Handicap asiatique" in texte and "Analyse des erreurs" in texte


def test_pas_de_fuite_de_donnees_futures():
    matchs = pc.parser(csv_synthetique(), "E0")
    d = matchs[300]["date"]
    avant = [m for m in matchs if m["date"] < d]
    # la prédiction du premier match de test ne dépend pas des résultats futurs : modifier le futur ne change rien
    t1 = pc.predire([dict(m) for m in matchs], d)[0]["p"]["1x2"]["poisson"]
    fut = [dict(m, gd=9, ge=0) if m["date"] >= d else dict(m) for m in matchs]
    t2 = pc.predire(fut, d)[0]["p"]["1x2"]["poisson"]
    assert t1 == t2
    assert avant


def test_demi_ligne():
    assert pc.demi_ligne(-0.5) and pc.demi_ligne(1.5) and not pc.demi_ligne(-0.25) and not pc.demi_ligne(0.0)
