# Comparaison des modèles IA (suivi en ombre) et plan d'utilisation

Enregistré le 06/11/2026. Résultats réels des jambes : à compléter après les matchs du 07/11 (`apprentissage.yml` puis `rapport-ombre`).

## Run de comparaison (DB run 269, 4 modèles, même catalogue, rien envoyé)

| Modèle | Coupons | Tokens entrée / sortie | Coût |
|---|---|---|---|
| base (modèle actuel) | 0 (appels non mesurés) | - | - |
| Claude Sonnet 5.5 | 0/3 (règles de Python non respectées) | 129 754 / 6 380 | 0,32 $ |
| GPT-6.1 Sol | 3/3 : 5,12 · 12,91 · 21,73 | 90 050 / 5 996 | 0,29 $ |
| Gemini 4 Argon | 1/3 (coupon3 : 27,04) | 98 873 / 4 798 | 0,25 $ |

## DeepSeek (coupons 356-358, envoyés) contre GPT-6.1 Sol (ombre)

| | Coupon 1 | Coupon 2 | Coupon 3 |
|---|---|---|---|
| DeepSeek | 5,29 · 4 jambes · 20,2 % | 12,50 · 4 jambes · 8,8 % | 21,84 · 3 jambes · 5,9 % |
| GPT-6.1 Sol | 5,12 · 4 jambes · 21,4 % | 12,91 · 5 jambes · 8,4 % | 21,73 · 5 jambes · 5,3 % |

Probabilités combinées approximatives (produit des jambes). Cotes de runs différents (262 et 269). Aucune différence nette avant les résultats.

## Décision

À titre provisoire, GPT-6.1 Sol est le meilleur candidat (seul à produire les 3 coupons, coût intermédiaire). Aucun changement de production avant la comparaison sur résultats réels : jambes gagnées, coupons gagnés, coût.
