# Phase 4.1 — Audit du suivi des modèles IA (07/11/2026, lecture seule)

Méthode : requêtes `SELECT` sur Supabase (aucune écriture) et lecture du code. Détail complémentaire : `docs/phase4-comparaison-modeles-ia.md`.

## 1. Identifiants de modèles
| Modèle demandé | Identifiant dans le dépôt | Remarque |
|---|---|---|
| DeepSeek Flash 4.1 | `deepseek-flash` / `deepseek/deepseek-v4.1-flash` | pilote par défaut ; **non enregistré dans les journaux de run** |
| GPT-6.1-Sol | `openai/gpt-6.1-sol` | confirmé par l'utilisateur dans cette mission |
| Claude Sonnet 5.5 | `anthropic/claude-sonnet-5.5` | |
| Gemini Argon 4 | `google/gemini-4-argon` | |

## 2. Constats (chiffres du 07/11/2026)
- Tables : `runs` 272, `coupons` 378, `jambes` 2 212, `coupons_ombre` 42, `jambes_ombre` 719.
- **Aucune table dédiée au suivi individuel** : le modèle n'est enregistré que dans `coupons_ombre.modele` (suivi retiré du code le 06/11) et dans `journal.composition.modele` du run 271. Les coupons réels (`coupons`) n'ont **aucune colonne modèle**.
- `coupons_ombre.jour` vaut 2026-11-06 pour toutes les lignes : c'est le jour du run, **pas forcément le jour des matchs** ; la date des matchs doit passer par `jambes_ombre.match_id` → `matchs`. À vérifier avant toute agrégation par jour (le rapport du 07/11 parlait de coupons « pour le 07/11 » : ce point est donc à confirmer).
- Intégrité : 0 jambe orpheline (réelles et ombre) ; 0 doublon de coupon ombre ; **5 doublons de jambes** dans `jambes` (même coupon, match, marché, sélection) ; **41 jambes réelles et 245 jambes ombre sans match rattaché** (inutilisables pour le jugement) ; **103 jambes réelles sans probabilité** (non estimées, jamais remplacées) ; 0 jambe sans cote.
- Résultats de jambes : `gagne, perdu, push, demi_gagne, en_attente, non_verifiable` ; statuts de coupons : `gagne, perdu, en_attente, incertain, vide`.
- Les modèles IA ne produisent pas de probabilité propre : la probabilité d'une jambe vient du catalogue Python partagé. Leur « prédiction » est la **sélection**.
- Les entrées `base`, `ecartes_ia`, `ecartes_veto` de `coupons_ombre` ne sont pas des modèles.

## 3. Coupons réglés attribuables avec preuve
| Modèle | Coupons réglés | Gagnés | Preuve | En attente |
|---|---|---|---|---|
| DeepSeek | 15 (runs 212, 213, 223, 238, 257, 258) | 1 | journal d'agent + pilote par défaut | 3 (run 262, attribution non prouvée par le journal) |
| GPT-6.1-Sol | 5 (run 271 : 2 ; ombre run 270 : 3) | 0 | `composition.modele` / colonne `modele` | 9 (ombre) |
| Gemini Argon 4 | 0 | 0 | colonne `modele` | 4 |
| Claude Sonnet 5.5 | 0 | 0 | colonne `modele` | 0 coupon valide |

Les 5 coupons GPT portent sur la même journée et probablement des matchs communs : observations corrélées.

## 4. Conclusion de l'audit
Le suivi historique ne permet pas une comparaison fiable : pas de colonne modèle sur les coupons réels, attribution DeepSeek non prouvée avant le 25/10 et pour le run 262, échantillons de 15 / 5 / 0 / 0. Une architecture dédiée est nécessaire (4.2).
