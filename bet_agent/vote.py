"""Vote final entre modèles IA pour la composition des coupons (06/11/2026, demande : « chaque modèle fait les 3,
vote final »). Le pilote (DeepSeek) compose ses 3 coupons ; chaque modèle de MODELES_VOTE compose aussi les 3 sur le
même catalogue ; pour chaque profil de risque, Python garde le coupon valide qui correspond le mieux à ce profil (prudent : probabilité
combinée ; équilibré : valeur espérée ; risque : cote totale), sans jamais imposer de cote. Aucun pari ne peut figurer dans deux coupons du jour. Égalité : le pilote."""
import math
import os


def modeles_vote():
    return [m.strip() for m in (os.getenv("MODELES_VOTE") or "").split(",") if m.strip() and m.strip().lower() != "aucun"]


def proba_combinee(selections):
    return math.prod((float(s["pick"].get("proba_modele_pct") or 0.0) / 100.0) for s in selections) if selections else 0.0


def cote_combinee(selections):
    return math.prod(float(s["pick"].get("cote") or 1.0) for s in selections) if selections else 0.0


def score_vote(niveau, selections):
    """Critère de choix entre coupons VALIDES du même profil (07/11/2026, trois profils de risque ; l'IA n'a aucune cote cible) :
    prudent = probabilité combinée maximale ; équilibré = valeur espérée (probabilité × cote totale) ; risque = cote totale (gain potentiel) la plus haute.
    Le second terme départage les égalités par la probabilité. Profil sans niveau (personnalisé, ancien) : probabilité combinée seule."""
    proba = proba_combinee(selections)
    if niveau == "equilibre":
        return (proba * cote_combinee(selections), proba)
    if niveau == "risque":
        return (cote_combinee(selections), proba)
    return (proba, 0.0)


def cle_pari(sel):
    p = sel["pick"]
    return (sel.get("match"), p.get("marche"), p.get("selection"), p.get("handicap"))


def choisir(profils, retenus_pilote, resultats_modeles, nom_pilote="pilote"):
    """-> (resultats_profils, journal). resultats_profils : même forme que etat["resultats_profils"]."""
    sortie, journal, _ = choisir_detail(profils, retenus_pilote, resultats_modeles, nom_pilote)
    return sortie, journal


def choisir_detail(profils, retenus_pilote, resultats_modeles, nom_pilote="pilote"):
    """-> (resultats_profils, journal, gagnants). gagnants : {clé du profil: nom du modèle retenu} (Phase 3 : le gagnant est conservé)."""
    par_pilote = {r["profil"]["cle"]: r["selections"] for r in retenus_pilote}
    pris, matchs_pris, sortie, journal, gagnants = set(), set(), [], [], {}
    for profil in profils:
        cle = profil["cle"]
        candidats = []
        if par_pilote.get(cle):
            candidats.append((nom_pilote, par_pilote[cle]))
        for res in resultats_modeles:
            for c in res.get("coupons") or []:
                if c.get("profil") == cle and c.get("dans_la_bande") and c.get("selections"):
                    candidats.append((res["modele"], c["selections"]))
        interdit_match = not profil.get("match_repete_autorise")   # Phase 4 : un match dans un seul coupon (sauf ajustement de l'agent)
        libres = [(n, s) for n, s in candidats if not any(cle_pari(x) in pris or (interdit_match and x.get("match") in matchs_pris) for x in s)]
        choix = max(libres or candidats, key=lambda ns: score_vote(profil.get("niveau_risque"), ns[1]), default=None)  # max garde le 1er (pilote) à égalité
        if choix is None:
            sortie.append({"profil": profil, "selections": par_pilote.get(cle) or []})
            journal.append(f"{cle} : aucun candidat")
            continue
        nom, selections = choix
        gagnants[cle] = nom
        pris.update(cle_pari(x) for x in selections)
        matchs_pris.update(x.get("match") for x in selections)
        sortie.append({"profil": profil, "selections": selections})
        detail = " · ".join(f"{n} {proba_combinee(s) * 100:.1f}% (cote {cote_combinee(s):.1f})" for n, s in candidats)
        journal.append(f"{cle} : {nom} retenu ({detail})")
    return sortie, journal, gagnants
