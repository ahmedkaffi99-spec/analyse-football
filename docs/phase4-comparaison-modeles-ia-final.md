# Phase 4 — Rapport final : comparaison des quatre modèles IA (07/11/2026)

## Verdict
**Aucun modèle ne peut être recommandé comme pilote à ce stade.** Les données ne permettent pas de classement : le protocole de 10 jours (4.5) n'a pas pu être exécuté sous les restrictions de la mission (pas d'appel IA payant, pas de pipeline, pas d'écriture Supabase). Aucune donnée n'a été fabriquée.

## Sous-phases
| | Statut |
|---|---|
| 4.1 Audit | Terminé : `docs/phase4-1-audit-suivi-modeles.md` |
| 4.2 Architecture | Terminée : `docs/phase4-2-architecture-suivi-individuel.md` |
| 4.3 Implémentation | Code terminé (`suivi_modeles.py`, `protocole_comparatif.py`) ; **persistance SQL préparée, non exécutée** (autorisation requise) |
| 4.4 Tests | Terminé : 37 tests (`test_suivi_modeles.py`), 306 tests backend verts |
| 4.5 Protocole 10 jours | Préparé, **non exécuté** : `docs/phase4-5-protocole-10-jours.md` |
| 4.6 Analyse | Outils prêts (`comparer`) ; analyse limitée aux données historiques ci-dessous |
| 4.7 Rapport | Ce document |

## Tableau comparatif (coupons réglés attribuables avec preuve, au 07/11/2026)
| | DeepSeek Flash 4.1 | GPT-6.1-Sol | Claude Sonnet 5.5 | Gemini Argon 4 |
|---|---|---|---|---|
| Coupons réglés | 15 | 5 | 0 | 0 |
| Gagnés | 1 | 0 | – | – |
| Win rate | 6,7 % (IC 95 % : 1,2–29,8 %) | 0 % (IC 95 % : 0–43,4 %) | non calculable | non calculable |
| Profit théorique (mise 1) | −10,76 | −5,00 | – | – |
| ROI théorique | −71,7 % | −100 % | – | – |
| Coupons en attente (exclus) | 3 (attribution non prouvée) | 9 | 0 | 4 |
| Échantillon ≥ 30 | non (15) | non (5) | non (0) | non (0) |
| Marchés, erreurs récurrentes, stabilité | non analysables : trop peu d'observations | idem | – | – |

Chiffres DeepSeek repris du rapport `docs/phase4-comparaison-modeles-ia.md` (calcul antérieur) ; GPT : 5 coupons perdus donc −5,00 par construction, IC 95 % de Wilson calculé pour 0/5. DeepSeek a été jugé sous d'anciennes règles, GPT sur un seul jour.

## Limites
- Échantillons très inférieurs à 30 ; aucune comparaison valide entre modèles.
- DeepSeek et GPT n'ont pas été testés sur les mêmes matchs ni les mêmes périodes.
- Observations corrélées : mêmes matchs dans plusieurs coupons (les grappes sont calculées par le code, sur données réelles).
- Les modèles choisissent des jambes ; les probabilités viennent du catalogue Python.
- `coupons_ombre.jour` est le jour du run : à recouper avec la date des matchs.
- 5 doublons de jambes, 41 jambes réelles sans match, 103 sans probabilité dans les données existantes.

## Opérations en attente (autorisations nécessaires)
1. Exécuter `backend/migrations/phase4/01_suivi_modeles_PRET_NON_EXECUTE.sql` (Supabase).
2. Autoriser un budget d'appels IA (~10 $ indicatifs pour 10 jours) et un déclenchement manuel sans Telegram.
3. Enregistrer le pilote dans le journal de chaque run (modification du pipeline).
4. Rejuger les coupons du 07/11 après les matchs, puis exécuter le protocole.

## Recommandation
Aucun modèle pilote n'est désigné. Conserver le pilote actuel, ne rien changer en production, et refaire la décision à l'issue du protocole, sur 30 coupons réglés par modèle au minimum, avec intervalles de confiance.
