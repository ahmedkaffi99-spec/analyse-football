"""Suivi « en ombre » (06/11/2026) : (1) paris ÉCARTÉS par les agents de familles (veto Python / IA), jugés ensuite avec les
résultats réels pour savoir si ces écarts servent ; (2) comparaison de modèles IA payants (OpenRouter) sur le MÊME catalogue,
sans jamais rien envoyer sur Telegram, avec les tokens et le coût réels de chaque modèle.

Désactivé par défaut : la comparaison de modèles ne tourne que si MODELES_OMBRE (liste d'identifiants OpenRouter séparés par des
virgules) est renseignée ; « base » = le modèle actuel (DeepSeek, sans mesure de coût). Plafond de dépense par run :
OMBRE_BUDGET_USD (défaut 1.50) ; nombre de tours de correction : OMBRE_NB_TOURS (défaut 2)."""

import math
import os
import time

import requests

import agent_strategie as st
import agents_familles
import analyser_et_envoyer as ae

URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


def modeles_ombre():
    return [m.strip() for m in (os.getenv("MODELES_OMBRE") or "").split(",") if m.strip()]


def details_ecartes(catalogue, ecartes, avis):
    """Paris écartés, avec leur origine (veto Python déterministe ou avis de l'IA de famille) et leur raison."""
    sortie = []
    for cid in sorted(ecartes):
        c = catalogue.get(cid)
        if not c:
            continue
        pick = c["pick"]
        origine = "veto_python" if agents_familles.veto_python(pick) else "ia_famille"
        sortie.append({"id": cid, "origine": origine, "famille": agents_familles.famille_de(pick.get("categorie"))[1],
                       "raison": str(avis.get(cid, ""))[:200], "candidat": c})
    return sortie


class BudgetEpuise(Exception):
    pass


class AppelOpenRouter:
    """Appelable (prompt, max_tokens, json_attendu) pour composer_coupons ; cumule tokens et coût réels (usage OpenRouter)."""

    def __init__(self, modele, cle, budget_usd, poster=requests.post):
        self.modele, self.cle, self.budget_usd, self.poster = modele, cle, budget_usd, poster
        self.tokens_entree = self.tokens_sortie = self.appels = 0
        self.cout_usd = 0.0

    def __call__(self, prompt, max_tokens=3000, json_attendu=False):
        if self.cout_usd >= self.budget_usd:
            raise BudgetEpuise(f"plafond de {self.budget_usd:g} $ atteint pour {self.modele}")
        r = self.poster(URL_OPENROUTER, timeout=240,
                        headers={"Authorization": f"Bearer {self.cle}", "Content-Type": "application/json"},
                        json={"model": self.modele, "messages": [{"role": "user", "content": prompt}],
                              "max_tokens": max_tokens, "usage": {"include": True}})
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage") or {}
        self.appels += 1
        self.tokens_entree += int(usage.get("prompt_tokens") or 0)
        self.tokens_sortie += int(usage.get("completion_tokens") or 0)
        self.cout_usd += float(usage.get("cost") or 0.0)
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def _resume_coupon(cle, profil, selections):
    cote = math.prod(float(s["pick"]["cote"]) for s in selections) if selections else None
    borne_min, borne_max = profil.get("cote_totale_min"), profil.get("cote_totale_max")
    dans = (cote is not None and (borne_min is None or cote >= borne_min) and (borne_max is None or cote <= borne_max))
    return {"profil": cle, "cote_totale": round(cote, 2) if cote else None, "dans_la_bande": bool(dans),
            "selections": selections}


def composer_ombre(pool, profils, catalogue, catalogue_texte, modeles=None, cle=None, appel_base=None,
                   budget_usd=None, nb_tours=None):
    """Compose les coupons avec chaque modèle sur le même catalogue. Renvoie une liste de résultats par modèle."""
    modeles = modeles if modeles is not None else modeles_ombre()
    cle = cle or os.getenv("OPENROUTER_API_KEY")
    budget_usd = budget_usd if budget_usd is not None else float(os.getenv("OMBRE_BUDGET_USD") or 1.5)
    nb_tours = nb_tours or int(os.getenv("OMBRE_NB_TOURS") or 2)
    resultats = []
    for modele in modeles:
        t0 = time.time()
        if modele == "base":
            appel, mesure = (appel_base or ae.appel_llm), None
        else:
            if not cle:
                resultats.append({"modele": modele, "erreur": "OPENROUTER_API_KEY absente", "coupons": []})
                continue
            appel = mesure = AppelOpenRouter(modele, cle, budget_usd)
        try:
            sortie = st.composer_coupons(pool, profils, appel=appel, nb_tours=nb_tours, catalogue_pret=(catalogue, catalogue_texte))
            erreur = None
        except Exception as e:
            sortie, erreur = None, f"{type(e).__name__}: {str(e)[:200]}"
        coupons = []
        if sortie:
            par_cle = {p["cle"]: p for p in profils}
            for cle_p, v in sortie["coupons"].items():
                coupons.append(_resume_coupon(cle_p, par_cle[cle_p], v["selections"]))
        resultats.append({"modele": modele, "erreur": erreur, "coupons": coupons, "secondes": round(time.time() - t0),
                          "tokens_entree": getattr(mesure, "tokens_entree", None), "tokens_sortie": getattr(mesure, "tokens_sortie", None),
                          "cout_usd": round(mesure.cout_usd, 4) if mesure else None, "appels": getattr(mesure, "appels", None)})
    return resultats
