"""Identification SEULE (0 cote, 0 appel /odds) de candidats sur les 5 grands championnats
pour la phase shadow OddsPapi vs API-Football — demande explicite du 09/10/2026 :
"Avant tout appel réseau [de cotes]... affiche la liste des matchs sélectionnés... N'effectue
aucune collecte réelle avant de présenter cette liste et d'obtenir une confirmation distincte."

Coût réel si exécuté avec --executer : EXACTEMENT 4 appels (1 OddsPapi /v4/fixtures + 3
API-Football /fixtures hier/aujourd'hui/demain, même fonction que la production,
cd.recuperer_fixtures_api_football) — AUCUN appel /odds, donc AUCUNE cote récupérée ici,
côté ni l'un ni l'autre fournisseur. Rien de ce fichier n'est importé par la production.

Sans --executer : 0 appel réseau, affiche seulement le plan.

Correspondance équipe -> fixture API-Football : réutilise cd.trouver_fixture_api_football
(même seuil de confiance que la production, cd.SEUIL_MATCH_ACCEPTABLE) — un match sans
correspondance fiable est exclu, jamais deviné."""

import argparse

import collecte_donnees as cd

# Les 5 grands championnats demandés explicitement (sous-ensemble de
# cd.LIGUES_DOMESTIQUES_MAJEURES, qui en contient 7) — format attendu par
# cd._correspond_au_filtre : [(mot_cle_tournoi, pays), ...].
PAYS_CINQ_GRANDS = ("england", "spain", "italy", "germany", "france")
CINQ_GRANDS_CHAMPIONNATS = [(kw, pays) for pays, kws in cd.LIGUES_DOMESTIQUES_MAJEURES.items()
                           if pays in PAYS_CINQ_GRANDS for kw in kws]


def _est_le_vrai_grand_championnat(fx):
    """Correspondance EXACTE (pas une sous-chaîne) du nom de tournoi — cd._correspond_au_filtre
    fait un simple "mot_cle in nom_tournoi", qui accepte à tort des compétitions mineures dont
    le nom CONTIENT le mot-clé (constaté réellement le 09/10/2026 : "Northern Premier League
    Premier", une ligue semi-professionnelle anglaise, matchait "premier league"). Les 5
    grands championnats ont un nom de tournoi OddsPapi exact et stable — jamais une variante
    à deviner."""
    nom_tournoi = (fx.get("tournamentName") or "").strip().lower()
    pays = (fx.get("categoryName") or "").strip().lower()
    return any(nom_tournoi == mot_cle and pays == pays_attendu
              for mot_cle, pays_attendu in CINQ_GRANDS_CHAMPIONNATS)


def identifier_candidats(fixtures_oddspapi, fixtures_api_football, max_par_championnat=1):
    """Pure (aucun appel réseau ici) : prend des listes déjà récupérées. Un candidat par
    championnat au maximum (le premier match Pre-Game avec cotes réelles ET une
    correspondance API-Football fiable), jamais plus sans le demander explicitement."""
    candidats = []
    pays_vus = set()
    for fx in fixtures_oddspapi:
        if not fx.get("hasOdds") or fx.get("statusName") != "Pre-Game":
            continue
        if not _est_le_vrai_grand_championnat(fx):
            continue
        pays = (fx.get("categoryName") or "").lower()
        if pays in pays_vus:
            continue
        home, away = fx.get("participant1Name"), fx.get("participant2Name")
        fx_af, score_af = cd.trouver_fixture_api_football(home, away, fixtures_api_football)
        if not fx_af:
            continue  # pas de correspondance fiable -> jamais une identification inventée
        donnees_af = cd._donnees_api_football(fx_af)
        candidats.append({
            "championnat": fx.get("tournamentName"), "pays": fx.get("categoryName"),
            "domicile": home, "exterieur": away,
            "fixture_id_oddspapi": fx.get("fixtureId"),
            "fixture_id_api_football": donnees_af.get("fixture_id_api_football"),
            "score_correspondance_af": round(score_af, 1),
            "coup_envoi_oddspapi": fx.get("startTime"),
            "coup_envoi_api_football": donnees_af.get("fixture_date"),
        })
        pays_vus.add(pays)
        if len(candidats) >= max_par_championnat * len(PAYS_CINQ_GRANDS):
            break
    return candidats


def executer_identification():
    print("1 appel OddsPapi /v4/fixtures...")
    fixtures_op = cd._telecharger_fixtures_oddspapi()
    print(f"   ✓ {len(fixtures_op)} fixtures OddsPapi chargées")
    print("3 appels API-Football /fixtures (hier/aujourd'hui/demain, même fonction que la production)...")
    fixtures_af = cd.recuperer_fixtures_api_football()

    candidats = identifier_candidats(fixtures_op, fixtures_af)
    print(f"\n{len(candidats)} candidat(s) identifié(s) (0 appel /odds effectué, 0 cote récupérée) :\n")
    for c in candidats:
        print(f"   [{c['championnat']}] {c['domicile']} vs {c['exterieur']}")
        print(f"      OddsPapi fixtureId={c['fixture_id_oddspapi']} (coup d'envoi {c['coup_envoi_oddspapi']})")
        print(f"      API-Football fixture={c['fixture_id_api_football']} "
              f"(correspondance {c['score_correspondance_af']}%, coup d'envoi {c['coup_envoi_api_football']})")
    return candidats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executer", action="store_true",
                        help="Sans ce drapeau : aucun appel réseau, affiche seulement le plan.")
    args = parser.parse_args()

    print("Plan (identification seule, 0 cote) : 1 appel OddsPapi /v4/fixtures + 3 appels "
          "API-Football /fixtures = 4 appels au total. 0 appel /odds (ni OddsPapi ni API-Football).")
    print(f"Championnats visés : {', '.join(sorted({p for _, p in CINQ_GRANDS_CHAMPIONNATS}))}")

    if not args.executer:
        print("\nAucun appel effectué (relancer avec --executer pour exécuter réellement ces "
              "4 appels d'identification, après autorisation explicite).")
        return
    executer_identification()


if __name__ == "__main__":
    main()
