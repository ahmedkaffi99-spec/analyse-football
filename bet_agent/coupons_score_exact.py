"""Coupons de SCORES EXACTS pour une liste de matchs (demande ponctuelle du 28/10/2026 : 3 coupons de 2 jambes,
6 matchs au total). Le pipeline ne gère pas ce marché (ni cote, ni modèle, ni vérification) : script autonome,
lecture seule, jamais d'envoi Telegram.

Probabilité d'un score = 50 % marché (cote 1xBet sans marge, normalisée sur les scores servis) + 50 % modèle
(Poisson indépendant sur les buts attendus du pipeline : stats 10 matchs, H2H, Elo). Un score exact reste un pari très improbable (≈ 10 à 15 % le plus probable) : à lire comme tel."""
import itertools
import math
import os
import re
import sys
from datetime import datetime, timedelta

import requests

# 50/50 : le choix ne repose pas sur les cotes seules (demande du 28/10/2026) ; POIDS_MARCHE_SCORE_EXACT pour changer.
POIDS_MARCHE = float(os.getenv("POIDS_MARCHE_SCORE_EXACT") or 0.5)
MATCHS_DEMANDES = [("AC Milan", "Bologna"), ("Manchester City", "Brighton"), ("Bournemouth", "Aston Villa"),
                   ("Sunderland", "Brentford"), ("Fulham", "Crystal Palace"), ("Liverpool", "Chelsea")]
NOMS_PARI = ("exact score", "correct score")
_SCORE = re.compile(r"^\s*(\d+)\s*[:\-]\s*(\d+)\s*$")


def scores_1xbet(bookmakers, id_bookmaker=11):
    """{(buts_dom, buts_ext): cote} du pari « Exact Score » du bookmaker, depuis le champ `bookmakers` d'une réponse
    GET /odds. Les valeurs non numériques (« Other »...) et cotes <= 1 sont ignorées."""
    sortie = {}
    for bk in bookmakers:
        if bk.get("id") != id_bookmaker:
            continue
        for bet in bk.get("bets", []):
            if (bet.get("name") or "").strip().lower() not in NOMS_PARI:
                continue
            for v in bet.get("values", []):
                m = _SCORE.match(str(v.get("value")))
                try:
                    cote = float(v.get("odd"))
                except (TypeError, ValueError):
                    continue
                if m and cote > 1.0:
                    sortie[(int(m.group(1)), int(m.group(2)))] = cote
    return sortie


def probas_marche(cotes):
    """Probabilités sans marge, normalisées sur les scores servis."""
    somme = sum(1 / c for c in cotes.values())
    return {s: (1 / c) / somme for s, c in cotes.items()}


def poisson(mu, k):
    return math.exp(k * math.log(mu) - mu - math.lgamma(k + 1)) if mu > 0 else (1.0 if k == 0 else 0.0)


def probas_modele(mu_dom, mu_ext, scores):
    """Poisson indépendant, renormalisé sur les mêmes scores que le marché."""
    brut = {s: poisson(mu_dom, s[0]) * poisson(mu_ext, s[1]) for s in scores}
    total = sum(brut.values())
    return {s: p / total for s, p in brut.items()}


def melange(p_marche, p_modele=None):
    if not p_modele:
        return dict(p_marche)
    return {s: POIDS_MARCHE * p_marche[s] + (1 - POIDS_MARCHE) * p_modele[s] for s in p_marche}


def classement(probas, cotes):
    """[(score, proba, cote)] du plus au moins probable."""
    return sorted(((s, p, cotes[s]) for s, p in probas.items()), key=lambda x: -x[1])


def construire_coupons(par_match):
    """par_match : {nom: [(score, proba, cote), ...] trié}. 3 coupons de 2 jambes, les 6 matchs répartis une seule
    fois (un match = une jambe), chacun avec son score exact le plus probable. Les matchs sont classés par la
    probabilité de ce score : coupon 1 = les 2 plus probables, coupon 2 = les 2 suivants, coupon 3 = les 2 derniers.
    Renvoie [(titre, [(match, score, proba, cote)])]."""
    if len(par_match) != 6:
        raise ValueError("6 matchs requis")
    noms = sorted(par_match, key=lambda n: -par_match[n][0][1])
    jambes = [(n,) + par_match[n][0] for n in noms]
    titres = ["Coupon 1 — les 2 scores les plus probables", "Coupon 2 — probabilité moyenne",
              "Coupon 3 — les 2 scores les moins probables"]
    return [(titres[i], jambes[2 * i:2 * i + 2]) for i in range(3)]


