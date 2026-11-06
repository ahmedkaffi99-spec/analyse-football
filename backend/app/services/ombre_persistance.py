"""Persistance et rapport du suivi « en ombre » (06/11/2026) : paris écartés par les agents de familles et coupons de modèles
IA comparés. Rien ici n'est envoyé sur Telegram ni compté dans les bilans réels."""

import os
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select

from app.models import CouponOmbre, Jambe, JambeOmbre
from app.services import pipeline
from app.services.verification import verifier_jambes


def _jambe_depuis_candidat(coupon, c, raison=None, index=None):
    pick = c["pick"]
    index = index or {}
    fixture_id = c.get("fixture_id_oddspapi")
    coupon.jambes.append(JambeOmbre(
        match=index.get(fixture_id) or index.get(c.get("match")), libelle_match=c.get("match") or "?",
        domicile=c.get("home_nom"), fixture_id_oddspapi=fixture_id, categorie=pick["categorie"], marche=pick["marche"],
        handicap=pick.get("handicap"), selection=str(pick["selection"]), cote=float(pick["cote"]),
        proba_modele_pct=pick.get("proba_modele_pct"), edge_pct=pick.get("edge_pct"), raison=raison))


def enregistrer_ecartes(db, run, jour, ecartes, index=None):
    """Un coupon fantôme par origine (ecartes_veto / ecartes_ia) ; chaque pari écarté une seule fois."""
    par_origine = defaultdict(dict)
    for e in ecartes or []:
        c = e["candidat"]
        pick = c["pick"]
        cle = (c.get("match"), pick["marche"], str(pick["selection"]))
        par_origine[e["origine"]].setdefault(cle, e)
    crees = 0
    for origine, paris in par_origine.items():
        coupon = CouponOmbre(run_id=run.id, jour=jour, modele="ecartes_veto" if origine == "veto_python" else "ecartes_ia",
                             profil="ecartes")
        for e in paris.values():
            _jambe_depuis_candidat(coupon, e["candidat"], raison=e.get("raison"), index=index)
            crees += 1
        db.add(coupon)
    db.flush()
    return crees


def enregistrer_comparaison(db, run, jour, resultats, index=None):
    for r in resultats:
        db.add(CouponOmbre(run_id=run.id, jour=jour, modele=r["modele"], profil="_resume", statut="resume",
                           tokens_entree=r.get("tokens_entree"), tokens_sortie=r.get("tokens_sortie"),
                           cout_usd=r.get("cout_usd"), erreur=r.get("erreur")))
        for k in r.get("coupons", []):
            coupon = CouponOmbre(run_id=run.id, jour=jour, modele=r["modele"], profil=k["profil"],
                                 cote_totale=k["cote_totale"], dans_la_bande=k["dans_la_bande"])
            for s in k["selections"]:
                _jambe_depuis_candidat(coupon, s, raison=s.get("raison_ia"), index=index)
            db.add(coupon)
    db.flush()


def executer_ombre(db, run, jour, ombre, index):
    """Appelé après l'envoi des coupons réels ; ne doit JAMAIS faire échouer un run."""
    try:
        n = enregistrer_ecartes(db, run, jour, ombre.get("ecartes"), index)
        print(f"🕶️ Ombre : {n} pari(s) écarté(s) par les agents de familles enregistrés pour jugement.")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"ℹ️ Suivi des paris écartés impossible : {str(e)[:120]}")
    try:
        _, _, _ = pipeline.modules()
        import ombre as ombre_ia
        modeles = ombre_ia.modeles_ombre()
        if modeles and ombre.get("catalogue"):
            print(f"🕶️ Comparaison en ombre : {', '.join(modeles)}")
            resultats = ombre_ia.composer_ombre(ombre["pool"], ombre["profils"], ombre["catalogue"], ombre["catalogue_texte"], modeles)
            enregistrer_comparaison(db, run, jour, resultats, index)
            db.commit()
            for r in resultats:
                print(f"   • {r['modele']} : {len(r['coupons'])} coupon(s), coût {r.get('cout_usd')} $, erreur {r.get('erreur')}")
    except Exception as e:
        db.rollback()
        print(f"ℹ️ Comparaison de modèles impossible : {str(e)[:160]}")


