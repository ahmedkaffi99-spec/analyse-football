"""Phase 2 — comparaison scientifique WALK-FORWARD sur données historiques GRATUITES (Football-Data.co.uk).

Pour chaque match : les modèles ne voient que les matchs strictement antérieurs (refit tous les REFIT_JOURS).
Comparés : Poisson / Dixon-Coles / binomiale négative ; modèle seul / marché seul / mélange ; par marché (1X2,
Over/Under 2,5, handicap asiatique en demi-ligne) ; calibration ; erreurs ; valeur vs clôture (CLV).
Marché = cotes Pinnacle (la référence la plus tranchante), sans marge, à l'OUVERTURE (PS*) et à la CLÔTURE (PSC*).
Usage : python phase2_comparaison.py [saisons=2122,2223,2324,2425] [ligues=E0,F1,D1,I1,SP1]"""
import csv
import io
import sys
import urllib.request
from datetime import datetime

import phase2_modeles as pm

URL = "https://www.football-data.co.uk/mmz4281/{saison}/{ligue}.csv"
REFIT_JOURS = 14
POIDS = (0.0, 0.15, 0.35, 0.5, 1.0)           # poids du MODÈLE dans le mélange (0 = marché seul, 1 = modèle seul)
MODELES = ("poisson", "dixon_coles", "binomiale_negative")


