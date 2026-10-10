"""Analyse PURE (aucun appel réseau) des captures shadow_capture.py : couverture, écarts de
cotes, délai entre captures, consommation de quota — opère uniquement sur des objets déjà
en mémoire (Cotation/RequeteShadow), jamais sur une nouvelle requête.

Une paire n'est comparée que si (fixture couple, marché canonique, sélection, ligne) sont
IDENTIQUES des deux côtés — jamais un rapprochement approximatif (demande explicite)."""

from collections import Counter, defaultdict


def cle_canonique(cotation):
    """(marché canonique, sélection, ligne) — jamais le nom brut ni une ressemblance de nom.
    La période (mi-temps/match entier) n'est pas un champ séparé de cette clé : chaque
    catégorie canonique (ex: BUTS_TOTAL) est déjà spécifique au temps réglementaire — un
    marché de mi-temps reste "non_mappe" (voir shadow_capture.py), jamais confondu."""
    return (cotation.marche, cotation.selection, cotation.ligne)


def detecter_doublons(cotations):
    """{cle_canonique: n} pour n > 1 — plusieurs cotations identiques (même marché/sélection/
    ligne) pour le MÊME appel sont un doublon à signaler explicitement, jamais sommées ou
    moyennées silencieusement."""
    compte = Counter(cle_canonique(c) for c in cotations)
    return {cle: n for cle, n in compte.items() if n > 1}


def associer_matchs(cotations_oddspapi, cotations_api_football, correspondance_fixtures):
    """correspondance_fixtures : {fixture_id_oddspapi: fixture_id_api_football} — fournie par
    l'appelant (jamais déduite ici par ressemblance de nom d'équipe). Renvoie la liste de
    paires (cotation_oddspapi, cotation_api_football) dont la clé canonique (marché, sélection,
    ligne) correspond EXACTEMENT ; les deux listes de côtes non appariées sont renvoyées
    séparément pour audit (jamais silencieusement perdues). Si un doublon existe côté
    API-Football pour une clé donnée, la paire n'est PAS formée (ambiguïté réelle, jamais
    résolue au hasard) — ce candidat reste dans les deux listes "non appariées"."""
    paires, non_appariees_op, non_appariees_af = [], [], []
    index_af = defaultdict(list)
    for c in cotations_api_football:
        index_af[c.fixture_id_api_football].append(c)

    for c_op in cotations_oddspapi:
        fid_af = correspondance_fixtures.get(c_op.fixture_id_oddspapi)
        candidats = index_af.get(fid_af, []) if fid_af else []
        trouves = [c_af for c_af in candidats if cle_canonique(c_af) == cle_canonique(c_op)]
        if len(trouves) == 1:
            paires.append((c_op, trouves[0]))
        else:
            non_appariees_op.append(c_op)  # 0 correspondance, ou ambiguë (>1) -> jamais au hasard

    appariees_af = {id(p[1]) for p in paires}
    non_appariees_af = [c for c in cotations_api_football if id(c) not in appariees_af]
    return paires, non_appariees_op, non_appariees_af


def ecart(cote_oddspapi, cote_api_football):
    abs_diff = abs(cote_api_football - cote_oddspapi)
    rel_diff = abs_diff / cote_oddspapi if cote_oddspapi else None
    return abs_diff, rel_diff


def mesurer_ecarts(paires):
    """[{..., ecart_absolu, ecart_relatif, delai_secondes}] — un enregistrement par paire."""
    resultats = []
    for c_op, c_af in paires:
        abs_diff, rel_diff = ecart(c_op.cote, c_af.cote)
        delai = (c_af.recu_le_utc - c_op.recu_le_utc).total_seconds()
        resultats.append({
            "championnat": c_op.championnat, "match": f"{c_op.domicile} vs {c_op.exterieur}",
            "marche": c_op.marche, "selection": c_op.selection, "ligne": c_op.ligne,
            "cote_oddspapi": c_op.cote, "cote_api_football": c_af.cote,
            "ecart_absolu": round(abs_diff, 4), "ecart_relatif": round(rel_diff, 4) if rel_diff is not None else None,
            "delai_secondes": delai, "maj_api_utc": c_af.maj_api_utc,
        })
    return resultats


SEUILS_ECART = (0.01, 0.03, 0.05)


