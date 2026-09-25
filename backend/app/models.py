"""Schéma de la base. Un RUN = une exécution du pipeline (ou un import de fichiers JSON
produits sur Termux). Chaque run possède ses MATCHS (avec toutes leurs COTES 1xBet et les
données d'équipe collectées) et ses 3 COUPONS, eux-mêmes composés de JAMBES (paris)."""

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def maintenant():
    return datetime.now(timezone.utc)


# Valeurs possibles des colonnes "statut" / "resultat" (chaînes simples, lisibles en SQL)
STATUTS_RUN = ("en_cours", "termine", "abandonne", "erreur")
STATUTS_COUPON = ("en_attente", "gagne", "perdu", "incertain", "vide")
RESULTATS_JAMBE = ("en_attente", "gagne", "perdu", "push", "non_verifiable")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    lance_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)
    termine_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20), default="api")  # api | import
    statut: Mapped[str] = mapped_column(String(20), default="en_cours", index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    nb_matchs: Mapped[int] = mapped_column(Integer, default=0)
    nb_matchs_avec_marches: Mapped[int] = mapped_column(Integer, default=0)
    nb_marches: Mapped[int] = mapped_column(Integer, default=0)
    envoye_telegram: Mapped[bool] = mapped_column(Boolean, default=False)

    matchs: Mapped[list["Match"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    coupons: Mapped[list["Coupon"]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                                   order_by="Coupon.profil")


class Match(Base):
    __tablename__ = "matchs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    domicile: Mapped[str] = mapped_column(String(120))
    exterieur: Mapped[str] = mapped_column(String(120))
    ligue: Mapped[str | None] = mapped_column(String(120))
    coup_envoi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fixture_id_oddspapi: Mapped[str | None] = mapped_column(String(64), index=True)
    fixture_id_api_football: Mapped[int | None] = mapped_column(Integer)
    score_domicile: Mapped[int | None] = mapped_column(Integer)
    score_exterieur: Mapped[int | None] = mapped_column(Integer)
    # Données d'équipe brutes : stats historiques, xG Understat, Elo, classement, contexte Serper
    donnees: Mapped[dict | None] = mapped_column(JSON)

    run: Mapped[Run] = relationship(back_populates="matchs")
    cotes: Mapped[list["Cote"]] = relationship(back_populates="match", cascade="all, delete-orphan")


class Cote(Base):
    """Une sélection d'un marché 1xBet (le marché 1X2 n'est pas collecté par le pipeline)."""

    __tablename__ = "cotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matchs.id", ondelete="CASCADE"), index=True)
    marche_id: Mapped[str] = mapped_column(String(32))
    marche: Mapped[str] = mapped_column(String(120))
    handicap: Mapped[float | None] = mapped_column(Float)
    periode: Mapped[str | None] = mapped_column(String(32))
    selection: Mapped[str] = mapped_column(String(64))
    cote: Mapped[float] = mapped_column(Float)

    match: Mapped[Match] = relationship(back_populates="cotes")


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    jour: Mapped[date] = mapped_column(Date, index=True)
    profil: Mapped[str] = mapped_column(String(20))  # profil1 | profil2 | profil3
    nom: Mapped[str] = mapped_column(String(80))
    cote_min: Mapped[float | None] = mapped_column(Float)
    cote_max: Mapped[float | None] = mapped_column(Float)
    cote_totale: Mapped[float | None] = mapped_column(Float)
    proba_combinee_pct: Mapped[float | None] = mapped_column(Float)
    texte: Mapped[str | None] = mapped_column(Text)  # ticket rédigé par le LLM
    statut: Mapped[str] = mapped_column(String(20), default="en_attente", index=True)
    bilan_envoye: Mapped[bool] = mapped_column(Boolean, default=False)  # bilan Telegram du soir

    run: Mapped[Run] = relationship(back_populates="coupons")
    jambes: Mapped[list["Jambe"]] = relationship(back_populates="coupon", cascade="all, delete-orphan",
                                                 order_by="Jambe.id")


class Jambe(Base):
    __tablename__ = "jambes"

    id: Mapped[int] = mapped_column(primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id", ondelete="CASCADE"), index=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matchs.id", ondelete="SET NULL"), index=True)
    libelle_match: Mapped[str] = mapped_column(String(250))
    domicile: Mapped[str | None] = mapped_column(String(120))
    fixture_id_oddspapi: Mapped[str | None] = mapped_column(String(64), index=True)
    categorie: Mapped[str] = mapped_column(String(40))
    marche: Mapped[str] = mapped_column(String(160))
    handicap: Mapped[float | None] = mapped_column(Float)
    selection: Mapped[str] = mapped_column(String(64))
    cote: Mapped[float] = mapped_column(Float)
    proba_modele_pct: Mapped[float | None] = mapped_column(Float)
    edge_pct: Mapped[float | None] = mapped_column(Float)
    guide: Mapped[str | None] = mapped_column(Text)
    onglet: Mapped[str | None] = mapped_column(String(160))
    resultat: Mapped[str] = mapped_column(String(20), default="en_attente", index=True)

    coupon: Mapped[Coupon] = relationship(back_populates="jambes")
    match: Mapped[Match | None] = relationship()
