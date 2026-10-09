"""Analyse PURE (aucun appel réseau) des captures shadow_capture.py : couverture, écarts de
cotes, délai entre captures, consommation de quota — opère uniquement sur des objets déjà
en mémoire (Cotation/RequeteShadow), jamais sur une nouvelle requête.

Une paire n'est comparée que si (fixture couple, marché canonique, sélection, ligne) sont
IDENTIQUES des deux côtés — jamais un rapprochement approximatif (demande explicite)."""

from collections import defaultdict


def _cle_match(cotation):
    return (cotation.fixture_id_oddspapi, cotation.fixture_id_api_football)


def associer_matchs(cotations_oddspapi, cotations_api_football, correspondance_fixtures):
    """correspondance_fixtures : {fixture_id_oddspapi: fixture_id_api_football} — fournie par
    l'appelant (jamais déduite ici par ressemblance de nom d'équipe). Renvoie la liste de
    paires (cotation_oddspapi, cotation_api_football) dont le marché canonique, la sélection
    ET la ligne correspondent exactement ; les deux listes de côtes non appariées sont
    renvoyées séparément pour audit (jamais silencieusement perdues)."""
    paires, non_appariees_op, non_appariees_af = [], [], []
    index_af = defaultdict(list)
    for c in cotations_api_football:
        index_af[c.fixture_id_api_football].append(c)

    for c_op in cotations_oddspapi:
        fid_af = correspondance_fixtures.get(c_op.fixture_id_oddspapi)
        candidats = index_af.get(fid_af, []) if fid_af else []
        trouve = next((c_af for c_af in candidats
                      if c_af.marche == c_op.marche and c_af.selection == c_op.selection
                      and c_af.ligne == c_op.ligne), None)
        if trouve:
            paires.append((c_op, trouve))
        else:
            non_appariees_op.append(c_op)

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


def couverture_matchs(matchs_attendus, requetes_oddspapi, requetes_api_football):
    """matchs_attendus : liste de fixture_id_oddspapi visés. Un match est "couvert" par un
    fournisseur si sa requête a réussi (statut_http == 200, ou en tout cas aucune erreur) ET
    renvoyé au moins 1 marché brut."""
    reussies_op = {r.fixture_id for r in requetes_oddspapi if r.erreur is None and r.nb_marches_recus > 0}
    reussies_af = {r.fixture_id for r in requetes_api_football if r.erreur is None and r.nb_marches_recus > 0}
    total = len(matchs_attendus)
    return {
        "total_matchs_vises": total,
        "oddspapi_couverts": len(reussies_op), "oddspapi_taux": round(len(reussies_op) / total, 4) if total else None,
        "api_football_couverts": len(reussies_af), "api_football_taux": round(len(reussies_af) / total, 4) if total else None,
        "couverts_par_les_deux": len(reussies_op & reussies_af),
    }


def consommation_quota(requetes_oddspapi, requetes_api_football):
    """Compte RÉEL des appels effectués (une ligne par appel, succès ou échec) — jamais estimé."""
    return {"oddspapi_appels": len(requetes_oddspapi), "api_football_appels": len(requetes_api_football)}


def marches_par_match(requetes):
    return {str(r.fixture_id): r.nb_marches_recus for r in requetes}


def rapport_complet(mesures, requetes_oddspapi, requetes_api_football, matchs_attendus):
    return {
        "couverture": couverture_matchs(matchs_attendus, requetes_oddspapi, requetes_api_football),
        "quota": consommation_quota(requetes_oddspapi, requetes_api_football),
        "marches_par_match_oddspapi": marches_par_match(requetes_oddspapi),
        "marches_par_match_api_football": marches_par_match(requetes_api_football),
        "ecarts_par_seuil": repartition_par_seuil(mesures),
        "par_championnat": resume_par_championnat(mesures),
        "par_marche": resume_par_marche(mesures),
        "n_paires_comparees": len(mesures),
    }