def repartition_par_seuil(mesures, seuils=SEUILS_ECART):
    """{seuil: n_au_dessus} — combien de paires dépassent chaque seuil d'écart relatif."""
    valides = [m for m in mesures if m["ecart_relatif"] is not None]
    return {f">{int(s * 100)}%": sum(1 for m in valides if m["ecart_relatif"] > s) for s in seuils}


def _grouper(mesures, cle):
    groupes = defaultdict(list)
    for m in mesures:
        groupes[cle(m)].append(m)
    return dict(groupes)


def resume_par_championnat(mesures):
    groupes = _grouper(mesures, lambda m: m["championnat"])
    return {champ: _resume_groupe(ms) for champ, ms in groupes.items()}


def resume_par_marche(mesures):
    groupes = _grouper(mesures, lambda m: m["marche"])
    return {marche: _resume_groupe(ms) for marche, ms in groupes.items()}


def _resume_groupe(mesures):
    rel = [m["ecart_relatif"] for m in mesures if m["ecart_relatif"] is not None]
    return {"n": len(mesures), "ecart_relatif_moyen": round(sum(rel) / len(rel), 4) if rel else None,
            "ecart_relatif_max": round(max(rel), 4) if rel else None, **repartition_par_seuil(mesures)}


def couverture_matchs(matchs_attendus, requetes_oddspapi, requetes_api_football, correspondance_fixtures=None):
    """matchs_attendus : liste de fixture_id_oddspapi visés. Un match est "couvert" par un
    fournisseur si sa requête a réussi (erreur is None) ET renvoyé au moins 1 marché brut.

    BUG CORRIGÉ le 10/10/2026 : "couverts_par_les_deux" comparait directement un fixture_id
    OddsPapi à un fixture_id API-Football — deux espaces d'identifiants totalement différents
    (ex: "id1000001772221292" vs 1557417), l'intersection était donc TOUJOURS vide, quelle que
    soit la couverture réelle. Nécessite maintenant correspondance_fixtures (le même mapping
    que associer_matchs) pour traduire les id OddsPapi vers l'espace API-Football avant de
    comparer. Sans ce mapping, "couverts_par_les_deux" reste None plutôt que de mentir."""
    correspondance_fixtures = correspondance_fixtures or {}
    reussies_op = {r.fixture_id for r in requetes_oddspapi if r.erreur is None and r.nb_marches_recus > 0}
    reussies_af = {r.fixture_id for r in requetes_api_football if r.erreur is None and r.nb_marches_recus > 0}
    total = len(matchs_attendus)

    reussies_op_traduits = {correspondance_fixtures.get(fid) for fid in reussies_op} - {None}
    couverts_deux = len(reussies_op_traduits & reussies_af) if correspondance_fixtures else None

    return {
        "total_matchs_vises": total,
        "oddspapi_couverts": len(reussies_op), "oddspapi_taux": round(len(reussies_op) / total, 4) if total else None,
        "api_football_couverts": len(reussies_af), "api_football_taux": round(len(reussies_af) / total, 4) if total else None,
        "couverts_par_les_deux": couverts_deux,
    }


def consommation_quota(requetes_oddspapi, requetes_api_football):
    """Compte RÉEL des appels effectués (une ligne par appel, succès ou échec) — jamais estimé."""
    return {"oddspapi_appels": len(requetes_oddspapi), "api_football_appels": len(requetes_api_football)}


def marches_par_match(requetes):
    return {str(r.fixture_id): r.nb_marches_recus for r in requetes}


def rapport_complet(mesures, requetes_oddspapi, requetes_api_football, matchs_attendus, correspondance_fixtures=None):
    return {
        "couverture": couverture_matchs(matchs_attendus, requetes_oddspapi, requetes_api_football, correspondance_fixtures),
        "quota": consommation_quota(requetes_oddspapi, requetes_api_football),
        "marches_par_match_oddspapi": marches_par_match(requetes_oddspapi),
        "marches_par_match_api_football": marches_par_match(requetes_api_football),
        "ecarts_par_seuil": repartition_par_seuil(mesures),
        "par_championnat": resume_par_championnat(mesures),
        "par_marche": resume_par_marche(mesures),
        "n_paires_comparees": len(mesures),
    }
