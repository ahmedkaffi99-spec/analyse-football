"""Phase 2 — RÉFÉRENCE ALÉATOIRE reproductible et utilitaires statistiques (Python pur, graine fixe).

Principe : un « pari » est une sélection d'un marché d'un match avec une cote, une issue (gagne/perdu/push), une date et
(optionnellement) la probabilité juste de clôture. La stratégie testée choisit un sous-ensemble de paris. La référence
aléatoire rejoue N fois le MÊME problème : mêmes matchs, mêmes marchés (groupes match×marché), mêmes périodes (les mêmes
dates, donc même ordre pour le drawdown), même NOMBRE de paris par groupe, mêmes contraintes de cotes (fourchette
[min, max] observée sur les paris de la stratégie) — seule la CHOIX de la sélection est tiré au hasard, uniformément,
parmi les sélections éligibles du groupe. Résultat : la distribution de ce qu'un choix sans information aurait rapporté.

Bet = dict(match, groupe, selection, cote, issue, date, clv_ref (proba juste de clôture ou None))."""
import math
import random


def profit(b):
    """Gain par unité misée : cote-1 si gagné, -1 si perdu, 0 si push (remboursé)."""
    return {"gagne": b["cote"] - 1.0, "perdu": -1.0, "push": 0.0}.get(b["issue"])


def clv(b):
    """Valeur au prix équitable de clôture : cote × proba juste − 1 ; None si inconnue."""
    p = b.get("clv_ref")
    return None if p is None else b["cote"] * p - 1.0


def drawdown_max(bets):
    """Plus grande baisse (en unités) du cumul des gains, paris classés par date puis par ordre d'entrée."""
    pic = cum = dd = 0.0
    for b in sorted(bets, key=lambda x: x["date"]):
        g = profit(b)
        if g is None:
            continue
        cum += g
        pic = max(pic, cum)
        dd = max(dd, pic - cum)
    return dd


def resume(bets):
    """{n, roi (par unité misée), clv, taux de réussite (hors push), drawdown max}."""
    jugés = [b for b in bets if profit(b) is not None]
    if not jugés:
        return {"n": 0, "roi": float("nan"), "clv": float("nan"), "reussite": float("nan"), "drawdown": 0.0}
    cl = [clv(b) for b in jugés if clv(b) is not None]
    dec = [b for b in jugés if b["issue"] != "push"]
    return {"n": len(jugés), "roi": sum(profit(b) for b in jugés) / len(jugés),
            "clv": sum(cl) / len(cl) if cl else float("nan"),
            "reussite": sum(b["issue"] == "gagne" for b in dec) / len(dec) if dec else float("nan"),
            "drawdown": drawdown_max(jugés)}


def percentile(valeurs, q):
    v = sorted(x for x in valeurs if x == x)
    if not v:
        return float("nan")
    k = (len(v) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return v[f] + (v[c] - v[f]) * (k - f)


def intervalle(valeurs, niveau=0.95):
    a = (1 - niveau) / 2
    return percentile(valeurs, a), percentile(valeurs, 1 - a)


def bootstrap_roi(bets, n_boot=2000, graine=12345):
    """Intervalle de confiance du ROI de la stratégie par ré-échantillonnage des paris (avec remise)."""
    gains = [profit(b) for b in bets if profit(b) is not None]
    if len(gains) < 2:
        return float("nan"), float("nan")
    rng = random.Random(graine)
    moy = [sum(rng.choice(gains) for _ in gains) / len(gains) for _ in range(n_boot)]
    return intervalle(moy)


def simuler_aleatoire(tous, choisis, n_sim=1000, graine=2026):
    """Retourne la liste des résumés de n_sim simulations (une par tirage), reproductible (graine fixe).
    `tous` : tous les paris possibles ; `choisis` : ceux retenus par la stratégie (sous-ensemble de `tous`)."""
    if not choisis:
        return []
    cmin, cmax = min(b["cote"] for b in choisis), max(b["cote"] for b in choisis)
    par_groupe = {}
    for b in tous:
        if cmin <= b["cote"] <= cmax:
            par_groupe.setdefault((b["match"], b["groupe"]), []).append(b)
    nb = {}
    for b in choisis:
        k = (b["match"], b["groupe"])
        nb[k] = nb.get(k, 0) + 1
    groupes = sorted(nb)                     # ordre stable => reproductible
    rng = random.Random(graine)
    sims = []
    for _ in range(n_sim):
        tirage = []
        for g in groupes:
            eligibles = par_groupe.get(g, [])
            k = min(nb[g], len(eligibles))
            tirage += rng.sample(eligibles, k) if k else []
        sims.append(resume(tirage))
    return sims


def comparer(tous, choisis, n_sim=1000, graine=2026):
    """Texte de rapport : stratégie (ROI, IC bootstrap, CLV, drawdown) contre la distribution aléatoire (moyenne, IC 95 %,
    rang de la stratégie) + les 10 premières simulations individuelles."""
    s = resume(choisis)
    sims = simuler_aleatoire(tous, choisis, n_sim, graine)
    if not sims or s["n"] == 0:
        return "  (aucun pari)"
    rois = [x["roi"] for x in sims]
    clvs = [x["clv"] for x in sims]
    dds = [x["drawdown"] for x in sims]
    lo, hi = bootstrap_roi(choisis)
    p_valeur = sum(r >= s["roi"] for r in rois) / len(rois)
    ic_r, ic_c, ic_d = intervalle(rois), intervalle(clvs), intervalle(dds)
    lignes = [
        f"  stratégie : n={s['n']} ROI={s['roi']*100:+.2f}% (IC95 bootstrap {lo*100:+.1f}…{hi*100:+.1f}) CLV={s['clv']*100:+.2f}% "
        f"réussite={s['reussite']*100:.1f}% drawdown={s['drawdown']:.1f} u",
        f"  aléatoire ({len(sims)} simulations, graine {graine}, mêmes matchs/marchés/cotes/nombre de paris) : "
        f"ROI moyen={sum(rois)/len(rois)*100:+.2f}% IC95 [{ic_r[0]*100:+.1f}%, {ic_r[1]*100:+.1f}%] ; "
        f"CLV moyen={sum(c for c in clvs if c==c)/max(1,sum(1 for c in clvs if c==c))*100:+.2f}% IC95 [{ic_c[0]*100:+.1f}%, {ic_c[1]*100:+.1f}%] ; "
        f"drawdown moyen={sum(dds)/len(dds):.1f} u IC95 [{ic_d[0]:.1f}, {ic_d[1]:.1f}]",
        f"  rang : la stratégie dépasse {100-p_valeur*100:.1f}% des simulations en ROI (p unilatéral={p_valeur:.3f})",
        "  simulations 1-10 (ROI% / CLV% / drawdown) : " + " | ".join(
            f"{x['roi']*100:+.1f}/{x['clv']*100:+.1f}/{x['drawdown']:.0f}" for x in sims[:10])]
    return "\n".join(lignes)
