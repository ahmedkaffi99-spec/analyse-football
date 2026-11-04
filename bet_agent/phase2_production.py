"""Phase 2 — comparaison du VRAI moteur de production avec Pinnacle (lecture seule, aucune écriture, aucun Telegram).

Le moteur réel est REJOUÉ sur la collecte brute archivée de chaque run (mêmes entrées que lors du run : cotes 1xBet,
stats, H2H, Elo) : analyser_et_envoyer.agent3_calcul_pool_candidats -> pour chaque candidat : proba_poisson_pct (modèle de
production SEUL), proba_marche_pct (marché 1xBet sans marge, au moment de la collecte), proba_modele_pct (mélange final
65 % marché / 35 % modèle). Résultats réels : scores de la table matchs. Pinnacle : cotes de clôture Football-Data
(1X2, Over/Under 2,5, handicap asiatique principal) rapprochées par date + noms d'équipes (rapprochement tracé).
Limite assumée : les probas de production datent de l'instant de collecte (heures avant le match), la clôture Pinnacle
est au coup d'envoi : l'écart d'échéance est signalé, jamais masqué. Un seul candidat gardé par (match, marché, sélection) :
la collecte la plus récente."""
import contextlib
import io
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import phase2_comparaison as pc
import phase2_modeles as pm
import phase2_reference as pr

DEPUIS = os.environ.get("PHASE2_DEPUIS", "2026-10-22")
LIGUES_FD = ["E0", "F1", "D1", "I1", "SP1"]
ALIAS = {"manchester united": "man united", "manchester city": "man city", "paris saint germain": "paris sg",
         "borussia monchengladbach": "m'gladbach", "atletico madrid": "ath madrid", "athletic club": "ath bilbao",
         "real betis": "betis", "real sociedad": "sociedad", "ac milan": "milan", "hellas verona": "verona",
         "borussia dortmund": "dortmund", "bayer leverkusen": "leverkusen", "eintracht frankfurt": "ein frankfurt",
         "newcastle united": "newcastle", "wolverhampton wanderers": "wolves", "tottenham hotspur": "tottenham",
         "west ham united": "west ham", "nottingham forest": "nott'm forest", "leeds united": "leeds",
         "brighton hove albion": "brighton", "olympique marseille": "marseille", "olympique lyonnais": "lyon",
         "stade rennais": "rennes", "as monaco": "monaco", "1 fc union berlin": "union berlin", "fsv mainz 05": "mainz",
         "vfl wolfsburg": "wolfsburg", "bayern munchen": "bayern munich", "fc koln": "fc koln",
         "1 fc heidenheim": "heidenheim", "sc freiburg": "freiburg", "tsg hoffenheim": "hoffenheim",
         "celta vigo": "celta", "rayo vallecano": "vallecano", "deportivo alaves": "alaves", "espanyol": "espanol"}


def norm(nom):
    from unidecode import unidecode
    n = re.sub(r"[^a-z0-9' ]", " ", unidecode(nom or "").lower())
    n = re.sub(r"\b(fc|afc|cf|sc|ssc|ac|as)\b", " ", n) if n.strip() not in ("ac milan", "as monaco") else n
    n = re.sub(r"\s+", " ", n).strip()
    return ALIAS.get(n, n)


def score_noms(a, b):
    from rapidfuzz import fuzz
    return fuzz.token_set_ratio(norm(a), norm(b))


