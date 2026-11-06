"""Suivi « en ombre » (06/11/2026) : (1) paris ÉCARTÉS par les agents de familles (veto Python / IA), jugés ensuite avec les
résultats réels pour savoir si ces écarts servent ; (2) comparaison de modèles IA payants (OpenRouter) sur le MÊME catalogue,
sans jamais rien envoyer sur Telegram, avec les tokens et le coût réels de chaque modèle.

Désactivé par défaut : la comparaison de modèles ne tourne que si MODELES_OMBRE (liste d'identifiants OpenRouter séparés par des
virgules) est renseignée ; « base » = le modèle actuel (DeepSeek, sans mesure de coût). Plafond de dépense par run :
OMBRE_BUDGET_USD (défaut 1.50) ; nombre de tours de correction : OMBRE_NB_TOURS (défaut 2) ; durée totale maximale :
OMBRE_DUREE_MAX_S (défaut 360) ; effort de raisonnement demandé aux modèles : OMBRE_RAISONNEMENT (low/medium/high, défaut medium)."""

import math
import os
import threading
import time

import requests

import agent_strategie as st
import agents_familles
import analyser_et_envoyer as ae

URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


def modeles_ombre():
    return [m.strip() for m in (os.getenv("MODELES_OMBRE") or "").split(",") if m.strip() and m.strip().lower() != "aucun"]


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
    """Appelable (prompt, max_tokens, json_attendu) pour composer_coupons ; cumule tokens et coût réels (usage OpenRouter).
    Borné dans le temps (échéance absolue + délai par appel) et dans l'effort de raisonnement (OMBRE_RAISONNEMENT, défaut medium) :
    le 06/11/2026, des appels séquentiels à des modèles de raisonnement ont tenu le pipeline plus de 15 minutes."""

    def __init__(self, modele, cle, budget_usd, poster=requests.post, echeance=None, delai_appel=150):
        self.modele, self.cle, self.budget_usd, self.poster = modele, cle, budget_usd, poster
        self.echeance, self.delai_appel = echeance, delai_appel
        self.tokens_entree = self.tokens_sortie = self.appels = 0
        self.cout_usd = 0.0
        self.erreurs = []   # composer_coupons avale les exceptions : on garde la dernière cause pour le rapport

    def _poster(self, prompt, max_tokens, avec_raisonnement):
        restant = (self.echeance - time.time()) if self.echeance is not None else self.delai_appel
        if restant <= 5:
            raise TimeoutError(f"échéance de comparaison dépassée pour {self.modele}")
        corps = {"model": self.modele, "messages": [{"role": "user", "content": prompt}],
                 "max_tokens": max_tokens, "usage": {"include": True}}
        effort = os.getenv("OMBRE_RAISONNEMENT") or "medium"
        if avec_raisonnement and effort != "aucun":
            corps["reasoning"] = {"effort": effort}
        return self.poster(URL_OPENROUTER, timeout=min(self.delai_appel, restant),
                           headers={"Authorization": f"Bearer {self.cle}", "Content-Type": "application/json"}, json=corps)

    def __call__(self, prompt, max_tokens=3000, json_attendu=False):
        try:
            return self._appeler(prompt, max_tokens)
        except Exception as e:
            self.erreurs.append(f"{type(e).__name__}: {str(e)[:180]}")
            raise

    def _appeler(self, prompt, max_tokens):
        if self.cout_usd >= self.budget_usd:
            raise BudgetEpuise(f"plafond de {self.budget_usd:g} $ atteint pour {self.modele}")
        r = self._poster(prompt, max_tokens, True)
        if getattr(r, "status_code", 200) == 400:   # paramètre de raisonnement refusé par ce fournisseur : on réessaie sans
            r = self._poster(prompt, max_tokens, False)
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


def _composer_un_modele(modele, pool, profils, catalogue, catalogue_texte, cle, appel_base, budget_usd, nb_tours, echeance, sortie):
    t0 = time.time()
    mesure = None
    try:
        if modele == "base":
            appel = appel_base or ae.appel_llm
        else:
            if not cle:
                sortie[modele] = {"modele": modele, "erreur": "OPENROUTER_API_KEY absente", "coupons": []}
                return
            appel = mesure = AppelOpenRouter(modele, cle, budget_usd, echeance=echeance)
        try:
            resultat = st.composer_coupons(pool, profils, appel=appel, nb_tours=nb_tours, catalogue_pret=(catalogue, catalogue_texte),
                                           controle_budget=False)
            erreur = None
        except Exception as e:
            resultat, erreur = None, f"{type(e).__name__}: {str(e)[:200]}"
        coupons = []
        if resultat:
            par_cle = {p["cle"]: p for p in profils}
            for cle_p, v in resultat["coupons"].items():
                coupons.append(_resume_coupon(cle_p, par_cle[cle_p], v["selections"]))
        if erreur is None and not coupons:   # explication plutôt qu'un silence : dernière erreur d'appel, sinon rejet par Python
            if mesure is not None and mesure.erreurs:
                erreur = "appel(s) en échec : " + mesure.erreurs[-1]
            elif mesure is not None and mesure.appels:
                erreur = f"aucun coupon valide après {mesure.appels} appel(s) (règles de Python non respectées)"
            else:
                erreur = "aucun appel effectué"
        sortie[modele] = {"modele": modele, "erreur": erreur, "coupons": coupons, "secondes": round(time.time() - t0),
                          "tokens_entree": getattr(mesure, "tokens_entree", None), "tokens_sortie": getattr(mesure, "tokens_sortie", None),
                          "cout_usd": round(mesure.cout_usd, 4) if mesure else None, "appels": getattr(mesure, "appels", None)}
    except Exception as e:   # jamais de fil muet : un résultat d'erreur est toujours écrit
        sortie[modele] = {"modele": modele, "erreur": f"{type(e).__name__}: {str(e)[:200]}", "coupons": []}


def composer_ombre(pool, profils, catalogue, catalogue_texte, modeles=None, cle=None, appel_base=None,
                   budget_usd=None, nb_tours=None, duree_max_s=None):
    """Compose les coupons avec chaque modèle sur le même catalogue, EN PARALLÈLE et dans une durée totale bornée
    (OMBRE_DUREE_MAX_S, défaut 360 s) : un modèle qui n'a pas fini à l'échéance est enregistré en erreur « délai dépassé »
    sans bloquer le pipeline (fils daemon). Renvoie une liste de résultats par modèle, dans l'ordre demandé."""
    modeles = modeles if modeles is not None else modeles_ombre()
    cle = cle or os.getenv("OPENROUTER_API_KEY")
    budget_usd = budget_usd if budget_usd is not None else float(os.getenv("OMBRE_BUDGET_USD") or 1.5)
    nb_tours = nb_tours or int(os.getenv("OMBRE_NB_TOURS") or 2)
    duree_max_s = duree_max_s if duree_max_s is not None else float(os.getenv("OMBRE_DUREE_MAX_S") or 360)
    echeance = time.time() + duree_max_s
    sortie, fils = {}, []
    for modele in modeles:
        t = threading.Thread(target=_composer_un_modele, daemon=True, name=f"ombre-{modele}",
                             args=(modele, pool, profils, catalogue, catalogue_texte, cle, appel_base, budget_usd, nb_tours, echeance, sortie))
        t.start()
        fils.append(t)
    for t in fils:
        t.join(max(0.0, echeance - time.time()))
    resultats = []
    for modele in modeles:
        resultats.append(sortie.get(modele) or {"modele": modele, "coupons": [],
                                                 "erreur": f"délai dépassé ({duree_max_s:g} s) : composition abandonnée"})
    return resultats