def resume_coupon(jambes):
    cote = math.prod(j[3] for j in jambes)
    proba = math.prod(j[2] for j in jambes)
    return cote, proba


# ---------------------------------------------------------------------------------------------------------------
# Partie réseau (diagnostic GitHub Actions uniquement)
# ---------------------------------------------------------------------------------------------------------------

def main():
    import adaptateur_api_football as adf
    import analyser_et_envoyer as ae
    import collecte_donnees as cd

    H = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY") or ""}

    def get(chemin, **params):
        r = requests.get(f"{adf.API_FOOTBALL_BASE}/{chemin}", headers=H, params=params, timeout=30)
        return r.json().get("response") or []

    fixtures = []
    for i in range(-1, 11):
        fixtures += get("fixtures", date=(datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d"))
    print(f"{len(fixtures)} matchs API-Football sur 12 jours")
    par_match, details = {}, {}
    for dom, ext in MATCHS_DEMANDES:
        fx, score = cd.trouver_fixture_api_football(dom, ext, fixtures)
        if not fx:
            print(f"✗ {dom} - {ext} introuvable (meilleur score {score})")
            continue
        nom = f"{fx['teams']['home']['name']} - {fx['teams']['away']['name']}"
        statut = (fx['fixture'].get('status') or {}).get('short')
        print(f"✓ {nom} [{fx['league']['name']}] {fx['fixture']['date']} statut {statut}")
        reponse = get("odds", fixture=fx["fixture"]["id"])
        bookmakers = [bk for e in reponse for bk in e.get("bookmakers", [])]
        cotes = scores_1xbet(bookmakers)
        if len(cotes) < 6:
            noms = sorted({b.get("name") for bk in bookmakers for b in bk.get("bets", [])
                           if "score" in (b.get("name") or "").lower()})
            print(f"   ⚠️ pas assez de scores exacts chez 1xBet ({len(cotes)}) — paris « score » vus : {noms}")
            continue
        p_marche = probas_marche(cotes)
        mu = None
        try:
            hid, aid = fx["teams"]["home"]["id"], fx["teams"]["away"]["id"]
            sd_h = cd.recuperer_stats_10_derniers_matchs(hid, fx["teams"]["home"]["name"])
            sd_a = cd.recuperer_stats_10_derniers_matchs(aid, fx["teams"]["away"]["name"])
            xg = ae.calculer_xg_depuis_stats_detaillees(sd_h, sd_a)
            if xg:
                h2h = cd.recuperer_head_to_head(hid, aid, fx["teams"]["home"]["name"], fx["teams"]["away"]["name"])
                xg = ae._ponderer_avec_h2h(xg[0], xg[1], h2h)
                elo = cd.recuperer_elo(hid, aid, fx["league"]["id"], fx["fixture"]["date"])
                xg = ae._ajuster_avec_elo(xg[0], xg[1], elo)
                mu = xg
        except Exception as e:
            print(f"   ⚠️ buts attendus indisponibles ({e}) — probabilités du marché seules")
        p_modele = probas_modele(mu[0], mu[1], list(cotes)) if mu else None
        if mu:
            print(f"   buts attendus modèle {mu[0]:.2f} / {mu[1]:.2f}")
        par_match[nom] = classement(melange(p_marche, p_modele), cotes)
        details[nom] = par_match[nom][:4]
        print("   mélange : " + " | ".join(f"{s[0]}-{s[1]} {100 * p:.1f} % @{c:g}" for s, p, c in details[nom]))
        if p_modele:
            haut_modele = classement(p_modele, cotes)[:3]
            haut_marche = classement(p_marche, cotes)[:3]
            print("   modèle seul : " + " | ".join(f"{s[0]}-{s[1]} {100 * p:.1f} %" for s, p, c in haut_modele))
            print("   marché seul : " + " | ".join(f"{s[0]}-{s[1]} {100 * p:.1f} % @{c:g}" for s, p, c in haut_marche))
    if len(par_match) < 6:
        print(f"\n⚠️ {len(par_match)} match(s) exploitable(s) sur 6 — pas de coupons complets.")
        return
    for titre, jambes in construire_coupons(par_match):
        cote, proba = resume_coupon(jambes)
        print(f"\n=== {titre} ===")
        for nom, s, p, c in jambes:
            print(f"  • {nom} → score exact {s[0]}-{s[1]} @ {c:g}   (proba {100 * p:.1f} %)")
        print(f"  Cote totale ≈ {cote:,.0f} — chance de gagner ≈ {100 * proba:.2f} % (1 sur {1 / proba:,.0f})")


if __name__ == "__main__":
    sys.exit(main())
