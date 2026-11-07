"""Budget de dépenses IA (Phase 3, 06/11/2026) : lecture du plafond, répartition entre modèles et bilan des coûts d'un run.
Module pur Python (aucune dépendance). Règle : on ne dépense jamais sans savoir ce qui reste, et rien ne dépasse en silence —
tout refus, toute réduction et tout dépassement est écrit dans le journal du run (runs.detail) et affiché."""
import os

MIN_PAR_MODELE_DEFAUT = 0.10   # $ : en dessous, un modèle n'a pas de quoi composer 3 coupons (un tour coûte de l'ordre de 0,05-0,20 $)


def lire_budget(valeur):
    """BUDGET_JOUR_USD -> None (aucun plafond : variable absente, vide, « aucun ») ou un montant >= 0 en dollars.
    Illisible ou négatif : plafond de 0 (on préfère ne rien dépenser qu'ignorer en silence un plafond mal saisi)."""
    texte = str(valeur if valeur is not None else "").strip().lower().replace("$", "").replace(",", ".").strip()
    if texte in ("", "aucun", "illimite", "illimité", "none"):
        return None
    try:
        montant = float(texte)
    except ValueError:
        print(f"⚠️ Budget « {valeur} » illisible — plafond de 0 $ appliqué par prudence (aucune dépense IA payante).")
        return 0.0
    if montant != montant or montant < 0:
        print(f"⚠️ Budget « {valeur} » invalide — plafond de 0 $ appliqué par prudence.")
        return 0.0
    return montant


def minimum_par_modele():
    try:
        return max(0.0, float(os.getenv("BUDGET_MIN_PAR_MODELE_USD") or MIN_PAR_MODELE_DEFAUT))
    except ValueError:
        return MIN_PAR_MODELE_DEFAUT


def repartir(restant, modeles, plafond_modele, minimum=None):
    """Répartit le budget restant entre les modèles du vote -> (budgets {modele: $}, ignores [(modele, raison)]).
    restant None = pas de plafond journalier (chaque modèle garde son plafond propre). Sinon chaque modèle reçoit
    min(plafond propre, restant / nombre de modèles retenus) ; si cette part est sous le minimum utile, on retient moins
    de modèles (dans l'ordre demandé) plutôt que de les affamer tous."""
    minimum = minimum_par_modele() if minimum is None else minimum
    if restant is None:
        return {m: plafond_modele for m in modeles}, []
    if restant <= 0:
        return {}, [(m, "plafond journalier atteint") for m in modeles]
    n = len(modeles)
    while n > 0 and restant / n < minimum:
        n -= 1
    retenus, ignores = modeles[:n], modeles[n:]
    part = restant / n if n else 0.0
    return ({m: min(plafond_modele, part) for m in retenus},
            [(m, f"budget restant insuffisant ({restant:.2f} $ pour {len(modeles)} modèle(s), minimum {minimum:.2f} $ chacun)")
             for m in ignores])


def bilan_couts(usage_pilote, resultats_vote, gagnants, restant, ignores, repli=None):
    """Bilan structuré des coûts d'un run, stocké dans le journal (runs.detail). Seuls les appels mesurés (OpenRouter) ont un coût ;
    le pilote ne l'a que si le fournisseur le renvoie (sinon None et tokens seulement)."""
    modeles = []
    for r in resultats_vote or []:
        modeles.append({"modele": r.get("modele"), "tokens_entree": r.get("tokens_entree"), "tokens_sortie": r.get("tokens_sortie"),
                        "cout_usd": r.get("cout_usd"), "appels": r.get("appels"), "secondes": r.get("secondes"),
                        "erreur": r.get("erreur"), "coupons_valides": sum(1 for c in (r.get("coupons") or []) if c.get("dans_la_bande")),
                        "coupons_retenus": sum(1 for v in (gagnants or {}).values() if v == r.get("modele"))})
    pilote = dict(usage_pilote or {})
    total = round(sum(m["cout_usd"] or 0.0 for m in modeles) + float(pilote.get("cout_usd") or 0.0), 4)
    bilan = {"pilote": pilote, "vote": modeles, "gagnants": dict(gagnants or {}), "total_usd": total,
             "modeles_ignores": [{"modele": m, "raison": r} for m, r in (ignores or [])]}
    if restant is not None:
        bilan["budget_restant_avant_usd"] = round(restant, 4)
        if total > restant + 1e-9:
            bilan["depassement_usd"] = round(total - restant, 4)
    if repli:
        bilan["repli"] = repli
    alertes = []
    if ignores:
        alertes.append("vote réduit ou annulé : " + " ; ".join(f"{m} ({r})" for m, r in ignores))
    if bilan.get("depassement_usd"):
        alertes.append(f"dépassement de {bilan['depassement_usd']:.2f} $ du budget restant (dernier appel en cours au moment du plafond)")
    if alertes:
        bilan["alerte"] = " | ".join(alertes)
    return bilan


