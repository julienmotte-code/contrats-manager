"""
Modèles SQLAlchemy — Tables de la base de données PostgreSQL
"""
import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column, String, Integer, Numeric, Boolean, Date, DateTime, Time,
    Text, ForeignKey, CheckConstraint, UniqueConstraint, JSON
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class ClientCache(Base):
    """Cache local des clients Karlia — synchronisé depuis l'API."""
    __tablename__ = "clients_cache"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    karlia_id        = Column(String(100), unique=True, nullable=False)
    numero_client    = Column(String(20), unique=True, nullable=False)
    nom              = Column(String(255), nullable=False)
    adresse_ligne1   = Column(String(255))
    adresse_ligne2   = Column(String(255))
    code_postal      = Column(String(10))
    ville            = Column(String(100))
    pays             = Column(String(100), default="France")
    email            = Column(String(255))
    telephone        = Column(String(30))
    mobile           = Column(String(30))
    siret            = Column(String(14))
    tva_intracom     = Column(String(20))
    forme_juridique  = Column(String(100))
    contact_nom      = Column(String(150))
    contact_prenom   = Column(String(150))
    contact_fonction = Column(String(150))
    notes            = Column(Text)
    synchro_at       = Column(DateTime(timezone=True))
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contrats         = relationship("Contrat", back_populates="client", foreign_keys="Contrat.client_karlia_id",
                                    primaryjoin="ClientCache.karlia_id == Contrat.client_karlia_id")


class ArticleCache(Base):
    """Cache local des articles/produits Karlia."""
    __tablename__ = "articles_cache"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    karlia_id        = Column(String(100), unique=True, nullable=False)
    reference        = Column(String(100))
    designation      = Column(String(500), nullable=False)
    prix_unitaire_ht = Column(Numeric(12, 4))
    unite            = Column(String(50))
    taux_tva         = Column(Numeric(5, 2), default=20.00)
    actif            = Column(Boolean, default=True)
    synchro_at       = Column(DateTime(timezone=True))
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


class IndiceRevision(Base):
    """Historique des indices Syntec."""
    __tablename__ = "indices_revision"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date_publication = Column(Date, nullable=False)
    annee            = Column(Integer)
    mois             = Column(String(10), default="AOUT")   # AOUT / OCTOBRE / AUTRE
    famille          = Column(String(50), default="SYNTEC") # SYNTEC / etc.
    valeur           = Column(Numeric(10, 4), nullable=False)
    commentaire      = Column(Text)
    source_url       = Column(String(500))
    created_by       = Column(String(100))
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    factures_plan    = relationship("PlanFacturation", back_populates="indice_calcul")


class Contrat(Base):
    """Table principale des contrats."""
    __tablename__ = "contrats"

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_contrat        = Column(String(100), unique=True, nullable=False)
    client_karlia_id      = Column(String(100), nullable=False)
    client_numero         = Column(String(20))
    client_nom            = Column(String(255))

    # Dates
    date_debut            = Column(Date, nullable=False)
    date_fin              = Column(Date, nullable=False)
    nombre_annees         = Column(Integer, nullable=False)

    # Montants
    montant_annuel_ht     = Column(Numeric(12, 2), nullable=False)
    indice_reference_id   = Column(UUID(as_uuid=True), ForeignKey("indices_revision.id"), nullable=True)

    # Prorata
    prorate_annee1        = Column(Boolean, default=False)
    prorate_nb_mois       = Column(Numeric(4, 1))
    prorate_montant_ht    = Column(Numeric(12, 2))
    prorate_validated     = Column(Boolean, default=False)
    prorate_note          = Column(Text)
    prorate_demi_mois     = Column(Boolean, default=False)
    notes_internes        = Column(Text)

    # Famille de contrat (détermine la règle de révision)
    famille_contrat       = Column(String(50), default="COSOLUCE")

    # Hiérarchie (avenants / renouvellements)
    contrat_parent_id     = Column(UUID(as_uuid=True), ForeignKey("contrats.id"), nullable=True)
    type_contrat          = Column(String(30), default="CONTRAT")
    numero_avenant        = Column(Integer)

    # Statut
    statut                = Column(String(30), default="BROUILLON")
    date_statut_change    = Column(Date)
    motif_fin             = Column(Text)
    avenants_fusionnes    = Column(Boolean, default=False)

    # Métadonnées
    created_by            = Column(String(100))
    created_at            = Column(DateTime(timezone=True), server_default=func.now())
    updated_at            = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    validated_at          = Column(DateTime(timezone=True))

    # Contraintes
    __table_args__ = (
        CheckConstraint("date_fin > date_debut", name="ck_dates_coherentes"),
        CheckConstraint("type_contrat IN ('CONTRAT','AVENANT','RENOUVELLEMENT')", name="ck_type_contrat"),
        CheckConstraint("statut IN ('EN_COURS','A_RENOUVELER','TERMINE','BROUILLON')", name="ck_statut"),
    )

    # Relations
    articles              = relationship("ContratArticle", back_populates="contrat", cascade="all, delete-orphan",
                                         order_by="ContratArticle.rang")
    plan_facturation      = relationship("PlanFacturation", back_populates="contrat", cascade="all, delete-orphan",
                                         order_by="PlanFacturation.numero_facture")
    documents             = relationship("DocumentGenere", back_populates="contrat")
    client                = relationship("ClientCache", foreign_keys=[client_karlia_id],
                                         primaryjoin="Contrat.client_karlia_id == ClientCache.karlia_id")
    indice_reference      = relationship("IndiceRevision", foreign_keys=[indice_reference_id])
    enfants               = relationship("Contrat", foreign_keys=[contrat_parent_id])
    factures_karlia       = relationship("FactureKarlia", back_populates="contrat")