def juger_ombre(db):
    """Juge les jambes en ombre avec les résultats réels (même juge que les coupons réels)."""
    jambes = list(db.scalars(select(JambeOmbre).where(JambeOmbre.resultat == "en_attente")))
    return verifier_jambes(db, jambes) if jambes else {}


def _taux(jambes):
    jugees = [j for j in jambes if j.resultat in ("gagne", "perdu")]
    if not jugees:
        return None
    g = sum(j.resultat == "gagne" for j in jugees)
    return {"n": len(jugees), "gagnees": g, "reussite_pct": round(100 * g / len(jugees), 1),
            "annoncee_pct": round(sum(j.proba_modele_pct or 0 for j in jugees) / len(jugees), 1),
            "roi_pct": round(100 * sum((j.cote - 1) if j.resultat == "gagne" else -1 for j in jugees) / len(jugees), 1)}


def rapport(db, jours=30):
    """Texte du rapport : (1) écartés contre gardés ; (2) comparaison des modèles (réussite, bande, tokens, coût)."""
    depuis = date.today() - timedelta(days=jours)
    lignes = [f"=== SUIVI EN OMBRE — {jours} derniers jours ==="]
    coupons = list(db.scalars(select(CouponOmbre).where(CouponOmbre.jour >= depuis)))
    lignes.append("\n--- 1) Paris ÉCARTÉS par les agents de familles (réussite réelle) contre paris GARDÉS dans les coupons réels ---")
    for modele in ("ecartes_veto", "ecartes_ia"):
        t = _taux([j for c in coupons if c.modele == modele for j in c.jambes])
        lignes.append(f"{modele:14s} : " + (f"{t['gagnees']}/{t['n']} gagnées = {t['reussite_pct']} % (annoncé {t['annoncee_pct']} %, "
                                            f"rendement {t['roi_pct']} %/jambe)" if t else "aucun pari jugé pour l'instant"))
    from app.models import Coupon
    gardes = list(db.scalars(select(Jambe).join(Coupon, Jambe.coupon_id == Coupon.id)
                             .where(Jambe.resultat.in_(("gagne", "perdu")), Coupon.jour >= depuis)))
    t = _taux(gardes)
    lignes.append(f"{'gardes (réels)':14s} : " + (f"{t['gagnees']}/{t['n']} gagnées = {t['reussite_pct']} % (annoncé {t['annoncee_pct']} %, "
                                                   f"rendement {t['roi_pct']} %/jambe)" if t else "—"))
    lignes.append("Lecture : si les paris écartés réussissent AUTANT que les gardés, l'écart n'apporte rien ; s'ils réussissent "
                  "nettement MOINS (écart > 6 points avec n >= 100), il est utile. Attention : population non identique.")
    lignes.append("\n--- 2) Comparaison de modèles IA (même catalogue, jamais envoyée) ---")
    par_modele = defaultdict(list)
    for c in coupons:
        if not c.modele.startswith("ecartes_"):
            par_modele[c.modele].append(c)
    if not par_modele:
        lignes.append("Aucune comparaison enregistrée (MODELES_OMBRE vide : désactivée).")
    for modele, cs in sorted(par_modele.items()):
        resumes = [c for c in cs if c.profil == "_resume"]
        reels = [c for c in cs if c.profil != "_resume"]
        jambes = [j for c in reels for j in c.jambes]
        t = _taux(jambes)
        dans = sum(1 for c in reels if c.dans_la_bande)
        jugees = [c for c in reels if c.jambes and all(j.resultat in ("gagne", "perdu") for j in c.jambes)]
        gagnes = sum(all(j.resultat == "gagne" for j in c.jambes) for c in jugees)
        cout = sum(c.cout_usd or 0 for c in resumes)
        tokens = sum((c.tokens_entree or 0) + (c.tokens_sortie or 0) for c in resumes)
        jours_n = len({c.jour for c in resumes}) or 1
        erreurs = sum(1 for c in resumes if c.erreur)
        lignes.append(f"{modele} : {len(reels)} coupon(s) composé(s), {dans} dans la bande ; jambes "
                      + (f"{t['gagnees']}/{t['n']} = {t['reussite_pct']} %" if t else "non jugées")
                      + f" ; coupons entièrement gagnés {gagnes}/{len(jugees)} ; coût {round(cout, 3)} $ "
                      f"({round(cout / jours_n, 3)} $/jour), {tokens} tokens ; {erreurs} erreur(s)")
    return "\n".join(lignes)
