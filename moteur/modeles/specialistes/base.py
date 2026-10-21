"""Interface commune des modèles spécialisés (un modèle = un marché).

Chaque spécialiste déclare : son numéro et son nom (voir catalogue.MODELES), les marchés qu'il
couvre, les données dont il a besoin et sa version. Il reçoit un ContexteMatch (features + config,
estimations de base calculées une seule fois) et renvoie des Prediction, ou [] si ses données sont
insuffisantes — jamais un chiffre inventé.
"""

from dataclasses import dataclass

from moteur.modeles import marches


@dataclass
class Prediction:
    modele: int
    nom_modele: str
    marche: str
    ligne: float | None
    selection: str
    issues: dict
    parametres: dict

    @property
    def probabilite(self):
        """Probabilité de gain plein. Sur un marché non binaire (remboursement/quart possible),
        voir aussi issues et esperance()."""
        return self.issues["gagne"]

    @property
    def binaire(self):
        return marches.est_binaire(self.issues)

    def esperance(self, cote):
        return marches.esperance(self.issues, cote)


class ContexteMatch:
    """Estimations de base d'un match, calculées à la demande puis mémorisées : plusieurs
    spécialistes de buts partagent la même matrice de scores sans la recalculer."""

    def __init__(self, features, cfg):
        self.features = features
        self.cfg = cfg
        self._memo = {}

    def memo(self, cle, calcul):
        if cle not in self._memo:
            self._memo[cle] = calcul()
        return self._memo[cle]


class ModeleMarche:
    numero: int
    nom: str
    marches: tuple
    donnees_requises: tuple
    version = "1.0.0"

    def predire(self, ctx, lignes):
        """list[Prediction] ; [] si les données requises manquent."""
        raise NotImplementedError

    def lignes_du_marche(self, lignes, marche):
        return lignes.get(marche) or [None]