def rapprocher(dom, ext, date_iso, lignes_fd, seuil=80):
    """Ligne Football-Data (même match, ±1 jour) ou None ; retourne (ligne, score moyen)."""
    try:
        d = datetime.fromisoformat(date_iso.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return None, 0
    meilleur, ms = None, 0
    for r in lignes_fd:
        if abs((r["date"].date() - d.date()).days) > 1:
            continue
        s = min(score_noms(dom, r["dom"]), score_noms(ext, r["ext"]))
        if s >= seuil and s > ms:
            meilleur, ms = r, s
    return meilleur, ms


def charger_fd(saisons):
    lignes = []
    for s in saisons:
        for lg in LIGUES_FD:
            try:
                lignes += pc.parser(pc.telecharger(s, lg), lg)
            except Exception as e:  # noqa: BLE001
                print(f"[FD {lg} {s}] indisponible : {e}")
    return lignes


def p_pinnacle(pick, fd):
    """Probabilité juste de CLÔTURE Pinnacle de ce pari, ou None si le marché n'existe pas chez Football-Data."""
    cat, sel, h = pick["categorie"], (pick["selection"] or "").lower(), pick.get("handicap")
    if cat == "Total" and h == 2.5:
        p = pm.sans_marge(fd["ou_clo"])
        return None if p is None else p["O" if "over" in sel else "U"]
    if cat == "Handicap" and fd.get("ah") and h is not None and abs(h - fd["ah"]["clo"]) < 1e-9 and pc.demi_ligne(h):
        p = pm.sans_marge(fd["ah_clo"])
        return None if p is None else p["H" if sel in ("home", "1") else "A"]
    p3 = pm.sans_marge(fd["1x2_clo"])
    if p3 is None:
        return None
    if cat == "Double Chance":
        k = re.sub(r"[^a-z0-9]", "", sel)
        return {"1x": p3["1"] + p3["X"], "x2": p3["X"] + p3["2"], "2x": p3["X"] + p3["2"], "12": p3["1"] + p3["2"]}.get(k)
    if cat == "Draw No Bet":
        return p3["1"] / (p3["1"] + p3["2"]) if sel in ("home", "1") else p3["2"] / (p3["1"] + p3["2"])
    return None


def rejouer_runs(db, depuis):
    """[candidat] avec p_modele/p_marche/p_final, cote, issue, identité du match. Stdout du moteur étouffé."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from sqlalchemy import select
    from app.models import Match, Run
    from app.services.archives import telecharger_collecte
    import analyser_et_envoyer as ae
    import verifier_resultats as vr

    ae.verifier_fraicheur_matchs = lambda ms, _d=None: ms           # pas d'appel réseau, pas de filtre « n'est plus pariable »
    ae.COTE_MIN_JAMBE, ae.COTE_MAX_JAMBE = 0.0, 0.0                  # toutes les cotes, jamais de fourchette
    scores = {}
    for m in db.execute(select(Match).where(Match.score_domicile.is_not(None))).scalars():
        if m.fixture_id_oddspapi:
            scores[m.fixture_id_oddspapi] = (m.score_domicile, m.score_exterieur)
    runs = db.execute(select(Run).where(Run.statut == "termine", Run.lance_le >= datetime.fromisoformat(depuis).replace(
        tzinfo=timezone.utc)).order_by(Run.lance_le)).scalars().all()
    garde, stats = {}, {"runs": len(runs), "archives_ok": 0, "archives_ko": 0, "sans_score": 0}
    for run in runs:
        try:
            donnees = telecharger_collecte(db, run)
            with contextlib.redirect_stdout(io.StringIO()):
                pool = ae.agent3_calcul_pool_candidats(donnees)
            stats["archives_ok"] += 1
        except Exception as e:  # noqa: BLE001 — jamais silencieux : compté et affiché
            stats["archives_ko"] += 1
            print(f"[run {run.id}] archive/rejeu impossible : {str(e)[:100]}")
            continue
        for cands in pool.values():
            for c in cands:
                pk = c["pick"]
                fx = c["fixture_id_oddspapi"]
                if None in (pk.get("proba_poisson_pct"), pk.get("proba_marche_pct"), pk.get("proba_modele_pct")):
                    continue
                garde[(fx, pk["marche"], pk["selection"])] = {       # la collecte la plus récente écrase la précédente
                    "match": fx, "groupe": pk["marche"], "selection": pk["selection"], "cote": pk["cote"], "issue": None,
                    "categorie": pk["categorie"], "handicap": pk.get("handicap"), "pick": pk, "date": run.lance_le,
                    "p_modele": pk["proba_poisson_pct"] / 100, "p_marche": pk["proba_marche_pct"] / 100,
                    "p_final": pk["proba_modele_pct"] / 100, "edge": pk.get("edge_pct"),
                    "dom": c["home_nom"], "ext": c["away_nom"], "date_iso": c["date_iso"], "ligue": c.get("competition")}
    print(f"Rejeu : {stats} ; candidats distincts : {len(garde)} ; scores connus en base : {len(scores)}")
    return list(garde.values()), scores


def un_par_evenement(bets):
    """Marchés à deux issues : une seule sélection par (match, marché) (Brier identique des deux côtés) ; les autres : toutes."""
    par = {}
    for b in bets:
        par.setdefault((b["match"], b["groupe"]), []).append(b)
    out = []
    for v in par.values():
        out += [min(v, key=lambda x: str(x["selection"]))] if len(v) == 2 else v
    return out


def y(b):
    return 1.0 if b["issue"] == "gagne" else 0.0


def scores_binaires(evts, cle):
    ev = [e for e in evts if e["issue"] != "push" and e.get(cle) is not None]
    br = [(e[cle] - y(e)) ** 2 for e in ev]
    ll = [-(y(e) * __import__("math").log(max(e[cle], 1e-9)) + (1 - y(e)) * __import__("math").log(max(1 - e[cle], 1e-9))) for e in ev]
    return ev, br, ll


def tableau_comparaison(evts, titre):
    """Brier / log-loss des approches sur les MÊMES événements ; Δ apparié vs Pinnacle."""
    evts = [e for e in evts if e["issue"] != "push" and e.get("p_pin") is not None]
    if not evts:
        return [f"{titre} : aucun événement commun avec Pinnacle"]
    taux = sum(y(e) for e in evts) / len(evts)
    for e in evts:
        e["p_melange_pin"] = 0.35 * e["p_modele"] + 0.65 * e["p_pin"]
        e["p_alea"] = taux
    approches = [("Pinnacle clôture seul", "p_pin"), ("Modèle production seul", "p_modele"),
                 ("Production final (65 % 1xBet + 35 % modèle)", "p_final"), ("Marché 1xBet seul (instant collecte)", "p_marche"),
                 ("Modèle production 35 % + Pinnacle 65 %", "p_melange_pin"), ("Référence aléatoire (taux de base constant)", "p_alea")]
    lignes = [f"{titre} — {len(evts)} événements communs (taux de base {taux*100:.1f} %)",
              f"  {'approche':46} {'Brier':>7} {'LogLoss':>8} {'ΔBrier vs Pinnacle ± es':>26}"]
    base = [(e["p_pin"] - y(e)) ** 2 for e in evts]
    for nom, cle in approches:
        _, br, ll = scores_binaires(evts, cle)
        mb, _ = pm.moyenne_et_erreur_type(br)
        ml, _ = pm.moyenne_et_erreur_type(ll)
        md, ed = pm.moyenne_et_erreur_type([a - b for a, b in zip(br, base)])
        lignes.append(f"  {nom:46} {mb:7.4f} {ml:8.4f} {md:+.4f} ± {ed:.4f}")
    return lignes


def rapport(cands, fd_lignes, scores=None):
    import verifier_resultats as vr
    scores = scores or {}
    out = [f"\nCANDIDATS REJOUÉS (un par match×marché×sélection, dernière collecte) : {len(cands)} "
           f"sur {len({c['match'] for c in cands})} matchs"]
    # --- rapprochement Football-Data (tracé) puis jugement : score Football-Data (match terminé) sinon score en base
    non_trouves, cache = set(), {}
    src = {"football-data": 0, "base": 0, "aucun": 0}
    for c in cands:
        k = (c["dom"], c["ext"], c["date_iso"])
        if k not in cache:
            cache[k] = rapprocher(c["dom"], c["ext"], c["date_iso"], fd_lignes)
        fd, s = cache[k]
        score = None
        if fd is not None:
            c["p_pin"], c["fd_ligue"] = p_pinnacle(c["pick"], fd), fd["ligue"]
            score = (fd["gd"], fd["ge"])
            src["football-data"] += 1
        else:
            non_trouves.add(f"{c['dom']} - {c['ext']}")
            c["p_pin"] = None
            score = scores.get(c["match"])
            src["base" if score else "aucun"] += 1
        c["issue"] = vr.grader_pick(c["pick"], *score) if score else None
    cands[:] = [c for c in cands if c["issue"] in ("gagne", "perdu", "push")]
    nb_matchs_fd = sum(1 for v in cache.values() if v[0] is not None)
    out.append(f"Jugement : {src} (par candidat). Candidats jugés : {len(cands)} sur {len({c['match'] for c in cands})} matchs")
    out.append(f"Rapprochement Football-Data : {nb_matchs_fd}/{len(cache)} matchs retrouvés (date ±1 jour, noms ≥ 80/100). "
               f"Hors 5 championnats ou non retrouvés ({len(non_trouves)}) : {sorted(non_trouves)[:10]}")
    avec_pin = [c for c in cands if c.get("p_pin") is not None]
    out.append(f"Paris avec probabilité Pinnacle correspondante (même événement exact) : {len(avec_pin)}")
    # --- 1) comparaison à 4 approches sur événements communs, par marché
    cats = sorted({c["categorie"] for c in avec_pin})
    out.append("\n=== COMPARAISON À 4+ APPROCHES (mêmes événements, même résultat réel) ===")
    out += tableau_comparaison(un_par_evenement(avec_pin), "TOUS MARCHÉS COMMUNS")
    for cat in cats:
        out += tableau_comparaison(un_par_evenement([c for c in avec_pin if c["categorie"] == cat]), f"Marché {cat}")
    ligues = sorted({c["fd_ligue"] for c in avec_pin})
    for lg in ligues:
        out += tableau_comparaison(un_par_evenement([c for c in avec_pin if c["fd_ligue"] == lg]), f"Championnat {lg}")
    # --- 2) production vs 1xBet sur TOUS les candidats (sans Pinnacle) : plus gros échantillon
    out.append("\n=== MODÈLE DE PRODUCTION vs MARCHÉ 1xBet vs FINAL — TOUS les paris jugés (sans exigence Pinnacle) ===")
    tout = un_par_evenement(cands)
    out.append(f"  {'groupe':26} {'n':>5} {'Brier modèle':>13} {'Brier 1xBet':>12} {'Brier final':>12} {'Δ final-1xBet ± es':>20}")
    for nom, ens in [("TOUS", tout)] + [(cat, [c for c in tout if c["categorie"] == cat]) for cat in sorted({c["categorie"] for c in tout})]:
        ev = [e for e in ens if e["issue"] != "push"]
        if len(ev) < 15:
            continue
        b = {k: [(e[k] - y(e)) ** 2 for e in ev] for k in ("p_modele", "p_marche", "p_final")}
        md, ed = pm.moyenne_et_erreur_type([a - c for a, c in zip(b["p_final"], b["p_marche"])])
        out.append(f"  {nom[:26]:26} {len(ev):5d} {sum(b['p_modele'])/len(ev):13.4f} {sum(b['p_marche'])/len(ev):12.4f} "
                   f"{sum(b['p_final'])/len(ev):12.4f} {md:+.4f} ± {ed:.4f}")
    # --- 3) calibration (final et marché 1xBet)
    for cle, nom in (("p_final", "final de production"), ("p_marche", "marché 1xBet")):
        pts = [(e[cle], y(e)) for e in tout if e["issue"] != "push"]
        lg, ece = pm.table_calibration(pts, 10)
        out.append(f"Calibration {nom} : ECE={ece:.4f} | " + " ".join(f"{t*10}-{t*10+10}%:{n}:{a*100:.0f}→{r*100:.0f}" for t, n, a, r in lg))
    # --- 4) ROI simulé, EV, CLV, drawdown : règle de production (edge final ≥ 0, cotes 1,25-3,00) vs aléatoire
    out.append("\n=== ROI SIMULÉ (mise unitaire à la cote 1xBet), EV annoncée vs réalisée, CLV vs clôture Pinnacle, drawdown ===")
    for b in cands:
        b["clv_ref"] = b.get("p_pin")
    choisis = [b for b in cands if b["edge"] is not None and b["edge"] >= 0 and 1.25 <= b["cote"] <= 3.0]
    tous = [b for b in cands if 1.25 <= b["cote"] <= 3.0]
    if choisis:
        ev_annoncee = sum(b["cote"] * b["p_final"] - 1 for b in choisis) / len(choisis)
        ev_pin = [b["cote"] * b["p_pin"] - 1 for b in choisis if b.get("p_pin") is not None]
        out.append(f"  EV annoncée par le moteur (cote×p_final−1) = {ev_annoncee*100:+.2f}% ; EV au prix juste Pinnacle "
                   f"({len(ev_pin)} paris) = {(sum(ev_pin)/len(ev_pin)*100 if ev_pin else float('nan')):+.2f}%")
        out.append(pr.comparer(tous, choisis, 1000, 2026))
        for cat in sorted({b["categorie"] for b in choisis}):
            sous = [b for b in choisis if b["categorie"] == cat]
            r = pr.resume(sous)
            if r["n"] >= 10:
                out.append(f"  marché {cat}: n={r['n']} ROI={r['roi']*100:+.1f}% réussite={r['reussite']*100:.0f}% CLV={r['clv']*100:+.1f}%")
        for lg in sorted({b.get("fd_ligue") for b in choisis if b.get("fd_ligue")}):
            r = pr.resume([b for b in choisis if b.get("fd_ligue") == lg])
            out.append(f"  championnat {lg}: n={r['n']} ROI={r['roi']*100:+.1f}% CLV={r['clv']*100:+.1f}%")
    else:
        out.append("  aucun pari ne satisfait la règle")
    return "\n".join(out)


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.database import SessionLocal
    saisons = ["2627"]
    with SessionLocal() as db:
        cands, scores = rejouer_runs(db, DEPUIS)
    fd = charger_fd(saisons)
    print(f"Football-Data : {len(fd)} matchs chargés ({saisons})")
    if fd:
        n_pin = sum(1 for r in fd if r["1x2_clo"]["1"] is not None)
        n_ou = sum(1 for r in fd if r["ou_clo"]["O"] is not None)
        n_ah = sum(1 for r in fd if r["ah_clo"]["H"] is not None)
        print(f"Colonnes vues (1re ligne) : {fd[0].get('_pin_cols')}")
        print(f"Matchs avec cotes de clôture Pinnacle : 1X2 {n_pin}/{len(fd)} ; Over/Under 2,5 {n_ou}/{len(fd)} ; handicap {n_ah}/{len(fd)}")
    print(rapport(cands, fd, scores))


if __name__ == "__main__":
    main()