class ContratArticle(Base):
    """Articles associés à un contrat (désignation principale + 7 lignes annexe)."""
    __tablename__ = "contrat_articles"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contrat_id       = Column(UUID(as_uuid=True), ForeignKey("contrats.id", ondelete="CASCADE"), nullable=False)
    rang             = Column(Integer, nullable=False)  # 0 = principal, 1-7 = annexe
    article_karlia_id = Column(String(100))
    designation      = Column(String(500), nullable=False)
    reference        = Column(String(100))
    prix_unitaire_ht = Column(Numeric(12, 4))
    quantite         = Column(Numeric(10, 3), default=1)
    unite            = Column(String(50))
    taux_tva         = Column(Numeric(5, 2), default=20.00)

    __table_args__ = (
        CheckConstraint("rang >= 0 AND rang <= 7", name="ck_rang_valide"),
        UniqueConstraint("contrat_id", "rang", name="uq_contrat_rang"),
    )

    contrat = relationship("Contrat", back_populates="articles")


class PlanFacturation(Base):
    """Plan prévisionnel des factures sur la durée du contrat."""
    __tablename__ = "plan_facturation"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contrat_id           = Column(UUID(as_uuid=True), ForeignKey("contrats.id", ondelete="CASCADE"), nullable=False)
    numero_facture       = Column(Integer, nullable=False)
    annee_facturation    = Column(Integer, nullable=False)
    date_echeance        = Column(Date, nullable=False)
    type_facture         = Column(String(20), default="ANNUELLE")

    # Calcul
    montant_ht_prevu          = Column(Numeric(12, 2))
    montant_annuel_precedent  = Column(Numeric(12, 2))
    taux_revision             = Column(Numeric(8, 6))
    montant_revise_ht         = Column(Numeric(12, 2))
    indice_calcul_id          = Column(UUID(as_uuid=True), ForeignKey("indices_revision.id"), nullable=True)
    montant_ht_facture        = Column(Numeric(12, 2))

    # Lien Karlia
    facture_karlia_id    = Column(String(100))
    facture_karlia_ref   = Column(String(100))
    karlia_synchro_at    = Column(DateTime(timezone=True))
    karlia_statut        = Column(String(50))

    # Statut
    statut               = Column(String(30), default="PLANIFIEE")
    erreur_message       = Column(Text)

    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("contrat_id", "numero_facture", name="uq_contrat_facture"),
        CheckConstraint("type_facture IN ('PRORATE','ANNUELLE')", name="ck_type_facture"),
        CheckConstraint("statut IN ('PLANIFIEE','CALCULEE','EMISE','ERREUR')", name="ck_statut_facture"),
    )

    contrat       = relationship("Contrat", back_populates="plan_facturation")
    indice_calcul = relationship("IndiceRevision", back_populates="factures_plan")


class LotFacturation(Base):
    """Historique des traitements en lot."""
    __tablename__ = "lots_facturation"

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    annee_traitement      = Column(Integer, nullable=False)
    indice_utilise_id     = Column(UUID(as_uuid=True), ForeignKey("indices_revision.id"), nullable=True)
    declenche_par         = Column(String(100))
    declenche_at          = Column(DateTime(timezone=True), server_default=func.now())
    nb_contrats_traites   = Column(Integer, default=0)
    nb_factures_emises    = Column(Integer, default=0)
    nb_erreurs            = Column(Integer, default=0)
    statut                = Column(String(20), default="EN_COURS")
    termine_at            = Column(DateTime(timezone=True))
    rapport_json          = Column(JSON)


