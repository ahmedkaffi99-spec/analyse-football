# Phase 4 — Comparaison des quatre modèles IA (état au 07/11/2026, 01 h UTC)

**Résumé en une phrase : les données actuelles ne permettent de classer aucun modèle.** Un seul modèle (DeepSeek) a un échantillon exploitable (15 coupons clos, mais sous d'anciennes règles) ; GPT n'a que 5 coupons clos, tous perdus, sur un seul jour ; Gemini et Claude n'ont aucun coupon jugé. Les coupons du 07/11 existent pour DeepSeek, GPT et Gemini, mais **aucun match du 07/11 n'est joué** (premier coup d'envoi à 12 h 30 UTC) : ils sont tous « en attente ».

Rapport produit en lecture seule : aucune écriture Supabase, aucun pipeline, aucun Telegram, aucun appel IA payant. Tous les chiffres viennent de requêtes `SELECT` du 07/11/2026 et du code du dépôt.

## 1. Les quatre modèles

| Nom demandé | Identifiant dans le dépôt | Remarque |
|---|---|---|
| DeepSeek Flash 4.1 | `deepseek-flash` (API DeepSeek) / `deepseek/deepseek-v4.1-flash` (OpenRouter) | Pilote par défaut |
| « GPT Sol 3.1 » | `openai/gpt-6.1-sol` | **Le dépôt dit 6.1, pas 3.1** : j'ai utilisé l'identifiant du dépôt. À confirmer si un autre modèle était visé |
| Claude Sonnet 5.5 | `anthropic/claude-sonnet-5.5` | |
| Gemini Argon 4 | `google/gemini-4-argon` | |

## 2. Données disponibles et règles d'attribution

**Règle absolue appliquée : un coupon final issu du vote collectif n'est jamais attribué à un modèle.** Le vote final n'a été ajouté qu'à 20 h 57 (Djibouti) le 06/11/2026, après le dernier run existant (run 271, 17 h 06 UTC) : aucun run en base n'est un résultat de vote. Malgré cela, je n'attribue un coupon à un modèle que s'il existe une preuve.

| Source | Modèle | Période | Volume | Attribution | Statut des résultats |
|---|---|---|---|---|---|
| `coupons` des runs 212, 213, 223, 238, 257, 258 (envoyés, journal d'agent) | DeepSeek (pilote) | 25/10 → 05/11 | 15 coupons clos, 5 jours | Journal d'agent présent ; pilote par défaut | Jugés |
| `coupons` du run 262 (coupons 356-358, envoyés) | DeepSeek (pilote) | pour le 07/11 | 3 coupons | Document `docs/comparaison-modeles-ia.md` du 06/11 ; **le journal ne le prouve pas** | **En attente** |
| `coupons` du run 271 (envoyé) | GPT (mode « modèle seul ») | pour le 06/11 | 2 coupons + 1 abstention | **Prouvée** : le journal enregistre `composition.modele = openai/gpt-6.1-sol` | Jugés |
| `coupons_ombre` / `jambes_ombre`, run 270 | GPT | pour le 06/11 | 3 coupons, 9 jambes | Colonne `modele` | Jugés |
| `coupons_ombre`, runs 265 et 269 | GPT (6 coupons), Gemini (4 coupons) | pour le 07/11 | 10 coupons | Colonne `modele` | **En attente** |
| `coupons_ombre`, run 267 | GPT | — | 3 coupons | Colonne `modele` | **Inutilisable** : les jambes n'ont pas de match rattaché |
| `coupons_ombre` | Claude | runs 265, 266, 269 | **0 coupon** | Colonne `modele` | Aucun |
| `coupons_ombre`, ligne « base » | modèle actuel, non identifié | runs 265, 269 | 0 coupon | — | Non attribuable à DeepSeek |

**Exclus volontairement :**
- Les coupons réels des runs 259 à 270, hors run 262 : aucun journal ne dit quel pilote les a produits (le formulaire du 06/11 permettait de choisir un autre modèle).
- Les runs envoyés sans journal d'agent (tous ceux d'avant le 25/10, et le run 206) : aucune preuve qu'ils viennent de DeepSeek plutôt que de l'ancien moteur.
- Le run 201, mélange manuel.
- Les coupons envoyés après vote : il n'y en a aucun à ce jour.
- Les lignes `ecartes_ia` et `ecartes_veto` de `coupons_ombre`, qui sont des paris écartés et non des modèles.

## 3. Vérifications effectuées (lecture seule)

- **Tables.** `coupons_ombre` compte 42 lignes sur un seul jour (06/11) et `jambes_ombre` 719 jambes. Ces tables sont intactes et ne sont plus alimentées par le code de la branche de travail.
- **Journaux.** Aucun journal de run ne contient le détail du vote (`vote`) ni le coût (`couts`) : ces rubriques sont postérieures au dernier run. Le modèle pilote n'est enregistré dans aucun journal.
- **Jugement.** 656 jambes de `jambes_ombre` sur 719 sont « en attente », dont **48 jambes de modèles pour le 07/11** (GPT 29, Gemini 19) ; le reste concerne les paris écartés et le run 267 sans match rattaché. Les 63 autres sont jugées (34 gagnées, 26 perdues, 3 push), dont les 9 jambes de GPT du run 270.
- **Scores.** 0 match du 07/11 a un score connu au moment de la vérification.
- **Doublons de tirage.** Les runs 265 et 269 couvrent les mêmes 20 affiches du 07/11 : GPT y a deux tirages et Gemini deux tirages (dont un seul coupon dans le second). Ils ne sont pas additionnés comme des échantillons indépendants.
- **Probabilités.** Les probabilités affichées pour chaque jambe viennent du catalogue Python partagé (modèle statistique mélangé au marché), pas d'une prédiction propre au modèle IA. **Les modèles IA ne font donc que choisir des jambes** : « leur prédiction » est leur sélection.

## 4. Résultats par modèle

### 4.1 DeepSeek (pilote, hors vote) — seul échantillon exploitable

15 coupons clos (6 runs, 5 jours, du 25/10 au 05/11) :

| Mesure | Valeur | Intervalle à 95 % |
|---|---|---|
| Coupons gagnés / perdus | **1 / 14** | — |
| Win rate des coupons | **6,7 %** | 1,2 % à 29,8 % |
| Cote totale moyenne des coupons clos | 14,02 (le seul gagné : 7,35) | — |
| Jambes par coupon | 7,8 en moyenne | — |
| Gain net théorique (mise de 1 par coupon clos) | **−10,76** | — |
| ROI théorique | **−71,7 %** | — |
| Jambes jugées : gagnées / perdues / push / demi | 75 / 28 / 12 / 1 | — |
| Win rate des jambes (hors push) | **72,8 %** (75/103), probabilité annoncée moyenne 71,4 % | 63,5 % à 80,5 % |

Lecture : le modèle choisit des jambes à 70 % environ qui se réalisent à peu près comme annoncé. Mais un coupon de 7 à 8 jambes à 72 % ne passe qu'environ une fois sur dix, et le ROI du coupon combiné est très négatif sur cet échantillon.

Performances par marché (jambes jugées, une ligne par jambe) :

| Marché | Jambes | Gagnées | Réussite | Intervalle à 95 % | Cote moy. | Annoncé moy. | Lecture |
|---|---|---|---|---|---|---|---|
| Total (temps plein) | 31 | 23 | 74,2 % | 56,8 – 86,3 | 1,40 | 71,8 % | conforme |
| Total corners | 21 | 15 | 71,4 % | 50,0 – 86,2 | 1,30 | 70,9 % | conforme |
| **Handicap** | **13** | **5** | **38,5 %** | 17,7 – 64,5 | 1,44 | 72,2 % | **très en dessous** |
| Double chance | 13 | 11 | 84,6 % | 57,8 – 95,7 | 1,35 | 73,1 % | au-dessus |
| Total équipe 2 | 11 | 9 | 81,8 % | — | 1,42 | 70,5 % | échantillon limité |
| Total équipe 1 | 9 | 7 | 77,8 % | — | 1,42 | 70,2 % | échantillon limité |
| Cartons, résultat, victoire sans encaisser | 5 | 5 | 100 % | — | — | — | **trop peu pour conclure** |

**Réserve majeure :** ces 15 coupons ont été produits **sous les anciennes règles** (probabilité minimale par jambe de 60 à 70 %, bandes de cote différentes, nombre de jambes imposé). Elles ont été retirées le 06/11. Ce n'est donc pas le même exercice que les coupons « smart » libres de GPT ou de Gemini. En outre, aucun journal ne prouve que DeepSeek a répondu seul : un repli vers un autre fournisseur est possible en cas de panne.

**Pour le 07/11 (run 262, 3 coupons envoyés, tous en attente) :** cotes 5,29 / 12,50 / 21,84, 4 / 4 / 3 jambes.

### 4.2 GPT-6.1 Sol

5 coupons clos : 3 en ombre (run 270) et 2 en mode « modèle seul » (run 271, plus une abstention sur le coupon 2).

| Mesure | Valeur | Intervalle à 95 % |
|---|---|---|
| Coupons gagnés / perdus | **0 / 5** | 0 % à 43,4 % |
| Cote totale moyenne | 5,94 (5,21 · 6,54 · 6,32 · 5,07 · 6,55) | — |
| ROI théorique (mise de 1 par coupon) | **−100 %** (−5 sur 5) | — |
| Jambes uniques : gagnées / perdues / push | 6 / 8 / 2 | — |
| Win rate des jambes (hors push) | 42,9 % (6/14) | 21,4 % à 67,4 % |
| Probabilité annoncée moyenne des jambes | **60,4 %** (16 jambes uniques) | — |

Par marché (jambes uniques, effectifs très faibles) : handicap 0/2, total temps plein 3/4 (1 push), total équipe 2 1/2 (1 push), total équipe 1 0/2, double chance 2/3, corners 0/1.

**Constat net :** un seul match, **Everton – Coventry, figurait dans les 5 coupons clos et a perdu à chaque fois** (handicap −1,5, handicap −1,0, double chance 2X, total équipe 1 sous 2,0). Les 5 défaites ne sont donc pas 5 observations indépendantes : c'est essentiellement un seul événement. De plus, GPT choisit des jambes nettement moins probables que DeepSeek (60,4 % contre 71,4 % annoncé, certaines à 42 % ou 43 %), mais mieux payées : un style différent, mesuré sur très peu de jambes.

**Pour le 07/11 :** 6 coupons en attente (run 265 : 5,18 · 12,98 · 20,67 ; run 269 : 5,12 · 12,91 · 21,73), 4 à 6 jambes chacun.

Coût et tokens (lignes de comparaison) : 1,00 $ sur 4 runs, 306 205 → 23 535 tokens, 12 coupons valides, soit environ 0,08 $ par coupon. Le run 271 « modèle seul » : 0,139 $, 38 348 → 4 310 tokens.

### 4.3 Gemini Argon 4

**Aucun coupon jugé.** 4 coupons pour le 07/11, en attente : run 265 (6,80 · 15,13 · 23,95) et run 269 (coupon 3 seul : 27,04). Coût : 0,43 $ sur 3 runs, 198 069 → 11 719 tokens, soit environ 0,11 $ par coupon valide. Au run 269, Gemini n'a produit qu'un seul coupon valide sur trois.

### 4.4 Claude Sonnet 5.5

**Aucun coupon enregistré.** Coût : 0,72 $ pour 260 549 → 19 698 tokens, sans aucune sortie exploitable.
- Run 265 : 0,39 $ dépensés, aucun coupon en base ; la cause n'est pas journalisée.
- Run 266 : 0 token.
- Run 269 : « aucun coupon valide après 2 appels (règles de Python non respectées) », 0,32 $.

Le coût par coupon valide ne peut pas être calculé. Rien ne permet d'évaluer sa sélection.

## 5. Tableau comparatif (à lire avec les réserves ci-dessus)

| | DeepSeek (pilote) | GPT-6.1 Sol | Gemini Argon 4 | Claude Sonnet 5.5 |
|---|---|---|---|---|
| Coupons clos | 15 | 5 | 0 | 0 |
| Gagnés / win rate | 1 / 6,7 % | 0 / 0 % | — | — |
| Cote totale moyenne | 14,02 | 5,94 | — | — |
| ROI théorique | −71,7 % | −100 % | — | — |
| Win rate des jambes | 72,8 % (n = 103) | 42,9 % (n = 14) | — | — |
| Probabilité annoncée moyenne des jambes | 71,4 % | 60,4 % | — | — |
| Coupons pour le 07/11 (en attente) | 3 | 6 | 4 | 0 |
| Coût par coupon valide | non enregistré | ≈ 0,08 $ | ≈ 0,11 $ | non calculable |
| Échantillon suffisant ? | **partiel, sous d'anciennes règles** | **non** | **non** | **non** |

**Aucune différence de performance entre modèles n'est démontrée.** Toutes les différences de pourcentage ci-dessus sont comprises dans les intervalles d'incertitude, et les règles n'étaient pas les mêmes.

## 6. Le 07/11/2026 (priorité demandée)

- **20 affiches**, du 12 h 30 UTC au 20 h 05 UTC. À 01 h 20 UTC : 0 score connu, donc rien n'est jugeable.
- **13 coupons pour le 07/11** : DeepSeek 3, GPT 6, Gemini 4, Claude 0. Le vote collectif n'a pas encore produit de coupon.

Espérance théorique par unité misée (produit des probabilités du catalogue × cote totale − 1) :

| Modèle | Coupons | Espérance théorique moyenne | Plage |
|---|---|---|---|
| DeepSeek (run 262) | 3 | +0,149 | +0,068 à +0,281 |
| GPT (runs 265, 269) | 6 | +0,110 | +0,079 à +0,144 |
| Gemini (runs 265, 269) | 4 | +0,143 | +0,099 à +0,223 |

**Ces espérances sont trompeuses et ne mesurent pas la qualité d'un modèle :** les probabilités sont communes à tous, elles supposent l'indépendance des jambes, et sur l'échantillon DeepSeek réel le même calcul aurait annoncé un ROI positif pour un résultat de −71,7 %. Elles ne donnent qu'un ordre de grandeur de la « valeur perçue » de chaque sélection.

**Comment juger le 07/11 :**
1. Attendre la fin du dernier match (20 h 05 UTC) puis la vérification.
2. DeepSeek : les coupons 356-358 sont jugés automatiquement par le workflow de vérification.
3. GPT et Gemini en ombre : **ils ne sont jugés par aucune tâche de la branche de travail actuelle** (le suivi « en ombre » y a été retiré le 06/11). Sur `main`, la tâche `rapport-ombre` existe encore. Il faudra donc soit l'utiliser, soit comparer les jambes aux scores finaux des matchs par une requête en lecture seule, avec la même fonction de jugement que l'application (`grader_pick`).

## 7. Erreurs récurrentes

1. **Handicap asiatique.** 5 réussites sur 13 jambes pour DeepSeek (38,5 % pour 72,2 % annoncé) et 0 sur 2 pour GPT, soit 5 sur 15 au total. Une étude du 25/10, tous runs envoyés confondus, mesurait déjà 4 sur 8 (50 %). Écart persistant mais échantillon petit : à surveiller.
2. **Un même match qui tombe dans plusieurs coupons.** Bayern – Magdeburg le 28/10 (les 3 coupons contenaient un pari perdu sur ce match), Everton – Coventry le 06/11 (5 coupons sur 5 pour GPT).
3. **Plusieurs paris perdus sur le même match** (« matchs pièges ») : Cardiff – West Ham le 04/11, Atalanta – Frosinone et Hoffenheim – Leverkusen le 25/10, RB Leipzig – Elversberg le 24/10.
4. **Coupons trop longs pour un win rate de jambe de 72 %.** 7 à 8 jambes donnent environ 10 % de chances de passer, d'où 1 coupon gagné sur 15.

## 8. Données manquantes et échantillons insuffisants

- **Aucun journal ne dit quel modèle pilote un run réel.** Le champ `modele_pilote` n'a jamais été enregistré en base.
- **Le détail du vote n'est pas conservé.** Depuis la Phase 3 on garde coûts, tokens et vainqueurs, mais pas les coupons de chaque modèle. Sans un enregistrement des coupons individuels, la comparaison ne pourra pas continuer.
- **Claude n'a jamais produit de coupon exploitable.** La cause du run 265 est inconnue.
- **Les runs 265 et 269 sont deux tirages sur les mêmes matchs** : ils ne doublent pas l'échantillon.
- **Seuils minimaux proposés pour conclure** : au moins 30 coupons clos par modèle sur au moins 10 jours distincts, au moins 100 jambes par modèle et 20 par marché, et des règles identiques. À ce jour, aucun modèle n'atteint ces seuils (DeepSeek 15 coupons / 5 jours ; GPT 5 / 1 ; Gemini 0 ; Claude 0).
- **Pas de comparaison à règles égales** : DeepSeek (ancien régime) et GPT/Gemini (régime « smart » libre) ne sont pas comparables.

## 9. Recommandations (aucune action n'a été engagée)

1. **Ne pas changer le modèle de production sur ces chiffres.**
2. **Enregistrer le modèle pilote de chaque run** (colonne ou clé du journal), puis **chaque coupon proposé par chaque modèle du vote**, avec ses jambes, pour avoir un échantillon attribuable. Cela demande un changement de code, et peut-être de schéma : je ne l'ai pas fait.
3. **Faire tourner les quatre modèles sur les mêmes jours et les mêmes règles** pendant au moins 10 jours, avec le budget IA de 3 $ par jour déjà en place (environ 0,3 à 0,4 $ par modèle et par jour d'après les runs de comparaison).
4. **Rejuger le 07/11** dès la fin des matchs et mettre à jour ce rapport avec les résultats réels.
5. **Clarifier le modèle « GPT Sol 3.1 »** par rapport à `gpt-6.1-sol`.

## Annexe — requêtes (lecture seule)

Les chiffres de ce rapport viennent de requêtes `SELECT` sur `coupons`, `jambes`, `runs`, `matchs`, `coupons_ombre` et `jambes_ombre`.
- **Ensemble DeepSeek :** `runs` avec `envoye_telegram` et `detail like 'JOURNAL_AGENT%'` et `id <= 258`, soit les runs 212, 213, 223, 238, 257 et 258.
- **Attribution du run 271 :** `substring(detail from '"composition":\{[^}]*\}')`.
- **Probabilité et espérance des coupons du 07/11 :** produit des `proba_modele_pct` des jambes, multiplié par `cote_totale`, moins 1.
- **Intervalles :** méthode de Wilson, niveau de confiance 95 %.
