# Mémoire d'apprentissage — préparation de la régénération des 5 études mélangées

Établi le 07/11/2026. **Aucune étude n'a été modifiée, supprimée ni remplacée.**

## 0. Fichiers produits le 07/11 (lecture seule)

- `rapports/phase3/apercu_etudes_regeneration.md` : ancienne et nouvelle étude, côte à côte, pour les 5 jours (calcul réel du code, sans écriture).
- `rapports/phase3/sauvegardes/memoire_agent_instantane_lecture_2026-11-07.json` : instantané de lecture des 8 études (texte et empreintes). **Les textes des études 9 (24/10) et 12 (29/10) ne sont pas identiques octet pour octet** (espaces fines insécables d'origine non recopiables ; `contenu_exact: false`). Les six autres sont vérifiés par empreinte md5. Ce fichier n'est donc pas la sauvegarde de référence.
- **Sauvegarde de référence** : l'export JSON de l'application (`--exporter`) ou la copie SQL (`06`), à lancer par vous ou sur votre autorisation.

## 1. Sauvegarde des études originales (à faire avant toute régénération)

- **Sans écriture en base** : `python -m app.taches apprendre --exporter sauvegarde_memoire.json` copie les 8 études, avec leurs `stats`, dans un fichier JSON. Cette commande refuse d'écraser un fichier existant.
- **Dans la base** : `backend/migrations/phase3/06_sauvegarde_memoire.sql` crée une copie exacte (`memoire_agent_sauvegarde_20261107`). Elle demande votre autorisation, comme toute écriture.
- Je n'ai pas pu produire moi-même un export de cette copie, faute d'accès direct de ma session à la base. Les textes d'origine y restent intacts tant qu'aucun remplacement n'a lieu.

## 2. Recalcul : uniquement sur les coupons envoyés

- **Ce qui est exclu** : les coupons des runs d'essai ou non envoyés, déjà exclus dans le code depuis la Phase 2.
- **Aperçu sans écriture** : `python -m app.taches apprendre --apercu --jour 2026-11-04,2026-10-28,2026-10-25,2026-10-24,2026-10-23 [--sans-ia]` affiche, pour chaque jour, l'ancienne et la nouvelle étude. Aucune écriture en base.
- **Remplacement réel** : `--refaire --jour AAAA-MM-JJ`, un jour à la fois et seulement après votre validation de l'aperçu. Si aucun coupon envoyé n'est jugé ce jour-là, l'ancienne étude est conservée.

## 3. Anciennes et nouvelles conclusions (chiffres calculés par requêtes en lecture seule)

Les nouvelles valeurs sont les conclusions chiffrées du recalcul sur les seuls coupons envoyés, avec les jambes dédoublonnées comme dans le code. Le texte final sera produit par l'aperçu ci-dessus.

| Jour | Bilan des coupons — ancien | Bilan — nouveau (envoyés) | Perdus par UNE jambe — ancien → nouveau | Jambes jugées — ancien → nouveau | Fiabilité réelle — ancien → nouveau |
|---|---|---|---|---|---|
| **04/11** | 2 gagnés, 14 perdus sur 18 | **0 gagné, 3 perdus sur 3** | 8 → 1 | 48 → 17 (11 gagnées) | 70-80 % : 66,7 % → **64,3 %** (n = 14) |
| **28/10** | 0 gagné, 9 perdus sur 9 | 0 gagné, 3 perdus sur 3 | 3 → 2 | 56 → 25 (19 gagnées) | 60-70 % : 56,0 % → **63,6 %** ; 70-80 % : 71,0 % → **85,7 %** |
| **25/10** | 4 gagnés, 11 perdus sur 15 | **1 gagné, 5 perdus sur 6** | 2 → 0 | 82 → 47 (35 gagnées) | 70-80 % : 74,4 % → 72,0 % ; 80 % et plus : 82,4 % → 100 % (n = 4) |
| **24/10** | 0 gagné, 7 perdus sur 7 | 0 gagné, 5 perdus sur 5 | 0 → 0 | 58 → 49 (36 gagnées) | 70-80 % : 75,0 % → 72,7 % ; 60-70 % : 73,1 % → 76,0 % |
| **23/10** | 4 gagnés, 14 perdus sur 18 | **2 gagnés, 4 perdus sur 6** (+ 2 coupons vides, abstentions) | 4 → 3 | 120 → 35 (30 gagnées) | 70-80 % : 77,2 % → **84,8 %** (n = 33) |

Points notables :
- **04/11** : la leçon « 8 coupons perdus par une seule jambe » venait d'essais. Elle tombe à 1. Seul 1 « match piège » subsiste.
- **28/10** : la conclusion s'inverse sur la tranche 70-80 %, de « trop optimiste » (71 %) à « bien calibrée » (85,7 %), avec un échantillon de 14 jambes. Le texte actuel le présentait à tort comme un défaut.
- **23/10** : le modèle y paraît encore mieux calibré qu'indiqué, mais avec un effectif réduit (35 jambes).
- **Étude du 05/11** : saine, elle ne change pas (3 perdus sur 3, 19 jambes).
- **Études du 03/11 et du 29/10** : aucun coupon envoyé ce jour-là, donc rien à régénérer. Elles restent en base et sont déjà ignorées à la lecture.

Limite : sur la plupart de ces jours, l'effectif des coupons envoyés est faible (3 à 8 coupons). Les nouvelles conclusions sont donc plus fiables dans leur origine mais plus bruitées statistiquement. Le code applique déjà un échantillon minimum avant d'en tirer des leçons.
