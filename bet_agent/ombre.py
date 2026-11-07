"""Composition de coupons par des modèles OpenRouter (06/11/2026) : utilisée par le vote final (MODELES_VOTE) et par le mode « modèle seul »
(COMPOSITEUR_MODELE). Chaque modèle compose les profils sur le MÊME catalogue, avec les mêmes règles de Python ; les tokens et le coût réels
(usage OpenRouter) sont mesurés. Plafond de dépense : OMBRE_BUDGET_USD (défaut 1.50) ; tours de correction : OMBRE_NB_TOURS (défaut 2) ;
durée totale maximale : OMBRE_DUREE_MAX_S (défaut 360) ; effort de raisonnement : OMBRE_RAISONNEMENT (low/medium/high, défaut medium).
(Le suivi « en ombre » — paris écartés et comparaison enregistrée en base — a été retiré le 06/11/2026.)"""

import math
import os
import threading
import time

import requests

import agent_strategie as st
import budget_ia
import analyser_et_envoyer as ae

URL_OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"


class BudgetEpuise(Exception):
    pass


class AppelOpenRouter:
    """Appelable (prompt, max_tokens, json_attendu) pour composer_coupons ; cumule tokens et coût réels (usage OpenRouter).
    Borné dans le temps (échéance absolue + délai par appel) et dans l'effort de raisonnement (OMBRE_RAISONNEMENT, défaut medium) :
    le 06/11/2026, des appels séquentiels à des modèles de raisonnement ont tenu le pipeline plus de 15 minutes."""

    def __init__(self, modele, cle, budget_usd, poster=requests.post, echeance=None, delai_appel=150):
        self.modele, self.cle, self.budget_usd, self.poster = modele, cle, budget_usd, poster
        self.echeance, self.delai_appel = echeance, delai_appel
        self.tokens_entree = self.tokens_sortie = self.appels = self.appels_cout_estime = 0
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
        if self.budget_usd is not None and self.cout_usd >= self.budget_usd:
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
        cout, estime = budget_ia.cout_appel(usage, usage.get("cost"))   # Phase 4 : un coût inconnu n'est jamais gratuit
        self.cout_usd += cout
        self.appels_cout_estime += 1 if estime else 0
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
    rejets = []   # rejets de Python (règles non respectées), du dernier tour au premier
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
                                           controle_budget=False, diagnostic=rejets)
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
                erreur = f"aucun coupon valide après {mesure.appels} appel(s) ; rejets de Python : " + " | ".join(r[:140] for r in rejets[-3:])
            elif mesure is None:   # modèle actuel : appels non mesurés
                erreur = "aucun coupon valide (modèle actuel, appels non mesurés)" + ("; rejets : " + " | ".join(r[:140] for r in rejets[-3:]) if rejets else "")
            else:
                erreur = "aucun appel effectué"
        sortie[modele] = {"modele": modele, "erreur": erreur, "coupons": coupons, "secondes": round(time.time() - t0),
                          "tokens_entree": getattr(mesure, "tokens_entree", None), "tokens_sortie": getattr(mesure, "tokens_sortie", None),
                          "cout_usd": round(mesure.cout_usd, 4) if mesure else None, "appels": getattr(mesure, "appels", None)}
    except Exception as e:   # jamais de fil muet : un résultat d'erreur est toujours écrit
        sortie[modele] = {"modele": modele, "erreur": f"{type(e).__name__}: {str(e)[:200]}", "coupons": []}


def composer_ombre(pool, profils, catalogue, catalogue_texte, modeles=None, cle=None, appel_base=None,
                   budget_usd=None, nb_tours=None, duree_max_s=None, budgets_par_modele=None):
    """Compose les coupons avec chaque modèle sur le même catalogue, EN PARALLÈLE et dans une durée totale bornée
    (OMBRE_DUREE_MAX_S, défaut 360 s). budgets_par_modele (Phase 3) : plafond en $ propre à chaque modèle (répartition du budget journalier),
    qui remplace budget_usd pour ce modèle. Ce plafond est vérifié AVANT chaque appel : le dernier appel peut le dépasser légèrement
    (le dépassement est mesuré et signalé par budget_ia.bilan_couts, jamais silencieux) : un modèle qui n'a pas fini à l'échéance est enregistré en erreur « délai dépassé »
    sans bloquer le pipeline (fils daemon). Renvoie une liste de résultats par modèle, dans l'ordre demandé."""
    modeles = list(modeles or [])
    cle = cle or os.getenv("OPENROUTER_API_KEY")
    # Variable absente, vide ou « aucun » = aucune limite financière ; le coût reste mesuré.
    budget_usd = budget_usd if budget_usd is not None else budget_ia.lire_budget(os.getenv("OMBRE_BUDGET_USD"))
    nb_tours = nb_tours or int(os.getenv("OMBRE_NB_TOURS") or 2)
    duree_max_s = duree_max_s if duree_max_s is not None else float(os.getenv("OMBRE_DUREE_MAX_S") or 360)
    echeance = time.time() + duree_max_s
    sortie, fils = {}, []
    for modele in modeles:
        t = threading.Thread(target=_composer_un_modele, daemon=True, name=f"ombre-{modele}",
                             args=(modele, pool, profils, catalogue, catalogue_texte, cle, appel_base,
                                   (budgets_par_modele or {}).get(modele, budget_usd), nb_tours, echeance, sortie))
        t.start()
        fils.append(t)
    for t in fils:
        t.join(max(0.0, echeance - time.time()))
    resultats = []
    for modele in modeles:
        resultats.append(sortie.get(modele) or {"modele": modele, "coupons": [],
                                                 "erreur": f"délai dépassé ({duree_max_s:g} s) : composition abandonnée"})
    return resultats
