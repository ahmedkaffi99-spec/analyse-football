# Les cinq études finales — à valider avant tout remplacement (rien n'est écrit en base)

Produit le 07/11/2026. **Base inchangée** : `memoire_agent` conserve ses 8 études d'origine ; la sauvegarde de référence `memoire_agent_sauvegarde_20261107` est vérifiée (empreinte `a509b8a390bb2aea24065a4be59b7ee4`, restauration testée).

## Comment ces textes ont été produits

- **Partie calculée** (bilan des coupons, jambes tueuses, matchs pièges, jambes annoncées perdues) : le code de l'application (`apprentissage.lecons_deterministes`), sur les seuls coupons des runs envoyés (25 coupons, 210 jambes ; données dans `rapports/phase3/donnees_sources_apercu/`).
- **Paragraphe `LEÇONS`** : aucune clé d'IA n'est disponible dans cet environnement (DeepSeek, OpenRouter, Groq, Gemini absentes) et aucun appel payant n'a été fait. Les paragraphes ont été **rédigés par moi (Claude) dans cette session**, en suivant exactement la consigne de l'application : français, sans markdown, causes de chaque perte, règles chiffrées avec effectif `(n=…)` ≥ 3 (sinon « à surveiller »), une question à vérifier, aucune information inventée. Chaque chiffre cité a été recoupé avec les faits calculés.
- **Longueur** : les cinq textes tiennent entièrement dans la limite de 1 400 caractères de l'application, donc **aucun n'est tronqué** (les anciens l'étaient en plein mot).
- **À votre choix au moment du remplacement** : garder ces paragraphes, ou les faire régénérer par l'IA de l'application (un court appel par jour, compté dans le budget) à partir des mêmes faits.
- **Correction de l'incohérence statistique du 04/11 (07/11/2026)** : les 5 jambes du coupon 🔴 (run 257) n'ont ni probabilité ni edge enregistrés ; le code les comptait comme « 0 % annoncé », ce qui donnait une moyenne annoncée de 17,7 % pour la tranche de cote 1,50-2,00 et 47,2 % pour la catégorie Total. **Le code est corrigé** (`apprentissage.statistiques` : la moyenne annoncée ne porte que sur les jambes qui ont une probabilité ; les statistiques indiquent `sans_proba` et `jambes_sans_proba`) et testé ; l'étude du 04/11 est recalculée (tranche 1,50-2,00 : 70,9 % annoncé ; Total : 75,6 % ; 3 jambes jugées sans probabilité signalées ; la mention « annoncé None % » devient « probabilité non enregistrée »). Les quatre autres jours n'avaient aucune jambe sans probabilité : leurs textes et statistiques sont inchangés.

## 2026-11-04 (étude 15) — 1285 caractères

### Ancienne étude (base, tronquée à 1 400 caractères)
```
Bilan du jour : 2 coupon(s) gagné(s), 14 perdu(s) sur 18.
8 coupon(s) perdu(s) par UNE seule jambe (8 jambe(s) différente(s)) : PSV Eindhoven vs Club Brugge — Asian Handicap (0.0) 1 @2.23 (annoncé None %); Porto vs Napoli — Over Under Full Time (2.75) Under @2.72 (annoncé None %); Cardiff vs West Ham — Over Under Full Time (3.25) Under @2.007 (annoncé None %); Fenerbahçe vs Liverpool — Asian Handicap (1.0) 1 @1.38 (annoncé 70.2 %); Lens vs Como — Double Chance Full Time 2X @1.32 (annoncé 72.4 %). Une jambe de plus dans un coupon est une chance de plus de perdre.
Match piège : Cardiff vs West Ham — 4 jambes DIFFÉRENTES perdues (Double Chance Full Time 12; Over Under Full Time (3.25) Under; Over Under Full Time (4.5) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Fenerbahçe vs Liverpool — 3 jambes DIFFÉRENTES perdues (Asian Handicap (1.0) 1; Over Under Team 2 (2.5) Under; Over Under Team 1 (2.0) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Jambe annoncée à 77.4 % perdue : Viking vs Sabah FA — Asian Handicap (-2.5) 2 (dans 1 coupon(s)).
Jambe annoncée à 77.2 % perdue : Cardiff vs West Ham — Double Chance Full Time 12 (dans 1 coupon(s)).
Jambe annoncée à 77.1 % perdue : Cardiff vs West Ham — Double Chance Full Time 12 (dan
```

### Nouvelle étude finale proposée
```
Bilan du jour : 0 coupon(s) gagné(s), 3 perdu(s) sur 3.
1 coupon(s) perdu(s) par UNE seule jambe (1 jambe(s) différente(s)) : Bristol City vs Wolves — Over Under Full Time (2.5) Under @1.85 (annoncé probabilité non enregistrée). Une jambe de plus dans un coupon est une chance de plus de perdre.
Match piège : Cardiff vs West Ham — 2 jambes DIFFÉRENTES perdues (Double Chance Full Time 12; Over Under Full Time (4.5) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Jambe annoncée à 77.4 % perdue : Viking vs Sabah FA — Asian Handicap (-2.5) 2 (dans 1 coupon(s)).
Jambe annoncée à 77.2 % perdue : Cardiff vs West Ham — Double Chance Full Time 12 (dans 1 coupon(s)).
LEÇONS : 1) Les 3 coupons ont perdu : 🟢 sur 2 jambes (Viking AH -2,5 ; Cardiff DC 12), 🟠 sur 3 (Porto, PSV corners, Cardiff Under 4,5), 🔴 sur 1 (Bristol City Under 2,5). Cardiff-West Ham a fait perdre 2 paris différents. 2) Sur 17 jambes jugées, 14 ont une probabilité enregistrée : tranche 70-80 % = 9/14 réussies, 64,3 % pour 74,5 % annoncé (n=14) ; les compter vers 65 % dans la probabilité d'un coupon ; aucune règle tirée des 3 jambes sans probabilité. 3) Question : pourquoi les 5 jambes du coupon 🔴 n'ont ni probabilité ni edge enregistrés ?
```

Jambes jugées dans les statistiques enregistrées : 17 dont 3 sans probabilité enregistrée (coupons envoyés seulement).

## 2026-10-28 (étude 11) — 1103 caractères

### Ancienne étude (base, tronquée à 1 400 caractères)
```
Bilan du jour : 0 coupon(s) gagné(s), 9 perdu(s) sur 9.
3 coupon(s) perdu(s) par UNE seule jambe (3 jambe(s) différente(s)) : Bayern München vs 1. FC Magdeburg — Over Under Team 1 (5.0) Under @1.48 (annoncé 74.6 %); Bayern München vs 1. FC Magdeburg — Asian Handicap (-4.5) 2 @1.39 (annoncé 77.7 %); Bayern München vs 1. FC Magdeburg — Over Under Team 1 (4.5) Under @1.6 (annoncé 70.8 %). Une jambe de plus dans un coupon est une chance de plus de perdre.
Match piège : Bayern München vs 1. FC Magdeburg — 5 jambes DIFFÉRENTES perdues (Over Under Team 1 (5.0) Under; Over Under Full Time (5.5) Under; Asian Handicap (-4.5) 2) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Frosinone vs Lecce — 3 jambes DIFFÉRENTES perdues (Asian Handicap (-1.5) 2; Over Under Full Time (4.0) Under; Over Under Team 1 (2.5) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Guijuelo vs Sporting Gijon — 2 jambes DIFFÉRENTES perdues (Over Under Full Time (3.5) Under; Over Under Team 2 (2.5) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Monza vs Napoli — 2 jambes DIFFÉRENTES perdues (Asian Handicap (1.5) 1; Corners - Over Under Full Time (7.5) Over) : plusieurs p
```

### Nouvelle étude finale proposée
```
Bilan du jour : 0 coupon(s) gagné(s), 3 perdu(s) sur 3.
2 coupon(s) perdu(s) par UNE seule jambe (2 jambe(s) différente(s)) : Bayern München vs 1. FC Magdeburg — Asian Handicap (-4.5) 2 @1.39 (annoncé 77.7 %); Bayern München vs 1. FC Magdeburg — Over Under Team 1 (4.5) Under @1.6 (annoncé 70.8 %). Une jambe de plus dans un coupon est une chance de plus de perdre.
Match piège : Bayern München vs 1. FC Magdeburg — 3 jambes DIFFÉRENTES perdues (Asian Handicap (-4.5) 2; Over Under Team 1 (4.5) Under; Corners - Over Under Full Time (8.5) Over) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
LEÇONS : 1) Le même match, Bayern-Magdeburg, était dans les 3 coupons et les a fait tomber tous les 3 (n=3 coupons) par 3 paris différents (AH -4,5, Under équipe 1 4,5, corners 8,5) ; le 🔴 a perdu 3 autres jambes. 2) Tranche 70-80 % : 12/14 réussies, 85,7 % pour 74,0 % annoncé (n=14) ; tranche 60-70 % : 63,6 % pour 67,4 % (n=11). Corners : 3/5, à surveiller. 3) Question : le AH -4,5 et le Under équipe 1 4,5 racontaient-ils le même scénario ?
```

Jambes jugées dans les statistiques enregistrées : 25 (coupons envoyés seulement).

## 2026-10-25 (étude 10) — 1159 caractères

### Ancienne étude (base, tronquée à 1 400 caractères)
```
Bilan du jour : 4 coupon(s) gagné(s), 11 perdu(s) sur 15.
2 coupon(s) perdu(s) par UNE seule jambe (2 jambe(s) différente(s)) : Atalanta vs Frosinone — Over Under Full Time (5.5) Under @1.14 (annoncé 85.3 %); Atalanta vs Frosinone — Over Under Team 2 (2.0) Under @1.31 (annoncé 78.2 %). Une jambe de plus dans un coupon est une chance de plus de perdre.
Match piège : 1899 Hoffenheim vs Bayer Leverkusen — 4 jambes DIFFÉRENTES perdues (Asian Handicap (-1.5) 2; Asian Handicap (-1.0) 2; Both Teams To Score Yes) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Sunderland vs Leeds — 2 jambes DIFFÉRENTES perdues (Over Under Team 2 (2.0) Under; Over Under Full Time (3.0) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Atalanta vs Frosinone — 4 jambes DIFFÉRENTES perdues (Over Under Full Time (5.5) Under; Over Under Team 2 (2.0) Under; Corners - Over Under Full Time (12.5) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Liverpool vs Brighton — 2 jambes DIFFÉRENTES perdues (Both Teams To Score Yes; Asian Handicap (-1.0) 2) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Jambe anno
```

### Nouvelle étude finale proposée
```
Bilan du jour : 1 coupon(s) gagné(s), 5 perdu(s) sur 6.
Match piège : 1899 Hoffenheim vs Bayer Leverkusen — 2 jambes DIFFÉRENTES perdues (Asian Handicap (-1.0) 2; Both Teams To Score Yes) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Atalanta vs Frosinone — 2 jambes DIFFÉRENTES perdues (Over Under Team 2 (2.0) Under; Corners - Over Under Full Time (12.5) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Jambe annoncée à 79.8 % perdue : Atalanta vs Frosinone — Over Under Team 2 (2.0) Under (dans 1 coupon(s)).
Jambe annoncée à 79.7 % perdue : 1899 Hoffenheim vs Bayer Leverkusen — Asian Handicap (-1.0) 2 (dans 1 coupon(s)).
LEÇONS : 1) Seul le coupon 🟢 a gagné. Pertes : 🟠 sur 3 jambes, 🔴 sur 4, les 3 ⭐ sur 2 chacun (Udinese AH 1,5 dans 2 coupons). Matchs pièges : Hoffenheim-Leverkusen, Atalanta-Frosinone (2 paris perdus chacun). 2) Handicap : 4/8 réussis, 50,0 % pour 72,3 % annoncé (n=8) : à pondérer fortement. BTTS Oui : 1/3 (n=3), à surveiller. 3) Question : les AH favoris sont-ils surévalués ?
```

Jambes jugées dans les statistiques enregistrées : 47 (coupons envoyés seulement).

## 2026-10-24 (étude 9) — 1326 caractères

### Ancienne étude (base, tronquée à 1 400 caractères)
```
Bilan du jour : 0 coupon(s) gagné(s), 7 perdu(s) sur 7.
Match piège : Borussia Dortmund vs Eintracht Frankfurt — 2 jambes DIFFÉRENTES perdues (Over Under Full Time (2.5) Over; Corners - Over Under Team 2 (2.5) Over) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Chelsea vs Tottenham — 3 jambes DIFFÉRENTES perdues (Double Chance Full Time 1X; Over Under Team 2 (1.5) Under; Asian Handicap (0.0) 1) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : RB Leipzig vs SV Elversberg — 2 jambes DIFFÉRENTES perdues (Over Under Team 1 (3.0) Under; Asian Handicap (-2.5) 2) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Jambe annoncée à 81.3 % perdue : Rayo Vallecano vs Elche — Offsides - Over Under Team 1 (3.5) Under (dans 1 coupon(s)).
Jambe annoncée à 77.4 % perdue : Chelsea vs Tottenham — Double Chance Full Time 1X (dans 2 coupon(s)).
Jambe annoncée à 75.7 % perdue : Coventry vs Fulham — Over Under Team 1 (0.5) Over (dans 1 coupon(s)).
Jambe annoncée à 75.6 % perdue : RB Leipzig vs SV Elversberg — Asian Handicap (-2.5) 2 (dans 1 coupon(s)).
LEÇONS : 1) Analyse des coupons :  
- ⭐ SPÉCIAL A et 🟢 FAIBLE et 🟠 MOYEN et ⭐ SPÉCIAL B ont perdu parce que chaque jambe perdue étai
```

### Nouvelle étude finale proposée
```
Bilan du jour : 0 coupon(s) gagné(s), 5 perdu(s) sur 5.
Match piège : RB Leipzig vs SV Elversberg — 2 jambes DIFFÉRENTES perdues (Asian Handicap (-2.5) 2; Over Under Team 1 (3.0) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Chelsea vs Tottenham — 2 jambes DIFFÉRENTES perdues (Double Chance Full Time 1X; Over Under Team 2 (1.5) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Jambe annoncée à 81.3 % perdue : Rayo Vallecano vs Elche — Offsides - Over Under Team 1 (3.5) Under (dans 1 coupon(s)).
Jambe annoncée à 78.6 % perdue : Chelsea vs Tottenham — Double Chance Full Time 1X (dans 1 coupon(s)).
Jambe annoncée à 75.7 % perdue : Coventry vs Fulham — Over Under Team 1 (0.5) Over (dans 1 coupon(s)).
Jambe annoncée à 75.6 % perdue : RB Leipzig vs SV Elversberg — Asian Handicap (-2.5) 2 (dans 1 coupon(s)).
LEÇONS : 1) Les 5 coupons ont perdu, chacun par 2 à 3 jambes. Matchs pièges : RB Leipzig-Elversberg et Chelsea-Tottenham (2 paris perdus chacun). 2) Tranche 60-70 % : 19/25 réussies, 76,0 % pour 65,9 % annoncé (n=25) ; 70-80 % : 72,7 % pour 74,4 % (n=22), calibrée. Total équipe 1 : 0/2, à surveiller. 3) Question : ces paris perdus étaient-ils corrélés ?
```

Jambes jugées dans les statistiques enregistrées : 49 (coupons envoyés seulement).

## 2026-10-23 (étude 8) — 1223 caractères

### Ancienne étude (base, tronquée à 1 400 caractères)
```
Bilan du jour : 4 coupon(s) gagné(s), 14 perdu(s) sur 18.
4 coupon(s) perdu(s) par UNE seule jambe (4 jambe(s) différente(s)) : Alaves vs Malaga — Corners - Over Under Team 2 (2.5) Over @1.23 (annoncé 76.0 %); Torino vs Monza — Over Under Team 2 (1.5) Under @1.44 (annoncé 70.3 %); Alaves vs Malaga — Corners - Over Under Team 2 (3.0) Over @1.32 (annoncé 71.7 %); 1. FC Köln vs FC Schalke 04 — Yellow Cards - Over Under Full Time (4.5) Under @1.48 (annoncé 68.8 %). Une jambe de plus dans un coupon est une chance de plus de perdre.
Match piège : Alaves vs Malaga — 3 jambes DIFFÉRENTES perdues (Corners - Over Under Team 2 (2.5) Over; Double Chance Full Time 12; Corners - Over Under Team 2 (3.0) Over) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Aston Villa vs Manchester City — 2 jambes DIFFÉRENTES perdues (Shots - Over Under Full Time (24.5) Over; Shots - Over Under Full Time (26.5) Over) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : RB Leipzig vs SV Elversberg — 3 jambes DIFFÉRENTES perdues (Asian Handicap (-2.5) 2; Asian Handicap (-2.0) 2; Over Under Team 1 (3.0) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Match piège : Cagliari vs Bologna — 2 jam
```

### Nouvelle étude finale proposée
```
Bilan du jour : 2 coupon(s) gagné(s), 4 perdu(s) sur 6.
3 coupon(s) perdu(s) par UNE seule jambe (3 jambe(s) différente(s)) : Alaves vs Malaga — Corners - Over Under Team 2 (2.5) Over @1.23 (annoncé 76.0 %); Torino vs Monza — Over Under Team 2 (1.5) Under @1.44 (annoncé 70.3 %); Alaves vs Malaga — Corners - Over Under Team 2 (3.0) Over @1.32 (annoncé 71.7 %). Une jambe de plus dans un coupon est une chance de plus de perdre.
Match piège : Alaves vs Malaga — 3 jambes DIFFÉRENTES perdues (Corners - Over Under Team 2 (2.5) Over; Double Chance Full Time 12; Corners - Over Under Team 2 (3.0) Over) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Jambe annoncée à 75.0 % perdue : Alaves vs Malaga — Double Chance Full Time 12 (dans 1 coupon(s)).
LEÇONS : 1) Sur 6 coupons, 2 ont gagné ; 3 pertes tiennent à une seule jambe : Alaves-Malaga corners équipe 2 (2,5 et 3,0, dans 3 coupons, n=3) et Torino-Monza Under équipe 2 1,5. Alaves-Malaga : 3 paris perdus. 2) Corners équipe 2 : 3/5 réussis, 60 % pour 75 % annoncé (n=5), à surveiller. Tranche 70-80 % : 84,8 % pour 74,1 % annoncé (n=33). 3) Question : pourquoi 3 coupons dépendaient-ils du même scénario ?
```

Jambes jugées dans les statistiques enregistrées : 35 (coupons envoyés seulement).
