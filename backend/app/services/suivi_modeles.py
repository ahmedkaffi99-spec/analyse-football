"""Phase 4 — suivi individuel des modèles IA (comparaison DeepSeek / GPT / Claude / Gemini).

Règles : (1) un coupon n'est attribué à un modèle que s'il est issu d'une composition INDIVIDUELLE ; la source « vote_collectif »
est refusée ; (2) aucune cote, probabilité ou résultat n'est inventé : une donnée absente reste None ; (3) anti-doublon par empreinte des
sélections ; (4) les coupons non réglés sont exclus des statistiques principales ; (5) un même match présent dans plusieurs coupons
crée des observations corrélées : les statistiques le signalent (grappes par match) ; (6) aucun gagnant n'est désigné sous 30 coupons
réglés par modèle. Module pur : aucun appel réseau, aucune écriture en base (la persistance SQL est préparée dans backend/migrations/phase4)."""

import hashlib
import json
import math
from collections import defaultdict

SEUIL_ECHANTILLON = 30   # coupons réglés minimum par modèle pour comparer
SOURCES_ACCEPTEES = ("individuel",)

MODELES = {
    "deepseek": {"nom": "DeepSeek Flash 4.1", "ids": ("deepseek-flash", "deepseek/deepseek-v4.1-flash")},
    "gpt": {"nom": "GPT-6.1-Sol", "ids": ("openai/gpt-6.1-sol", "gpt-6.1-sol")},
    "claude": {"nom": "Claude Sonnet 5.5", "ids": ("anthropic/claude-sonnet-5.5",)},
    "gemini": {"nom": "Gemini Argon 4", "ids": ("google/gemini-4-argon",)},
}


class AttributionRefusee(ValueError):
    pass


def modele_canonique(identifiant):
    """Renvoie la clé canonique (deepseek/gpt/claude/gemini) ou lève AttributionRefusee : jamais de devinette (« base », « vote », None…)."""
    for cle, m in MODELES.items():
        if identifiant in m["ids"]:
            return cle
    raise AttributionRefusee(f"identifiant de modèle inconnu ou non attribuable : {identifiant!r}")


def empreinte(selections):
    """Empreinte stable d'un coupon : (match, marché, sélection, handicap) triés ; la cote n'en fait pas partie."""
    cles = sorted((int(s["match_id"]), str(s["marche"]), str(s["selection"]), s.get("handicap")) for s in selections)
    return hashlib.sha1(json.dumps(cles, default=str).encode()).hexdigest()[:16]


def nouveau_coupon(protocole, jour, modele, profil, selections, source="individuel", run_id=None, couts=None):
    """Construit un enregistrement de coupon individuel. Lève AttributionRefusee pour le vote collectif ou un modèle inconnu.
    Chaque sélection : {match_id, marche, selection, cote, handicap?, proba_pct?}. La cote totale est le produit des cotes (None si une manque)."""
    if source not in SOURCES_ACCEPTEES:
        raise AttributionRefusee(f"source {source!r} refusée : seuls les coupons individuels sont suivis (le vote collectif n'est jamais attribué)")
    cle = modele_canonique(modele)
    if not selections:
        raise ValueError("coupon sans sélection")
    jambes = []
    for s in selections:
        if s.get("cote") is None or s.get("match_id") is None:
            raise ValueError("sélection sans cote ou sans match : refusée (rien n'est inventé)")
        jambes.append({"match_id": int(s["match_id"]), "marche": str(s["marche"]), "selection": str(s["selection"]),
                       "handicap": s.get("handicap"), "cote": float(s["cote"]),
                       "proba_pct": None if s.get("proba_pct") is None else float(s["proba_pct"]), "resultat": "en_attente"})
    probas = [j["proba_pct"] for j in jambes]
    return {"protocole": protocole, "jour": str(jour), "modele": cle, "source": source, "run_id": run_id, "profil": profil,
            "cle_unique": empreinte(jambes), "cote_totale": round(math.prod(j["cote"] for j in jambes), 2),
            "proba_combinee_pct": None if None in probas else round(100 * math.prod(p / 100 for p in probas), 2),
            "statut": "en_attente", "jambes": jambes, "couts": couts or {}}


