# Migrations Phase 3 — NON EXÉCUTÉES (préparées le 06/11/2026)

Aucun de ces fichiers n'a été lancé. Ordre prévu, chacun après autorisation expresse :

1. `01_verifications_prealables.sql` — SELECT seulement ; chaque requête doit renvoyer 0 ligne (sauf la dernière, informative).
2. `02_correction_doublon_matchs.sql` — supprime UN match en double du run 2 (sans cote ni jambe) ; sauvegarde de la ligne : `rapports/phase3/sauvegardes/match_21_doublon_run2.json` et `..._restauration.sql`.
3. `03_contraintes_unicite.sql` — crée les index uniques (coupons, jambes, matchs, plans, mémoire). Transaction unique : tout ou rien.
4. `04_corrections_proposees_NON_RECOMMANDEES_SANS_REVUE.sql` — correction d'heures de coup d'envoi (250 matchs) : proposition, à relire.
5. `05_correction_heures_250_liste_figee.sql` — liste figée des 250 corrections d'heures (transaction annulée par défaut) ; détail dans `rapports/phase3/corrections_heures_250.csv`.
5b. `05b_correction_heures_180_confiance_forte.sql` — variante prudente : les 180 corrections de confiance forte seulement.
6. `06_sauvegarde_memoire.sql` — copie de `memoire_agent` avant régénération.
7. `99_annulation.sql` — supprime les index créés par le fichier 03.

Points d'attention (voir `rapports/phase3/rapport_donnees_historiques.md`) :
- pas d'index unique sur `cotes` : 0 doublon aujourd'hui, mais l'index ajouterait ~40-50 Mo à une base déjà proche de sa limite ;
- l'unicité des plans est PARTIELLE (un seul plan non clos par run) car le code remplace seulement les plans non clos ;
- l'application ne produit aucun doublon dans son usage normal (testé : `backend/tests/test_migrations_unicite.py`). Seul un profil manuel dont deux coupons auraient la même clé (`profils_json`) violerait `uq_coupons_run_profil` : l'erreur surviendrait après l'envoi, le run serait alors marqué `[APRES_ENVOI]` et jamais renvoyé (Phase 2), mais ses coupons ne seraient pas enregistrés.