class DocumentGenere(Base):
    """Fichiers générés (Word + PDF) liés aux contrats."""
    __tablename__ = "documents_generes"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contrat_id       = Column(UUID(as_uuid=True), ForeignKey("contrats.id"), nullable=False)
    type_document    = Column(String(50), nullable=False)
    nom_fichier      = Column(String(500), nullable=False)
    chemin_docx      = Column(String(1000))
    chemin_pdf       = Column(String(1000))
    modele_utilise   = Column(String(200))
    variables_json   = Column(JSON)
    generated_by     = Column(String(100))
    generated_at     = Column(DateTime(timezone=True), server_default=func.now())

    contrat = relationship("Contrat", back_populates="documents")


class ModeleDocument(Base):
    """Modèles Word uploadés par l'entreprise."""
    __tablename__ = "modeles_documents"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type_document  = Column(String(50), nullable=False)
    nom            = Column(String(200), nullable=False)
    version        = Column(String(20))
    chemin_fichier = Column(String(1000), nullable=False)
    actif          = Column(Boolean, default=True)
    uploaded_by    = Column(String(100))
    uploaded_at    = Column(DateTime(timezone=True), server_default=func.now())
    description    = Column(Text)


class Utilisateur(Base):
    """Utilisateurs du module."""
    __tablename__ = "utilisateurs"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    login             = Column(String(100), unique=True, nullable=False)
    email             = Column(String(255), unique=True, nullable=False)
    nom_complet       = Column(String(200))
    password_hash     = Column(String(500), nullable=False)
    role              = Column(String(30), default="UTILISATEUR")
    actif             = Column(Boolean, default=True)
    derniere_connexion = Column(DateTime(timezone=True))
    formateur_id      = Column(Integer, ForeignKey("formateurs.id"))
    created_at        = Column(DateTime(timezone=True), server_default=func.now())


class Parametre(Base):
    """Configuration globale du module."""
    __tablename__ = "parametres"

    cle        = Column(String(100), primary_key=True)
    valeur     = Column(Text)
    description = Column(Text)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ══════════════════════════════════════════════════════════════════════════════
# GESTION DES COMMANDES (Devis acceptés Karlia)
# ══════════════════════════════════════════════════════════════════════════════

class Commande(Base):
    """Commande issue d'un devis accepté Karlia."""
    __tablename__ = "commandes"

    id                  = Column(Integer, primary_key=True, index=True)
    karlia_document_id  = Column(Integer, unique=True, nullable=False)
    karlia_customer_id  = Column(Integer)
    reference_devis     = Column(String(100))
    client_nom          = Column(String(255))
    client_email        = Column(String(255))
    client_telephone    = Column(String(50))
    client_adresse      = Column(Text)
    client_siret        = Column(String(20))
    montant_ht          = Column(Numeric(15, 2))
    montant_tva         = Column(Numeric(15, 2))
    montant_ttc         = Column(Numeric(15, 2))
    date_devis          = Column(Date)
    date_acceptation    = Column(Date)
    date_import         = Column(DateTime(timezone=True), server_default=func.now())
    date_validation     = Column(DateTime(timezone=True))
    statut              = Column(String(50), default='nouvelle')
    type_traitement     = Column(String(50))
    necessite_contrat   = Column(Boolean, default=False)
    date_planifiee      = Column(Date)
    intervenant_id      = Column(Integer)
    intervenant_nom     = Column(String(255))
    notes_planification = Column(Text)
    contrat_id          = Column(UUID(as_uuid=True), ForeignKey("contrats.id", ondelete="SET NULL"))
    pdf_devis           = Column(Text)  # Base64 encoded
    pdf_devis_nom       = Column(String(255))
    pdf_url             = Column(Text)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by          = Column(Integer)
    updated_by          = Column(Integer)
    formateur_id        = Column(Integer, ForeignKey("formateurs.id"))
    facture_karlia_id   = Column(String(50))
    facture_karlia_ref  = Column(String(50))

    lignes  = relationship("CommandeLigne", back_populates="commande", cascade="all, delete-orphan")
    contrat = relationship("Contrat", foreign_keys=[contrat_id])
    formateur = relationship("Formateur", back_populates="commandes")
    prestations = relationship("Prestation", back_populates="commande", cascade="all, delete-orphan")


class CommandeLigne(Base):
    """Ligne de commande (produit du devis)."""
    __tablename__ = "commande_lignes"

    id                = Column(Integer, primary_key=True, index=True)
    commande_id       = Column(Integer, ForeignKey("commandes.id", ondelete="CASCADE"))
    karlia_product_id = Column(String(50))
    designation       = Column(String(500))
    description       = Column(Text)
    quantite          = Column(Numeric(10, 3), default=1)
    unite             = Column(String(50))
    prix_unitaire_ht  = Column(Numeric(15, 2))
    taux_tva          = Column(Numeric(5, 2))
    montant_ht        = Column(Numeric(15, 2))
    montant_tva       = Column(Numeric(15, 2))
    montant_ttc       = Column(Numeric(15, 2))
    ordre             = Column(Integer, default=0)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    commande = relationship("Commande", back_populates="lignes")
    prestations = relationship("Prestation", back_populates="commande_ligne")