def depuis_resultats_ombre(protocole, jour, resultats, run_id=None, catalogue_index=None):
    """Adaptateur : sortie de ombre.composer_ombre (liste de résultats par modèle) -> coupons individuels. Les entrées « base » ou inconnues
    sont ignorées et listées dans `ignores` (jamais attribuées). `catalogue_index` : {(match_id, marche, selection, handicap): proba_pct}."""
    coupons, ignores = [], []
    for r in resultats:
        try:
            cle = modele_canonique(r.get("modele"))
        except AttributionRefusee:
            ignores.append(r.get("modele"))
            continue
        couts = {k: r.get(k) for k in ("tokens_entree", "tokens_sortie", "cout_usd", "appels", "secondes", "erreur")}
        for c in r.get("coupons") or []:
            sels = []
            for s in c.get("selections") or []:
                p = s.get("pick") or s
                idx = (p.get("match_id"), p.get("marche"), p.get("selection"), p.get("handicap"))
                sels.append({"match_id": p.get("match_id"), "marche": p.get("marche"), "selection": p.get("selection"), "cote": p.get("cote"),
                             "handicap": p.get("handicap"), "proba_pct": p.get("proba_pct", (catalogue_index or {}).get(idx))})
            if sels:
                coupons.append(nouveau_coupon(protocole, jour, MODELES[cle]["ids"][0], c.get("profil") or "?", sels, run_id=run_id, couts=couts))
    return coupons, ignores


class Registre:
    """Registre en mémoire (sérialisable en JSON lignes) avec anti-doublons : (protocole, jour, modèle, profil, empreinte) est unique."""

    def __init__(self, coupons=None):
        self.coupons, self._cles = [], set()
        for c in coupons or []:
            self.ajouter(c)

    @staticmethod
    def _cle(c):
        return (c["protocole"], c["jour"], c["modele"], c["profil"], c["cle_unique"])

    def ajouter(self, coupon):
        """Renvoie True si ajouté, False si doublon (ignoré, jamais compté deux fois)."""
        if coupon.get("source") not in SOURCES_ACCEPTEES:
            raise AttributionRefusee("source non individuelle")
        k = self._cle(coupon)
        if k in self._cles:
            return False
        self._cles.add(k)
        self.coupons.append(coupon)
        return True

    def enregistrer_resultats(self, resultats_jambes):
        """resultats_jambes : {match_id: {(marche, selection, handicap): resultat}} ; seules les jambes connues sont mises à jour. Renvoie le nb de jambes jugées."""
        n = 0
        for c in self.coupons:
            for j in c["jambes"]:
                r = (resultats_jambes.get(j["match_id"]) or {}).get((j["marche"], j["selection"], j["handicap"]))
                if r and r != "en_attente" and j["resultat"] == "en_attente":
                    j["resultat"] = r
                    n += 1
            c["statut"] = statut_coupon(c["jambes"])
        return n

    def vers_jsonl(self):
        return "\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in self.coupons)

    @classmethod
    def depuis_jsonl(cls, texte):
        return cls([json.loads(l) for l in texte.splitlines() if l.strip()])


def statut_coupon(jambes):
    """gagne : toutes gagnées ou neutralisées (push) avec au moins une gagnée ; perdu : au moins une perdue ; annule : tout neutralisé ;
    en_attente : une jambe non jugée sans perdante, ou une jambe « non_verifiable » (jamais présumée)."""
    res = [j["resultat"] for j in jambes]
    if "perdu" in res:
        return "perdu"
    if any(r in ("en_attente", "non_verifiable") for r in res):
        return "en_attente"
    if all(r == "push" for r in res):
        return "annule"
    return "gagne"


def cote_effective(coupon):
    """Cote réglée : push = 1, demi_gagne = 1 + (cote-1)/2 ; sinon cote de la jambe."""
    p = 1.0
    for j in coupon["jambes"]:
        if j["resultat"] == "push":
            continue
        p *= 1 + (j["cote"] - 1) / 2 if j["resultat"] == "demi_gagne" else j["cote"]
    return p


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(100 * max(0, c - h), 1), round(100 * min(1, c + h), 1))


