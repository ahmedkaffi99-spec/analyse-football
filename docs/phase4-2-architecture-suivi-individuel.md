# Phase 4.2 / 4.3 — Architecture du suivi individuel

**Principe : une couche séparée, alimentée uniquement par des compositions individuelles.**
- `backend/app/services/suivi_modeles.py` (pur, sans réseau) : registre des 4 modèles (identifiants canoniques), construction de coupons individuels, refus de toute source autre qu'`individuel` (vote collectif, « base », modèle inconnu), anti-doublon par empreinte des sélections (indépendante de l'ordre et de la cote), règlement des coupons, statistiques (win rate + Wilson 95 %, ROI et profit théoriques à mise 1, cote moyenne, marchés, probabilité annoncée, grappes corrélées, stabilité par jour), garde « aucun classement sous 30 coupons réglés par modèle ».
- `backend/app/services/protocole_comparatif.py` : plan de 10 jours, empreinte du catalogue figé, contrôle d'équité (mêmes informations pour les quatre modèles), couverture et manques.
- Adaptateur `depuis_resultats_ombre` : branche la sortie de `ombre.composer_ombre` sans modifier ce module ni le pipeline.
- Persistance SQL préparée, **non exécutée** : `backend/migrations/phase4/01_suivi_modeles_PRET_NON_EXECUTE.sql` (tables `suivi_modeles_coupons` / `suivi_modeles_jambes`, contrainte `source = 'individuel'`, unicité anti-doublon, RLS activé). Elle exige une autorisation Supabase spécifique.
- Aucune modification de `main`, du pipeline, du cron, des tables existantes.

**Branchement futur (hors périmètre, nécessite autorisation)** : dans le pipeline, après `composer_ombre`, appeler `depuis_resultats_ombre` puis écrire dans les nouvelles tables ; enregistrer le pilote dans `journal.composition` pour chaque run.
