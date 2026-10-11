# Audit A — Incohérence des cibles de cote totale (IA stratège vs repli Python)

**Date** : 2026-10-11. **Méthode** : lecture directe du code réel (`bet_agent/analyser_et_envoyer.py`,
`bet_agent/agent_strategie.py`), aucune donnée inventée, aucune modification de production.

## 1. Quel chemin est réellement actif aujourd'hui ?

```python
UTILISER_STRATEGE_IA = os.getenv("UTILISER_STRATEGE_IA", "false").lower() not in ("0", "false", "non", "no")
```

**`false` par défaut depuis le 03/10/2026** ("diminue le travail de l'IA, seulement en
rédaction"). Aucune variable `UTILISER_STRATEGE_IA` n'est définie dans
`.github/workflows/pipeline-quotidien.yml` ni dans les secrets/variables du dépôt (vérifié) —
**le chemin réellement actif en production aujourd'hui est donc le repli Python (Monte Carlo),
pas l'IA stratège.** L'IA stratège (`agent_strategie.py`) reste du code disponible,
réactivable par cette seule variable, mais inactive par défaut.

## 2. La règle réellement utilisée par CHAQUE chemin

### Chemin actif par défaut — repli Python (`selectionner_combo_cote_cible`)
Lit `PROFILS_COUPON[0]` : `cote_min=1.1`, `cote_max=2.1` — **cible une fourchette de cote
TOTALE** (demande explicite du 03/10/2026 : "notre cote cible est 1.1 à 2.1"). En plus,
appliqués UNIQUEMENT à ce chemin (`_filtres_fallback_auto`, lignes 2536-2577) :
- `PROBA_MIN_FALLBACK_AUTO = 30.0` (plancher de probabilité individuelle).
- `COTE_INDIVIDUELLE_MAX_FALLBACK_AUTO = 2.0` (aucune jambe individuelle au-delà de cote 2.0).

### Chemin optionnel, inactif par défaut — IA stratège (`agent_strategie.valider`)
```python
plancher = profil.get("cote_totale_min", COTE_TOTALE_MIN)  # COTE_TOTALE_MIN = 5.0
...
if selections and cote < plancher:
    erreurs.append(...)
```
`PROFILS_COUPON[0]` ne définit **aucune** clé `"cote_totale_min"` — donc ce chemin retombe
systématiquement sur `COTE_TOTALE_MIN = 5.0` ("demande explicite du 01/10/2026 : interdit les
cote total moins de 5"), **un plancher SANS plafond**, et **sans aucun plafond de cote
individuelle** (`COTE_INDIVIDUELLE_MAX_FALLBACK_AUTO` n'est jamais lu par ce chemin — son nom
le dit déjà : "FALLBACK_AUTO" seulement).

## 3. La divergence réelle

| | Repli Python (actif par défaut) | IA stratège (inactif par défaut, réactivable) |
|---|---|---|
| Cible de cote TOTALE | 1.1 - 2.1 (fourchette étroite) | ≥ 5.0 (plancher seul, aucun plafond) |
| Plafond de cote INDIVIDUELLE | 2.0 | aucun |
| Plancher de probabilité individuelle | 30 % | aucun (l'IA voit tout le pool, y compris edge négatif, et choisit elle-même) |
| Date de la demande à l'origine | 03/10/2026 | 01/10/2026 (2 jours plus tôt) |

**Ces deux règles ne sont pas de simples variantes du même objectif — elles ciblent des profils
de risque opposés.** Le plancher de 5.0 (01/10) a été écrit avant la demande explicite de
fourchette 1.1-2.1 (03/10, 2 jours après) ; cette fourchette n'a ensuite été câblée QUE dans le
repli Python, jamais reportée dans `agent_strategie.py`. Rien n'indique que ce soit volontaire —
aucun commentaire ne justifie pourquoi l'IA stratège devrait viser une cote totale 2 à 5 fois
plus élevée que le repli automatique censé la remplacer "si l'IA échoue".

## 4. Conséquence réelle, si elle se produit

Tant que `UTILISER_STRATEGE_IA` reste à `false` (cas actuel), **aucune conséquence
opérationnelle** : seul le repli Python décide, avec sa règle 1.1-2.1 cohérente et déjà
appliquée à tous les runs réels de cette session. **Mais si `UTILISER_STRATEGE_IA=true` est
remis un jour** (c'était le défaut du 26/09 au 03/10/2026, et le code reste pleinement
fonctionnel) : le coupon basculerait silencieusement d'une cote totale typique ~1.1-2.1 à une
cote totale ≥5.0 — un changement radical de profil de risque (bien moins de paris "sûrs"
combinés, ou des cotes individuelles plus élevées pour atteindre 5.0) **sans qu'aucun
avertissement ni test ne signale ce changement**, puisque les deux chemins ne sont jamais
comparés entre eux dans le code ni dans les tests existants.

## 5. Proposition — une règle unique (NON appliquée, en attente de validation)

Deux options existent, selon l'intention réelle voulue (à clarifier avec vous, pas déduite ici) :

**Option A — aligner l'IA stratège sur le repli (cohérent avec la demande la plus récente,
03/10/2026)** : ajouter `"cote_totale_min": 1.1` (ou retirer le concept de plancher seul et
ajouter un plafond symétrique) dans `PROFILS_COUPON[0]`, et faire lire par `agent_strategie.
valider()` un plafond de cote totale équivalent à `cote_max` du profil (actuellement non lu du
tout par ce module). Cohérent avec l'intention la plus récente exprimée par l'utilisateur.

**Option B — aligner le repli sur l'IA stratège (cohérent avec la demande du 01/10/2026,
"interdit les cote total moins de 5")** : relever `cote_min`/`cote_max` de `PROFILS_COUPON[0]`
à une fourchette compatible avec ≥5.0. Contredirait la demande plus récente du 03/10/2026, donc
moins probable d'être l'intention réelle, mais listé par exhaustivité.

**Aucune des deux options n'est appliquée par cet audit.** Le choix dépend de l'intention
business réelle (quel niveau de risque/cote viser), une décision qui vous revient.

## 6. Portée de cet audit

Lecture de code uniquement, aucune donnée Supabase consultée ou modifiée, aucun fichier de
production modifié, aucune exécution de test nécessaire (aucun changement de code).
