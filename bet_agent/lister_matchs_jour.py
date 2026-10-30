"""Matchs à venir du jour (UTC) par compétition, TOUTES compétitions confondues sauf féminines/jeunes/réserves —
pour comprendre quels matchs le pipeline retient ou ignore (diagnostic du 28/10/2026 : « il y avait 18 matchs »)."""
import os
from collections import defaultdict
from datetime import datetime, timezone

import requests

import adaptateur_api_football as adf
import collecte_donnees as cd

H = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY") or ""}


def horaires_paires(paires, jour):
    """Coup d'envoi (UTC), statut et fin estimée (+1h50) de chaque paire « A vs B » — pour savoir quand commence
    le premier match d'un lot de coupons et quand termine le dernier."""
    from datetime import timedelta
    r = requests.get(f"{adf.API_FOOTBALL_BASE}/fixtures", headers=H, params={"date": jour}, timeout=30)
    fixtures = r.json().get("response") or []
    lignes = []
    for paire in paires:
        dom, _, ext = paire.partition(" vs ")
        fx, score = cd.trouver_fixture_api_football(dom.strip(), ext.strip(), fixtures)
        if not fx:
            lignes.append((None, paire, "introuvable", ""))
            continue
        debut = datetime.fromisoformat(fx["fixture"]["date"].replace("Z", "+00:00"))
        statut = (fx["fixture"].get("status") or {}).get("short")
        lignes.append((debut, paire, statut, f"{fx['league']['name']}"))
    for debut, paire, statut, ligue in sorted(lignes, key=lambda x: (x[0] is None, x[0])):
        if debut is None:
            print(f"?? {paire} — introuvable")
            continue
        fin = debut + timedelta(minutes=110)
        print(f"{debut:%H:%M} UTC → fin vers {fin:%H:%M} UTC  {paire}  [{ligue}] statut {statut}")


def main():
    if os.getenv("PAIRES"):
        return horaires_paires([p.strip() for p in os.environ["PAIRES"].split(";") if p.strip()],
                               os.getenv("JOUR") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    jour = os.getenv("JOUR") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = requests.get(f"{adf.API_FOOTBALL_BASE}/fixtures", headers=H, params={"date": jour}, timeout=30)
    fixtures = r.json().get("response") or []
    par_ligue = defaultdict(list)
    for fx in fixtures:
        if ((fx.get("fixture") or {}).get("status") or {}).get("short") != "NS":
            continue
        dom, ext = fx["teams"]["home"]["name"], fx["teams"]["away"]["name"]
        if cd.contient_indicateur_reserve(dom) or cd.contient_indicateur_reserve(ext) \
                or cd.est_equipe_feminine_api_football(dom) or cd.est_equipe_feminine_api_football(ext):
            continue
        lg = fx["league"]
        par_ligue[(lg["id"], lg["name"], lg.get("country"))].append((fx["fixture"]["date"], dom, ext))
    print(f"{jour} : {sum(len(v) for v in par_ligue.values())} match(s) à venir (hors féminines/jeunes/réserves), "
          f"{len(par_ligue)} compétition(s)")
    pipeline = cd.LIGUES_FILTRE_API_FOOTBALL
    print("\n=== Compétitions avec le plus de matchs (✓ = déjà retenue par le pipeline) ===")
    for (lid, nom, pays), matchs in sorted(par_ligue.items(), key=lambda x: -len(x[1]))[:40]:
        print(f"{'✓' if lid in pipeline else ' '} [{lid}] {pays} — {nom} : {len(matchs)}")
        if len(matchs) <= 6 or lid in pipeline:
            for d, h, a in sorted(matchs):
                print(f"      {d[11:16]} {h} - {a}")


if __name__ == "__main__":
    main()
