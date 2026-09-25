# CHECKPOINT bet_agent — Reprise rapide

## COURT TERME — reprendre exactement ici

- Dernier fix appliqué : max_tokens augmenté à 1500 (tâche 2) et 1000 (tâche 3) dans appel_openrouter, car les modèles gratuits sont des "reasoning models" qui épuisaient le budget en réflexion interne avant de répondre
- Mémoire persistante ajoutée : memoire_agents.json (créé automatiquement au run), suit court/moyen/long terme du pipeline lui-même
- Prochaine étape : lancer `python bet_agent.py`, vérifier le ticket final complet reçu sur Telegram, puis vérifier `cat memoire_agents.json`

## AGENTS — état actuel

- Agent 1 (matchs + tous les marchés réels 1xBet) : ✅ validé — API-Football filtré sur LIGUES_MAJEURES = [39, 140, 135, 78, 61, 2, 3, 88, 94] (Europe uniquement, MLS/Brasileirão retirés) ; cotes 1X2 via The Odds API ; tous les autres marchés via OddsPapi (fetch_oddspapi_all_markets)
- Agent 2 (contexte web Serper) : ✅ validé
- Agent 3 (calcul Poisson/xG réel) : ✅ validé — calcule uniquement le 1X2 avec probabilité réelle
- Agent 4 (3 tâches OpenRouter → ticket combiné) : ⚠️ en cours de stabilisation — Tâche 1 OK, Tâches 2/3 corrigées (max_tokens) mais à re-tester
- Agent 5 (envoi Telegram) : ✅ validé — envoie toujours un message même en cas d'échec partiel

## MOYEN TERME — architecture validée

- Fichier unique bet_agent.py, envi.local à part pour les clés API
- Bookmaker unique : 1xBet
- llama.cpp local abandonné pour la rédaction — uniquement OpenRouter
- Pipeline sécurisé : chaque agent dans un try/except individuel, aucun échec ne bloque le reste
- Ne sélectionne que des marchés avec cote réelle confirmée
- 3 matchs actuellement disponibles (période creuse estivale, qualifications européennes uniquement) : Omonia Nicosia vs Kairat Almaty, Levski Sofia vs Universitatea Craiova, Egnatia Rrogozhinë vs Celje

## LONG TERME — parcours et leçons

- Environnement : Samsung A56 (12 Go RAM, 256 Go stockage), Termux
- API utilisées : Telegram bot, API-Football, The Odds API, OddsPapi, Serper, OpenRouter
- OddsPapi : slug 1xBet = "1xbet" ; marketId 101 = Full Time Result (1X2) ; /v4/fixtures nécessite from/to (max 10 jours) ; /v4/markets a un champ "handicap" = ligne numérique exacte
- Leçon 1 : la correspondance textuelle approximative donne des faux positifs — toujours croiser avec les ligues majeures et vérifier dans l'app
- Leçon 2 : les modèles OpenRouter "gratuits" sont souvent des reasoning models — toujours prévoir 1000+ tokens même pour des tâches simples
- Leçon 3 : ne jamais faire confiance à un marché sans vérifier où se trouve sa vraie donnée numérique (ligne, période) dans la réponse API
