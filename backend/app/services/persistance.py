"""Écriture en base des sorties du pipeline : donnees_collectees.json (matchs + cotes +
données d'équipe) et le(s) coupon(s) (format de generer_coupons ou de ticket_du_jour.json)."""

from datetime import date, datetime, timezone

from app.models import Coupon, Cote, Jambe, Match, Run


def parse_datetime(valeur):
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError:
        return None


def stats_combine(selections):
    """Même calcul que analyser_et_envoyer.calculer_stats_combine (produit des cotes et des
    probabilités), refait ici pour que l'import ne dépende pas du pipeline."""
    cote, proba = 1.0, 1.0
    for s in selections:
        cote *= s["pick"]["cote"]
        proba *= (s["pick"].get("proba_modele_pct") or 0) / 100
    return round(cote, 2), round(proba * 100, 1)


def enregistrer_collecte(db, run, donnees):
    """Crée les matchs et leurs cotes. Renvoie un index {fixture_id OddsPapi ou 'A vs B': Match}
    pour rattacher ensuite chaque jambe de coupon à son match."""
    index = {}
    for m in donnees.get("matchs", []):
        af = m.get("api_football") or {}
        demande = m.get("match_demande") or {}
        op = m.get("oddspapi") or {}
        match = Match(
            run=run,
            domicile=af.get("home_name") or demande.get("home") or "?",
            exterieur=af.get("away_name") or demande.get("away") or "?",
            ligue=af.get("league_name"),
            coup_envoi=parse_datetime(af.get("fixture_date")),
            fixture_id_oddspapi=op.get("fixture_id"),
            fixture_id_api_football=af.get("fixture_id_api_football"),
            donnees={cle: m.get(cle) for cle in ("stats_historiques", "understat_xg", "clubelo", "classement", "serper")},
        )
        for marche in op.get("tous_marches") or []:
            for s in marche.get("selections", []):
                match.cotes.append(Cote(
                    marche_id=str(marche.get("marche_id")), marche=marche.get("marche") or "",
                    handicap=marche.get("handicap"), periode=marche.get("periode"),
                    selection=str(s.get("selection")), cote=float(s.get("cote")),
                ))
        db.add(match)
        if match.fixture_id_oddspapi:
            index[match.fixture_id_oddspapi] = match
        index[f"{match.domicile} vs {match.exterieur}"] = match

    run.nb_matchs = donnees.get("nb_matchs_demandes", len(donnees.get("matchs", [])))
    run.nb_matchs_avec_marches = donnees.get("nb_matchs_avec_marches", 0)
    run.nb_marches = donnees.get("nb_marches_total", 0)
    db.flush()
    return index


def enregistrer_coupons(db, run, resultats_profils, index_matchs=None, textes=None, jour=None):
    """resultats_profils : liste de {"profil": {cle, nom, cote_min, cote_max}, "selections": [...]},
    le format renvoyé par analyser_et_envoyer.generer_coupons. textes[i] = ticket rédigé
    pour le profil i (même ordre, comme agent4_rediger_coupons)."""
    index_matchs = index_matchs or {}
    jour = jour or date.today()
    coupons = []
    for i, item in enumerate(resultats_profils):
        profil, selections = item["profil"], item["selections"]
        cote_totale, proba = stats_combine(selections) if selections else (None, None)
        coupon = Coupon(
            run=run, jour=jour, profil=profil["cle"], nom=profil["nom"],
            cote_min=profil.get("cote_min"), cote_max=profil.get("cote_max"),
            cote_totale=cote_totale, proba_combinee_pct=proba,
            texte=textes[i] if textes and i < len(textes) else None,
            statut="en_attente" if selections else "vide",
        )
        for s in selections:
            pick = s["pick"]
            fixture_id = s.get("fixture_id_oddspapi")
            coupon.jambes.append(Jambe(
                match=index_matchs.get(fixture_id) or index_matchs.get(s.get("match")),
                libelle_match=s.get("match") or "?", domicile=s.get("home_nom"),
                fixture_id_oddspapi=fixture_id, categorie=pick["categorie"], marche=pick["marche"],
                handicap=pick.get("handicap"), selection=str(pick["selection"]), cote=float(pick["cote"]),
                proba_modele_pct=pick.get("proba_modele_pct"), edge_pct=pick.get("edge_pct"),
                guide=pick.get("guide"), onglet=pick.get("onglet"),
            ))
        db.add(coupon)
        coupons.append(coupon)
    db.flush()
    return coupons


def importer_fichiers(db, collecte=None, ticket=None):
    """Importe les fichiers produits par le pipeline sur Termux (donnees_collectees.json et/ou
    ticket_du_jour.json) dans un run 'import'. Les deux peuvent être importés ensemble pour
    que les jambes soient rattachées à leurs matchs."""
    if not collecte and not ticket:
        raise ValueError("Rien à importer : fournir 'collecte' et/ou 'ticket'.")
    lance_le = parse_datetime((ticket or {}).get("genere_a")) or parse_datetime((collecte or {}).get("date_collecte"))
    run = Run(source="import", statut="termine", lance_le=lance_le or datetime.now(timezone.utc),
              termine_le=datetime.now(timezone.utc))
    db.add(run)
    index = enregistrer_collecte(db, run, collecte) if collecte else {}
    if ticket:
        profils = [{"profil": {"cle": p["cle"], "nom": p["nom"]}, "selections": p.get("selections") or []}
                   for p in ticket.get("profils", [])]
        jour = date.fromisoformat(ticket["date"]) if ticket.get("date") else None
        enregistrer_coupons(db, run, profils, index, jour=jour)
    db.commit()
    return run
