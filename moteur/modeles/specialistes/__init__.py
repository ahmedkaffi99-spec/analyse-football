"""Les 11 modèles spécialisés, un par marché."""

from moteur.modeles.specialistes.base import ContexteMatch, ModeleMarche, Prediction
from moteur.modeles.specialistes.buts import (Btts, ButsEquipe1, ButsEquipe2, ButsTotal, DoubleChance, Handicap,
                                              Resultat, buts_attendus)
from moteur.modeles.specialistes.comptage import Cartons, Corners, Fautes, Tirs, comptage_attendu

SPECIALISTES = (Resultat(), DoubleChance(), Handicap(), ButsTotal(), ButsEquipe1(), ButsEquipe2(), Btts(),
                Corners(), Cartons(), Tirs(), Fautes())
SPECIALISTE_PAR_NUMERO = {s.numero: s for s in SPECIALISTES}