# ══════════════════════════════════════════════════════════════════════════════
# GESTION CHORUS PRO
# ══════════════════════════════════════════════════════════════════════════════

class FactureKarlia(Base):
    """Cache local des factures Karlia pour transmission Chorus Pro."""
    __tablename__ = "factures_karlia"

    id                     = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    karlia_document_id     = Column(Integer, unique=True, nullable=False)
    numero_facture         = Column(String(100), nullable=False)
    reference              = Column(String(200))

    # Client
    client_karlia_id       = Column(Integer, nullable=False)
    client_nom             = Column(String(255))
    client_siret           = Column(String(14))
    client_code_service    = Column(String(100))

    # Montants
    montant_ht             = Column(Numeric(15, 2), nullable=False)
    montant_tva            = Column(Numeric(15, 2))
    montant_ttc            = Column(Numeric(15, 2))

    # Dates
    date_facture           = Column(Date, nullable=False)
    date_echeance          = Column(Date)

    # Statut Chorus Pro
    statut_chorus          = Column(String(50), default='NON_TRANSMISE')
    date_transmission      = Column(DateTime(timezone=True))
    chorus_numero_flux     = Column(String(100))
    chorus_statut_technique = Column(String(100))
    chorus_date_statut     = Column(DateTime(timezone=True))
    chorus_message_erreur  = Column(Text)

    # Lien contrat
    contrat_id             = Column(UUID(as_uuid=True), ForeignKey("contrats.id", ondelete="SET NULL"))

    # Métadonnées
    imported_at            = Column(DateTime(timezone=True), server_default=func.now())
    updated_at             = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    contrat                = relationship("Contrat", back_populates="factures_karlia")
    transmissions          = relationship("TransmissionChorus", back_populates="facture", cascade="all, delete-orphan")


class TransmissionChorus(Base):
    """Journal des transmissions vers Chorus Pro."""
    __tablename__ = "transmissions_chorus"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facture_id        = Column(UUID(as_uuid=True), ForeignKey("factures_karlia.id", ondelete="CASCADE"), nullable=False)

    # Identifiants Chorus
    chorus_id_flux    = Column(String(100))
    chorus_id_facture = Column(String(100))

    # Statut
    statut            = Column(String(50), nullable=False, default='EN_ATTENTE')
    code_retour       = Column(String(50))
    message_retour    = Column(Text)

    # Données
    payload_json      = Column(JSONB)
    reponse_json      = Column(JSONB)

    # Métadonnées
    transmis_par      = Column(String(100))
    transmis_at       = Column(DateTime(timezone=True), server_default=func.now())

    # Relation
    facture           = relationship("FactureKarlia", back_populates="transmissions")


# ══════════════════════════════════════════════════════════════════════════════
# GESTION DES FORMATEURS ET PRESTATIONS
# ══════════════════════════════════════════════════════════════════════════════

class Formateur(Base):
    """Formateurs pouvant être assignés aux commandes."""
    __tablename__ = "formateurs"

    id           = Column(Integer, primary_key=True, index=True)
    nom          = Column(String(255), nullable=False)
    prenom       = Column(String(255))
    email        = Column(String(255), unique=True, nullable=False)
    email_google = Column(String(255))
    telephone    = Column(String(50))
    actif        = Column(Boolean, default=True)
    couleur      = Column(String(7), default='#3788d8')
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    commandes   = relationship("Commande", back_populates="formateur")
    prestations = relationship("Prestation", back_populates="formateur")


class Prestation(Base):
    """Prestation à planifier (issue d'une ligne de commande)."""
    __tablename__ = "prestations"

    id                = Column(Integer, primary_key=True, index=True)
    commande_id       = Column(Integer, ForeignKey("commandes.id", ondelete="CASCADE"), nullable=False)
    commande_ligne_id = Column(Integer, ForeignKey("commande_lignes.id", ondelete="SET NULL"))
    formateur_id      = Column(Integer, ForeignKey("formateurs.id"))
    designation       = Column(String(500), nullable=False)
    description       = Column(Text)
    duree_jours       = Column(Numeric(5, 2), default=1)
    date_prevue       = Column(Date)
    date_planifiee    = Column(Date)
    heure_debut       = Column(Time)
    heure_fin         = Column(Time)
    lieu              = Column(String(500))
    google_event_id   = Column(String(255))
    statut            = Column(String(50), default='a_planifier')
    notes             = Column(Text)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    commande       = relationship("Commande", back_populates="prestations")
    commande_ligne = relationship("CommandeLigne", back_populates="prestations")
    formateur      = relationship("Formateur", back_populates="prestations")