def statistiques_modele(coupons):
    """Statistiques principales d'un modèle sur ses coupons RÉGLÉS (gagne/perdu) ; les autres sont comptés à part.
    Corrélation : grappes de coupons reliés par un match commun ; n_grappes = taille d'échantillon indépendant approchée."""
    reg = [c for c in coupons if c["statut"] in ("gagne", "perdu")]
    n = len(reg)
    out = {"n_total": len(coupons), "n_regles": n, "n_en_attente": sum(c["statut"] == "en_attente" for c in coupons),
           "n_annules": sum(c["statut"] == "annule" for c in coupons)}
    gag = [c for c in reg if c["statut"] == "gagne"]
    out["gagnes"] = len(gag)
    out["win_rate_pct"] = round(100 * len(gag) / n, 1) if n else None
    out["ic95_win_rate"] = wilson(len(gag), n)
    out["cote_moyenne"] = round(sum(c["cote_totale"] for c in reg) / n, 2) if n else None
    profit = sum((cote_effective(c) - 1) if c["statut"] == "gagne" else -1 for c in reg)
    out["profit_theorique"] = round(profit, 2) if n else None   # mise de 1 par coupon réglé
    out["roi_pct"] = round(100 * profit / n, 1) if n else None
    pr = [c for c in reg if c.get("proba_combinee_pct") is not None]
    out["n_avec_proba"] = len(pr)
    out["proba_annoncee_moy_pct"] = round(sum(c["proba_combinee_pct"] for c in pr) / len(pr), 1) if pr else None
    out["win_rate_pct_meme_ensemble"] = round(100 * sum(c["statut"] == "gagne" for c in pr) / len(pr), 1) if pr else None
    out["marches"] = _par_marche(reg)
    out["grappes"] = nb_grappes(reg)
    out["suffisant"] = n >= SEUIL_ECHANTILLON and out["grappes"] >= SEUIL_ECHANTILLON
    out["limites"] = _limites(out)
    return out


def _par_marche(reg):
    d = defaultdict(lambda: [0, 0])
    for c in reg:
        for j in c["jambes"]:
            if j["resultat"] in ("gagne", "perdu"):
                d[j["marche"]][0] += j["resultat"] == "gagne"
                d[j["marche"]][1] += 1
    return {m: {"jambes_jugees": n, "gagnees": k, "taux_pct": round(100 * k / n, 1), "ic95": wilson(k, n)} for m, (k, n) in sorted(d.items())}


def nb_grappes(coupons):
    """Nombre de composantes connexes de coupons reliés par un match commun (union-find) : un coupon isolé = une grappe."""
    parent = list(range(len(coupons)))

    def trouver(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    vu = {}
    for i, c in enumerate(coupons):
        for j in c["jambes"]:
            k = (c["jour"], j["match_id"])
            if k in vu:
                parent[trouver(i)] = trouver(vu[k])
            else:
                vu[k] = i
    return len({trouver(i) for i in range(len(coupons))})


def _limites(s):
    lim = []
    if s["n_regles"] < SEUIL_ECHANTILLON:
        lim.append(f"échantillon insuffisant : {s['n_regles']} coupon(s) réglé(s) < {SEUIL_ECHANTILLON}")
    if s["n_regles"] and s["grappes"] < s["n_regles"]:
        lim.append(f"observations corrélées : {s['n_regles']} coupons réglés mais {s['grappes']} grappe(s) indépendante(s) (matchs partagés)")
    if s["n_regles"] and s["n_avec_proba"] < s["n_regles"]:
        lim.append(f"probabilité absente pour {s['n_regles'] - s['n_avec_proba']} coupon(s) : non estimée")
    if s["n_en_attente"]:
        lim.append(f"{s['n_en_attente']} coupon(s) non réglé(s), exclus des statistiques")
    return lim


def stabilite_journaliere(coupons):
    """Win rate par jour (coupons réglés) : permet de voir si un résultat dépend d'une seule journée."""
    d = defaultdict(lambda: [0, 0])
    for c in coupons:
        if c["statut"] in ("gagne", "perdu"):
            d[c["jour"]][0] += c["statut"] == "gagne"
            d[c["jour"]][1] += 1
    return {j: {"reglés": n, "gagnés": k} for j, (k, n) in sorted(d.items())}


def comparer(registre):
    """Tableau comparatif des quatre modèles + verdict prudent. Aucun gagnant tant que l'un des quatre n'atteint pas le seuil."""
    par = {k: [] for k in MODELES}
    for c in registre.coupons:
        par[c["modele"]].append(c)
    stats = {k: statistiques_modele(v) for k, v in par.items()}
    insuff = [MODELES[k]["nom"] for k, s in stats.items() if not s["suffisant"]]
    verdict = ("AUCUN CLASSEMENT : échantillon insuffisant pour " + ", ".join(insuff)) if insuff else \
        "Échantillons suffisants : comparaison possible, avec intervalles de confiance (un écart doit les dépasser pour être retenu)."
    return {"modeles": stats, "stabilite": {k: stabilite_journaliere(v) for k, v in par.items()}, "verdict": verdict,
            "classement_autorise": not insuff}
