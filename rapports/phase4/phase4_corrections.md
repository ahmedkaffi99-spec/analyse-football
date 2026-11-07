# Phase 4 — Corrections contrôlées du pipeline football (07/11/2026)

Référence : rapport d'audit `audit_pipeline_quotidien.md` (verdict « GO SOUS CONDITIONS »), section L.
Dépôt de travail : **`analyse-football`** (choix confirmé par l'utilisateur : le dépôt `analyse-football-codex` n'existe plus, supprimé à sa demande).
**Aucun commit, push, merge, lancement de workflow, appel API payant, écriture Supabase, envoi Telegram ni changement de cron.**

## 1. État initial du dépôt
- Branche `claude/analyse-matchs-football-796va6`, commit `f5aff9b` (pause du cron), `origin/main` = `1fcf3cf`.
- 8 fichiers non suivis (Phase 4 : `suivi_modeles.py`, `protocole_comparatif.py`, `test_suivi_modeles.py`, `backend/migrations/phase4/`, 4 documents `docs/phase4-*`) et 1 stash (`regles-simplifiees : ebauche NON validee`).
- Aucune modification suivie. Tests de départ : 1 080 réussis (audit) + 37 (suivi) sans échec.

## 2. Anomalies corrigées (référence : audit)
| Audit | Correction | Statut |
|---|---|---|
| D1 durée 75 min > job 60 min | Défaut ramené à 45 min ; `AGENT_DUREE_MAX_MIN=45` explicite dans le workflow ; arrêt propre déjà géré par `piloter` | Corrigé |
| D1/D3 timeout : statut et coûts perdus | Coûts écrits après chaque appel (`COUTS_FICHIER`) ; nouvelle tâche `app.taches finaliser` exécutée par une étape `if: always()` : run « en_cours » → « interrompu » avec la dépense | Corrigé (non vérifié sur un vrai timeout GitHub) |
| D2 budget non plafonné en cours de run | Contrôle AVANT chaque appel du pilote (`budget_atteint`) ; le vote reçoit le restant APRÈS la dépense du pilote | Corrigé |
| Coût inconnu compté gratuit | `budget_ia.cout_appel` : coût fournisseur, sinon estimation prudente (3 / 15 $ par M tokens, remplaçable), sinon forfait 0,01 $ ; appliqué au pilote et au vote ; alerte « coût estimé » | Corrigé |
| D3/D4 coûts invisibles des runs en erreur | `runs.py` : le run reste « erreur » (jamais masqué) et le détail reçoit `COUTS_AGENT` relu du fichier | Corrigé |
| D4 relances payantes répétitives | `garde.relances_payantes_epuisees` : au plus 2 runs payants ratés/jour (`MAX_ECHECS_PAYANTS_PAR_JOUR`) pour les passages planifiés ; alerte au dernier passage ; le lancement manuel n'est pas bridé | Corrigé |
| Statuts réussi / échoué / interrompu / en cours | Nouveau statut `interrompu` (run tué) distinct de `erreur`, utilisé par la garde, la finalisation, les alertes | Corrigé |
| Exécutions simultanées | `garde.autre_run_en_cours` : le run le plus récent s'abstient (« abandonne », aucune dépense) ; le groupe de concurrence du workflow est conservé | Corrigé |
| Idempotence | `enregistrer_coupons` ne crée jamais une seconde série pour un run ; `finaliser` ne touche pas un run terminé et ne double pas la dépense | Corrigé |
| D6 chat Telegram codé en dur | Valeur par défaut supprimée (`TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES` vide) ; second chat uniquement via la variable du dépôt, transmise par le workflow | Corrigé |
| D7 `coupons.jour` = date du run | `jour_du_coupon` : date du match le plus tôt du coupon (UTC) ; repli sur la date du jour seulement sans coup d'envoi connu | Corrigé |
| Même match dans plusieurs coupons | Profils smart : `match_repete_autorise=False` ; `ajuster_repetition` l'autorise seulement si le catalogue a moins de matchs que coupons × jambes minimales ; le vote la respecte ; le pari exact identique reste interdit | Corrigé |
| Minimum de jambes | `nb_jambes_min=2` dans les profils smart ET vérifié par `valider` (annoncé à l'IA mais jamais contrôlé auparavant) | Corrigé |
| Modèle pilote non enregistré (DeepSeek) | `journal.modele_pilote` toujours écrit, plus `journal.route_pilote` (API DeepSeek ou OpenRouter/secours) | Corrigé |
| H cohérence des workflows | Test : les deux crons sont tous deux actifs ou tous deux en pause ; crons conservés ; aucun changement de cron | Corrigé |
| Seuils workflow ≠ code | **Non modifiés** (décision de l'utilisateur) ; les deux côtés sont figés par des tests ; `POIDS_MARCHE=0.65` conservé ; Dixon-Coles non activé | Documenté |
| Validation stricte du catalogue | Inchangée ; tests ajoutés : un identifiant inconnu est refusé, cote/probabilité/marché envoyés par l'IA sont ignorés au profit du catalogue | Conservé |

## 3. Fichiers modifiés (22) et créés (2 tests)
Modifiés : `.github/workflows/pipeline-quotidien.yml` (+14 lignes, aucune suppression, lignes `# PAUSE` intactes), `backend/app/{config,garde,models,taches}.py`, `backend/app/services/{alertes,budget,persistance,runs}.py`, `bet_agent/{agent_pilote,agent_strategie,analyser_et_envoyer,budget_ia,ombre,profils_smart,vote}.py`, tests : `backend/tests/{test_archives_et_robustesse,test_garde,test_preparer_formulaire}.py`, `bet_agent/{test_agent_pilote,test_agent_strategie,test_budget_ia}.py`.
Créés : `backend/tests/test_phase4_corrections.py` (22 tests), `bet_agent/test_phase4_corrections.py` (27 tests), ce rapport.
Non modifié : `verification-resultats.yml`.

## 4. Explication technique
- **Durée et finalisation** : `agent_pilote.DUREE_MAX_S` = 45 min. `tache_run` pose `{run_id}` dans `COUTS_FICHIER` ; après chaque appel, `enregistrer_couts_en_cours` y écrit le coût cumulé (écriture atomique, jamais bloquante). L'étape `Finaliser le run` (toujours exécutée) lit ce fichier et, si le run est resté « en_cours », le passe en « interrompu » avec `COUTS_AGENT`. Elle n'envoie rien et ne change pas le résultat du job.
- **Budget** : `piloter` appelle `budget_atteint(coût cumulé, restant)` avant chaque appel (restant `None` = pas de plafond ; `0` = mode sans dépense, aucun appel). `_voter_entre_modeles` répartit `restant − dépense du pilote`.
- **Coûts** : `cout_appel` ne renvoie 0 que si le fournisseur renvoie lui-même 0.
- **Relances** : `echecs_payants_du_jour` compte les runs `erreur/abandonne/interrompu` dont `total_usd > 0` ; `decision_passage` et `tache_run` s'y réfèrent. Les runs sans dépense (collecte vide) restent relançables.
- **Coupons** : voir tableau ; `valider` ajoute l'erreur « minimum N jambes » ; `vote.choisir_detail` écarte un coupon d'un autre modèle qui reprend un match déjà pris quand le profil l'interdit.

## 5. Tests ajoutés (49)
Durée du job et ordre des étapes du workflow ; coûts inconnus (valeurs, NaN, négatif, prix remplaçables) ; arrêt du pilote avant l'appel suivant, mode sans dépense, pas de bridage sans plafond ; fichier de coûts (atomique, jamais bloquant, écrit après chaque appel) ; modèle pilote enregistré ; `POIDS_MARCHE` ; seuils figés ; Telegram sans chat par défaut et sans identifiant en dur ; minimum de jambes ; match répété ; pari exact ; ajustement de répétition ; catalogue strict ; vote ; relances payantes ; run simultané ; finalisation (nominal, idempotent, fichiers absents/illisibles) ; run en erreur avec coûts / sans coûts ; alertes ; idempotence des coupons ; date réelle ; cohérence des workflows.
Tests existants adaptés (6), uniquement quand ils figeaient l'ancien comportement : `test_cout_du_pilote_mesure_ou_estime` (coût inconnu non gratuit), mocks du pilote (coût 0 renvoyé explicitement), `test_le_nombre_de_jambes_n_est_plus_borne` et `test_le_nombre_de_jambes_n_est_plus_impose` (minimum désormais vérifié, demande du 07/11), `test_defauts_gardent_le_comportement_smart_habituel` (profils à 2 jambes minimum, match non répété), et deux tests de run tué (« interrompu » au lieu de « erreur »).

## 6. Résultats des tests (sandbox sans réseau, clés retirées)
`moteur` 42 · `moteur_central` 59 · `bet_agent` 713 · `backend/tests` 328 · `tests` 24 = **1 166 réussis, 0 échec** (avant : 1 080 + 37). Ces tests ne prouvent aucune rentabilité prédictive.

## 7. Risques restant à traiter
1. L'étape `always()` après un vrai timeout GitHub n'a pas été exercée (aucun lancement autorisé).
2. **Changement de comportement Telegram** : tant que la variable du dépôt `TELEGRAM_CHAT_IDS_SUPPLEMENTAIRES` n'est pas créée, le second chat ne reçoit plus rien.
3. `coupons.jour` devient la date des matchs : `apprentissage.py` et `plan_verification.py` filtrent par `Coupon.jour` ; les anciennes lignes gardent la date du run. À valider avant la reprise.
4. Probabilité à 65 % issue du marché, vote par probabilité combinée, Dixon-Coles absent, marge retirée proportionnellement : non modifiés (décision attendue).
5. Estimation de coût prudente : peut brider plus tôt le budget de 3 $ qu'un coût réel plus bas.
6. Contraintes d'unicité absentes de l'ORM, non revérifiées en base ; `nb_jambes_min` par défaut du prompt (2) ≠ contrôle de `valider` (1 si le profil ne le précise pas).
7. Le pilote consomme tout le restant du jour s'il le faut : le vote peut être annulé (journalisé).
8. Un run planifié ne peut plus être relancé après 2 échecs payants : l'alerte l'indique, relance manuelle nécessaire.
9. Avant toute reprise : réactiver ensemble `pipeline-quotidien` et `verification-resultats`, sur validation explicite.

## 8. Dépôt original intact
Pas de dépôt séparé : le dépôt de production est le dépôt de travail. `HEAD` reste `f5aff9b` (aucun commit), `origin/main` reste `1fcf3cf`, aucune branche ni aucun fichier supprimé. Cron : les deux workflows n'ont que `workflow_dispatch` ; les lignes `# PAUSE   - cron:` sont inchangées (le diff du workflow ne contient aucune suppression). Rien lancé.

## 9. Fichiers non suivis et stash
Les 8 fichiers non suivis d'origine sont toujours présents et inchangés ; 2 fichiers de test s'y ajoutent, ainsi que ce rapport. `stash@{0}` (« regles-simplifiees : ebauche NON validee ») est intact ; les 2 branches `sauvegarde/…` aussi.

## 10. Verdict
**Prêt pour validation** des corrections A à H (zéro régression sur 1 166 tests), avec les réserves de la section 7, en particulier les points 1 à 3. Aucune reprise du cron ni lancement sans votre autorisation explicite.

---

## Addendum — nouvelle stratégie de génération (07/11/2026, demande de l'utilisateur)
- **Trois profils de risque** : 🟢 PRUDENT (probabilités les plus élevées, sécurité), 🟠 ÉQUILIBRÉ (compromis probabilité / rendement), 🔴 RISQUE (davantage de risque pour un gain potentiel plus élevé). Clés `coupon1/2/3` conservées (colonne `coupons.profil`), nouveau champ `niveau_risque` et `consigne`.
- **Aucune cote imposée** : plus de bande 5-10 / 12-18 / 20-35, plus de plancher absolu de 5, plus de plancher adaptatif, plus de champ `prefere_cote_elevee`. Un profil personnalisé (`profils_json`) peut encore fixer explicitement une bande, vérifiée par Python.
- **Validations Python conservées** : identifiants et cotes du catalogue (l'IA ne peut rien inventer), 2 jambes minimum, un pari par match et par event dans un coupon, un match dans un seul coupon (assoupli seulement si le catalogue manque de matchs), pari exact jamais répété, pas de coupons identiques.
- **Vote entre modèles par niveau de risque** : prudent = probabilité combinée maximale ; équilibré = valeur espérée (probabilité × cote totale) ; risque = cote totale la plus haute. Limite : le critère « risque » favorise mécaniquement les combinaisons les plus ambitieuses des modèles ; il ne mesure aucune rentabilité.
- **Consignes de l'IA alignées** avec les règles Python (le pilote et les modèles du vote ne sont plus invités à reprendre un match, ni à viser une bande) ; formulaire du workflow : plus de nombre de coupons ni de cote par coupon.
- **Nettoyage** : imports inutilisés supprimés (`agent_strategie`, `agents_familles`, `taches`, `runs`, `plan_verification`), commentaires périmés corrigés.
- **Tests** : 1 180 réussis, 0 échec (`moteur` 42, `moteur_central` 59, `bet_agent` 729, `backend/tests` 326, `tests` 24), sans réseau ni clé. Ils ne prouvent aucune rentabilité prédictive.