# ---------------------------------------------------------------------------------------------------------------------------------
# Phase 4 (07/11/2026, corrections contrôlées) : un coût INCONNU n'est jamais gratuit, et les coûts sont écrits au fil de l'eau.
# ---------------------------------------------------------------------------------------------------------------------------------
import json
import tempfile

PRIX_DEFAUT_ENTREE_USD_M = 3.0     # $ par million de tokens d'entrée, estimation PRUDENTE quand le fournisseur ne renvoie aucun coût
PRIX_DEFAUT_SORTIE_USD_M = 15.0
PRIX_DEEPSEEK_ENTREE_USD_M = 0.30    # estimation pour l'API DeepSeek officielle quand aucun coût n'est renvoyé (remplaçable par DEEPSEEK_PRIX_ENTREE_USD_M)
PRIX_DEEPSEEK_SORTIE_USD_M = 1.20    # $ par million de tokens de sortie (idem)


def _prix(nom, defaut):
    try:
        return max(0.0, float(os.getenv(nom) or defaut))
    except ValueError:
        return defaut


def cout_appel(usage, cout_fournisseur=None, prix_entree=None, prix_sortie=None):
    """-> (cout_usd, estime). Coût renvoyé par le fournisseur s'il existe ; sinon estimation à partir des tokens avec des prix
    PRUDENTS (PRIX_DEFAUT_*_USD_M, remplaçables) ; sans aucun token connu non plus, coût minimal forfaitaire de 0,01 $ : jamais 0 en silence.
    `prix_entree`/`prix_sortie` : prix configurés du modèle (ex. DeepSeek), prioritaires sur les prix par défaut."""
    usage = usage or {}
    if cout_fournisseur is not None:
        try:
            c = float(cout_fournisseur)
            if c == c and c >= 0:
                return c, False
        except (TypeError, ValueError):
            pass
    tin, tout = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    if not tin and not tout:
        return 0.01, True
    pin = prix_entree if prix_entree else _prix("PRIX_DEFAUT_ENTREE_USD_M", PRIX_DEFAUT_ENTREE_USD_M)
    pout = prix_sortie if prix_sortie else _prix("PRIX_DEFAUT_SORTIE_USD_M", PRIX_DEFAUT_SORTIE_USD_M)
    return (tin * pin + tout * pout) / 1_000_000, True


def budget_atteint(depense, restant):
    """True quand il ne faut plus lancer d'appel payant : `restant` None = pas de plafond ; sinon dépense >= restant (restant <= 0 : toujours)."""
    return restant is not None and (restant <= 0 or depense >= restant)


def fichier_couts():
    """Chemin du fichier de coûts du run en cours (COUTS_FICHIER) ; None = désactivé."""
    chemin = (os.getenv("COUTS_FICHIER") or "").strip()
    return chemin or None


def ecrire_couts(donnees, chemin=None):
    """Écrit (remplace, de façon atomique) l'état des coûts du run : lisible même si le processus est tué juste après.
    Ne lève jamais : un échec d'écriture ne doit pas arrêter un run (il est signalé sur la sortie standard)."""
    chemin = chemin or fichier_couts()
    if not chemin:
        return False
    try:
        dossier = os.path.dirname(os.path.abspath(chemin))
        os.makedirs(dossier, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dossier, prefix=".couts_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False)
        os.replace(tmp, chemin)
        return True
    except Exception as e:
        print(f"⚠️ Coûts non écrits dans {chemin} : {str(e)[:120]}")
        return False


def lire_couts(chemin=None):
    """Dernier état de coûts écrit, ou None (fichier absent ou illisible)."""
    chemin = chemin or fichier_couts()
    if not chemin or not os.path.exists(chemin):
        return None
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
