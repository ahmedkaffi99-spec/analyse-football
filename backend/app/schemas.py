from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class JambeOut(_Orm):
    id: int
    match_id: int | None
    libelle_match: str
    categorie: str
    marche: str
    handicap: float | None
    selection: str
    cote: float
    proba_modele_pct: float | None
    edge_pct: float | None
    guide: str | None
    onglet: str | None
    resultat: str


class CouponOut(_Orm):
    id: int
    run_id: int
    jour: date
    profil: str
    nom: str
    cote_min: float | None
    cote_max: float | None
    cote_totale: float | None
    proba_combinee_pct: float | None
    statut: str
    texte: str | None
    jambes: list[JambeOut]


class RunOut(_Orm):
    id: int
    lance_le: datetime
    termine_le: datetime | None
    source: str
    statut: str
    detail: str | None
    nb_matchs: int
    nb_matchs_avec_marches: int
    nb_marches: int
    envoye_telegram: bool


class RunDetail(RunOut):
    coupons: list[CouponOut]


class RunCreate(BaseModel):
    envoyer_telegram: bool = False  # désactivé par défaut : un run de test n'envoie rien
    rediger: bool = True  # rédaction des tickets par le LLM (Groq → Gemini → OpenRouter)


class CoteOut(_Orm):
    marche_id: str
    marche: str
    handicap: float | None
    periode: str | None
    selection: str
    cote: float


class MatchOut(_Orm):
    id: int
    run_id: int
    domicile: str
    exterieur: str
    ligue: str | None
    coup_envoi: datetime | None
    fixture_id_oddspapi: str | None
    score_domicile: int | None
    score_exterieur: int | None


class MatchDetail(MatchOut):
    donnees: dict | None
    cotes: list[CoteOut]


class ImportIn(BaseModel):
    collecte: dict | None = None  # contenu de donnees_collectees.json
    ticket: dict | None = None  # contenu de ticket_du_jour.json


class VerificationOut(BaseModel):
    gagne: int = 0
    perdu: int = 0
    push: int = 0
    non_verifiable: int = 0
    pas_termine: int = 0
    annule: int = 0  # match reporté/annulé/abandonné (PST/CANC/ABD) -> remboursement, jamais un score deviné
    perime: int = 0  # délai de péremption dépassé sans verdict -> jamais en_attente indéfiniment