def telecharger(saison, ligue):
    req = urllib.request.Request(URL.format(saison=saison, ligue=ligue), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("latin-1")


def _f(row, col):
    try:
        v = float(row.get(col, "") or "nan")
        return v if v == v and v > 1.0 else None
    except ValueError:
        return None


def parser(texte, ligue):
    """CSV -> liste de matchs (dict) triés par date ; ignore les lignes sans score."""
    out = []
    for row in csv.DictReader(io.StringIO(texte)):
        try:
            date = datetime.strptime(row["Date"], "%d/%m/%Y" if len(row["Date"]) == 10 else "%d/%m/%y")
            gd, ge = int(row["FTHG"]), int(row["FTAG"])
        except (KeyError, ValueError):
            continue
        ah = None
        try:
            ligne = float(row.get("AHh") or "nan")
            ligne_c = float(row.get("AHCh") or "nan")
            ah = {"ouv": ligne, "clo": ligne_c}
        except ValueError:
            pass
        out.append({
            "ligue": ligue, "date": date, "dom": row["HomeTeam"], "ext": row["AwayTeam"], "gd": gd, "ge": ge,
            "1x2_ouv": {"1": _f(row, "PSH"), "X": _f(row, "PSD"), "2": _f(row, "PSA")},
            "1x2_clo": {"1": _f(row, "PSCH"), "X": _f(row, "PSCD"), "2": _f(row, "PSCA")},
            "ou_ouv": {"O": _f(row, "P>2.5"), "U": _f(row, "P<2.5")},
            "ou_clo": {"O": _f(row, "PC>2.5"), "U": _f(row, "PC<2.5")},
            "ah": ah,
            "ah_ouv": {"H": _f(row, "PAHH"), "A": _f(row, "PAHA")},
            "ah_clo": {"H": _f(row, "PCAHH"), "A": _f(row, "PCAHA")},
        })
    out.sort(key=lambda m: m["date"])
    return out


def demi_ligne(x):
    return x is not None and x == x and abs(x * 2) % 2 == 1


def predire(matchs, debut_test):
    """Ajoute à chaque match de test {'p': {marché: {modèle: {sélection: proba}}}, 'freq': {modèle: fréquences}}."""
    forces, derniere, passe = None, None, []
    tests = []
    for m in matchs:
        if m["date"] >= debut_test:
            if forces is None or (m["date"] - derniere).days >= REFIT_JOURS:
                forces, derniere = pm.ajuster(passe, m["date"]), m["date"]
            mats = pm.matrices_modeles(forces, m["dom"], m["ext"])
            p = {"1x2": {}, "ou": {}, "ah": {}}
            for nom, mat in mats.items():
                p["1x2"][nom] = pm.probas_1x2(mat)
                po = pm.proba_over(mat, 2.5)
                p["ou"][nom] = {"O": po, "U": 1 - po}
                if m["ah"] and demi_ligne(m["ah"]["clo"]):
                    ph = pm.proba_ah_demi_ligne(mat, m["ah"]["clo"])
                    p["ah"][nom] = {"H": ph, "A": 1 - ph}
            m["p"] = p
            m["freq"] = {nom: pm.frequences_attendues(mat) for nom, mat in mats.items()}
            tests.append(m)
        passe.append((m["date"], m["dom"], m["ext"], m["gd"], m["ge"]))
    return tests


def gagnante(marche, m):
    gd, ge = m["gd"], m["ge"]
    if marche == "1x2":
        return "1" if gd > ge else ("X" if gd == ge else "2")
    if marche == "ou":
        return "O" if gd + ge > 2.5 else "U"
    return "H" if gd + m["ah"]["clo"] > ge else "A"


def evaluer(tests, marche):
    """Pour un marché : Brier / log-loss moyens (± erreur type) de chaque modèle, du marché (ouverture, clôture) et
    des mélanges, sur les matchs ayant une cote de clôture ; différences appariées vs le marché de clôture."""
    lignes, serie = [], {}
    for m in tests:
        cle_clo = "ah_clo" if marche == "ah" else f"{marche}_clo"
        cle_ouv = "ah_ouv" if marche == "ah" else f"{marche}_ouv"
        clo, ouv = pm.sans_marge(m[cle_clo]), pm.sans_marge(m[cle_ouv])
        if clo is None or marche not in m["p"] or not m["p"][marche]:
            continue
        g = gagnante(marche, m)
        serie.setdefault("marche_cloture", []).append((pm.brier(clo, g), pm.log_loss(clo, g)))
        if ouv:
            serie.setdefault("marche_ouverture", []).append((pm.brier(ouv, g), pm.log_loss(ouv, g)))
        for nom, p in m["p"][marche].items():
            for w in POIDS:
                q = pm.melanger(clo, p, w) if w < 1 else p
                lib = nom if w == 1 else f"{nom}+cloture(w={w})"
                if 0 < w < 1 or w == 1:
                    serie.setdefault(lib, []).append((pm.brier(q, g), pm.log_loss(q, g)))
    base = serie.get("marche_cloture", [])
    for lib, v in serie.items():
        mb, eb = pm.moyenne_et_erreur_type([x[0] for x in v])
        ml, el = pm.moyenne_et_erreur_type([x[1] for x in v])
        if lib != "marche_cloture" and len(v) == len(base):
            d = [a[0] - b[0] for a, b in zip(v, base)]
            md, ed = pm.moyenne_et_erreur_type(d)
            dl = [a[1] - b[1] for a, b in zip(v, base)]
            mdl, edl = pm.moyenne_et_erreur_type(dl)
            lignes.append((lib, len(v), mb, ml, md, ed, mdl, edl))
        else:
            lignes.append((lib, len(v), mb, ml, None, None, None, None))
    return sorted(lignes, key=lambda x: x[3])


def analyse_erreurs(tests):
    """Fréquences observées vs attendues par modèle : nuls, écarts >= 3 buts, totaux >= 5 / <= 1."""
    n = len(tests)
    obs = {"nul": sum(m["gd"] == m["ge"] for m in tests) / n,
           "ecart>=3": sum(abs(m["gd"] - m["ge"]) >= 3 for m in tests) / n,
           "total>=5": sum(m["gd"] + m["ge"] >= 5 for m in tests) / n,
           "total<=1": sum(m["gd"] + m["ge"] <= 1 for m in tests) / n}
    res = {nom: {k: sum(m["freq"][nom][k] for m in tests) / n for k in obs} for nom in MODELES}
    return obs, res


def calibration(tests, marche, source):
    """source = 'marche' ou un nom de modèle ; points (proba, issue) pour toutes les sélections."""
    pts = []
    for m in tests:
        cle = "ah_clo" if marche == "ah" else f"{marche}_clo"
        clo = pm.sans_marge(m[cle])
        if clo is None or not m["p"].get(marche):
            continue
        p = clo if source == "marche" else m["p"][marche][source]
        g = gagnante(marche, m)
        pts += [(p[s], 1.0 if s == g else 0.0) for s in p]
    return pm.table_calibration(pts, 10)


def paris_et_clv(tests, marche, source, seuil=0.03):
    """Parier à l'OUVERTURE Pinnacle quand la probabilité de `source` dépasse la proba juste d'ouverture de `seuil` :
    CLV moyen (valeur au prix de clôture sans marge), ROI réel à l'ouverture, nombre de paris."""
    n, clv, roi = 0, [], []
    for m in tests:
        co, cc = (("ah_ouv", "ah_clo") if marche == "ah" else (f"{marche}_ouv", f"{marche}_clo"))
        ouv_c, clo = m[co], pm.sans_marge(m[cc])
        ouv = pm.sans_marge(ouv_c)
        if ouv is None or clo is None or not m["p"].get(marche):
            continue
        p = m["p"][marche][source]
        g = gagnante(marche, m)
        for s in p:
            if p[s] - ouv[s] >= seuil:
                n += 1
                clv.append(pm.clv_pct(ouv_c[s], clo[s]))
                roi.append((ouv_c[s] - 1) if s == g else -1.0)
    mc, ec = pm.moyenne_et_erreur_type(clv)
    mr, er = pm.moyenne_et_erreur_type(roi)
    return n, mc, ec, mr, er


def rapport(tests):
    out = [f"MATCHS TESTÉS (hors échantillon, walk-forward) : {len(tests)}"]
    for marche, titre in (("1x2", "1X2"), ("ou", "Over/Under 2,5"), ("ah", "Handicap asiatique (demi-lignes seules)")):
        lignes = evaluer(tests, marche)
        if not lignes:
            continue
        out.append(f"\n=== {titre} === (Brier / log-loss moyens ; Δ vs marché de clôture : négatif = mieux que le marché)")
        out.append(f"{'source':38} {'n':>5} {'Brier':>8} {'LogLoss':>8} {'ΔBrier±es':>16} {'ΔLL±es':>16}")
        for lib, n, mb, ml, md, ed, mdl, edl in lignes:
            d1 = f"{md:+.4f}±{ed:.4f}" if md is not None else "—"
            d2 = f"{mdl:+.4f}±{edl:.4f}" if mdl is not None else "—"
            out.append(f"{lib:38} {n:5d} {mb:8.4f} {ml:8.4f} {d1:>16} {d2:>16}")
        out.append(f"-- Calibration ({titre}) : annoncé moyen vs réel par tranche de 10 %")
        for src in ("marche", "dixon_coles"):
            lg, ece = calibration(tests, marche, src)
            out.append(f"  [{src}] ECE={ece:.4f} | " + " ".join(f"{t*10}-{t*10+10}%:{n}:{a*100:.0f}→{r*100:.0f}" for t, n, a, r in lg))
        out.append(f"-- Paris à l'OUVERTURE Pinnacle si proba(source) ≥ juste+3 pts : n, CLV moyen±es, ROI réel±es")
        for src in MODELES:
            n, mc, ec, mr, er = paris_et_clv(tests, marche, src)
            out.append(f"  {src:20} n={n:5d} CLV={mc*100:+.2f}%±{ec*100:.2f} ROI={mr*100:+.2f}%±{er*100:.2f}" if n > 1 else f"  {src:20} n={n}")
    obs, att = analyse_erreurs(tests)
    out.append("\n=== Analyse des erreurs : fréquence OBSERVÉE vs ATTENDUE par le modèle ===")
    out.append(f"{'événement':10} {'observé':>8} " + " ".join(f"{k:>20}" for k in MODELES))
    for k in obs:
        out.append(f"{k:10} {obs[k]*100:7.1f}% " + " ".join(f"{att[n][k]*100:19.1f}%" for n in MODELES))
    return "\n".join(out)


def main(argv):
    saisons = ((argv[1] if len(argv) > 1 else "") or "2021,2122,2223,2324,2425").split(",")
    ligues = ((argv[2] if len(argv) > 2 else "") or "E0,F1,D1,I1,SP1").split(",")
    tous = []
    for lg in ligues:
        matchs = []
        for s in saisons:
            try:
                matchs += parser(telecharger(s, lg), lg)
            except Exception as e:  # noqa: BLE001 — une saison manquante ne doit pas tout arrêter
                print(f"[{lg} {s}] indisponible : {e}")
        matchs.sort(key=lambda m: m["date"])
        if len(matchs) < 600:
            print(f"[{lg}] trop peu de matchs ({len(matchs)})")
            continue
        debut_test = matchs[len(matchs) // 3]["date"]          # le premier tiers sert de rodage (jamais évalué)
        print(f"[{lg}] {len(matchs)} matchs ; test à partir de {debut_test.date()}")
        tous += predire(matchs, debut_test)
    if tous:
        print(rapport(tous))


if __name__ == "__main__":
    main(sys.argv)
