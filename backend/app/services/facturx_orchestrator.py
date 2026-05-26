"""
Orchestration de la génération Factur-X pour la transmission Chorus Pro
via la voie 'dépôt de flux'.

Pipeline :
  1) Lecture des paramètres (table parametres) + cache local FactureKarlia/ClientCache
  2) Appels Karlia (lecture seule)
       - GET /documents/{id}    -> customer_reference, products_list, échéance
       - GET /company           -> identité émetteur (nom + adresse)
       - GET <download_url>     -> PDF d'origine
  3) Mapping ORM/API -> facturx_cii_builder.FactureInput
  4) Génération XML CII (profil BASIC EN 16931)
  5) Normalisation Ghostscript en PDF/A-3
  6) Assemblage Factur-X (PDF/A-3 + XML CII embarqué)

Ce module n'effectue AUCUNE écriture en base et n'effectue AUCUN appel
Chorus Pro. Il retourne un FacturxBuildResult que l'appelant (API ou
service ChorusFluxService) consomme ensuite pour le dépôt effectif.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.models.models import ClientCache, FactureKarlia, Parametre
from app.services.facturx_cii_builder import (
    FactureInput,
    LigneFacture,
    PaymentMeansInput,
    TradeParty,
    build_xml_cii_basic,
)
from app.services.facturx_packager import package_facturx
from app.services.pdfa3_normalizer import normalize_to_pdfa3

logger = logging.getLogger(__name__)


KARLIA_BASE = "https://karlia.fr/app/api/v2"


@dataclass
class FacturxBuildResult:
    """Sortie complète du pipeline pour permettre logs et inspection en aval."""
    facture_input: FactureInput
    xml_cii_bytes: bytes
    pdf_karlia_bytes: bytes
    pdf_pdfa3_bytes: bytes
    pdf_facturx_bytes: bytes


class FacturxOrchestrationError(Exception):
    """Erreur de pipeline (paramètre manquant, document Karlia absent, etc.)."""


# ── Helpers de conversion ─────────────────────────────────────────────────

def _to_decimal(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if v is None or v == "":
        return Decimal("0")
    return Decimal(str(v))


def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def _compute_fr_vat_number(siret: str) -> Optional[str]:
    """
    Numéro de TVA intracom français calculé depuis le SIRET (14 chiffres).
    Formule officielle : FR + clé + SIREN, clé = (12 + 3 * (SIREN % 97)) % 97.
    Source : portail impots.gouv.fr. Retourne None si SIRET invalide.
    """
    if not siret or not siret.isdigit() or len(siret) != 14:
        return None
    siren = int(siret[:9])
    cle = (12 + 3 * (siren % 97)) % 97
    return f"FR{cle:02d}{siret[:9]}"


def _normalize_country(raw: Optional[str]) -> str:
    """CountryID CII = ISO 3166-1 alpha-2. On normalise 'France' -> 'FR'."""
    if not raw:
        return "FR"
    s = str(raw).strip().upper()
    if len(s) == 2:
        return s
    if s in ("FRANCE", "FRA"):
        return "FR"
    return "FR"


# ── Appels Karlia (lecture seule) ─────────────────────────────────────────

async def _fetch_karlia_document(api_key: str, document_id: int) -> Dict[str, Any]:
    url = f"{KARLIA_BASE}/documents/{document_id}"
    async with httpx.AsyncClient(timeout=30.0) as cli:
        r = await cli.get(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
    r.raise_for_status()
    return r.json()


async def _fetch_karlia_company(api_key: str) -> Dict[str, Any]:
    url = f"{KARLIA_BASE}/company"
    async with httpx.AsyncClient(timeout=30.0) as cli:
        r = await cli.get(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
    r.raise_for_status()
    return r.json()


async def _fetch_karlia_pdf(api_key: str, karlia_doc: Dict[str, Any]) -> bytes:
    pdf_url = karlia_doc.get("download_url")
    if not pdf_url:
        raise FacturxOrchestrationError("download_url absent du document Karlia.")
    headers = {"Authorization": f"Bearer {api_key}"} if "karlia" in pdf_url else {}
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as cli:
        r = await cli.get(pdf_url, headers=headers)
    r.raise_for_status()
    return r.content


# ── Mapping vers FactureInput ─────────────────────────────────────────────

def map_lignes(products_list: List[Dict[str, Any]]) -> List[LigneFacture]:
    """
    products_list Karlia -> liste de LigneFacture facturables.

    Filtrage : section != '1' (les sections '1' sont des titres/regroupements)
    ET total_without_tax > 0. PU net retenu = total_without_tax / quantity
    (intègre les remises déjà calculées par Karlia).
    """
    out: List[LigneFacture] = []
    rang = 0
    for entry in products_list or []:
        section_val = str(entry.get("section", "")).strip()
        total_ht = _to_decimal(entry.get("total_without_tax"))
        if section_val == "1":
            continue
        if total_ht <= Decimal("0"):
            continue
        qte = _to_decimal(entry.get("quantity"))
        if qte == Decimal("0"):
            qte = Decimal("1")
        pu_net = (total_ht / qte).quantize(Decimal("0.0001"))
        rang += 1
        out.append(
            LigneFacture(
                numero=rang,
                designation=(entry.get("title") or "Prestation").strip(),
                quantite=qte,
                prix_unitaire_ht=pu_net,
                taux_tva=_to_decimal(entry.get("vat") or "0"),
                unite="C62",
                reference=(entry.get("reference") or None) or None,
            )
        )
    return out


def build_emetteur(siret_emetteur: str, company: Dict[str, Any]) -> TradeParty:
    """
    SellerTradeParty depuis Karlia /company. Compose une TVA intracom calculée
    depuis le SIRET si Karlia ne la renvoie pas (BR-S-02 EN 16931).
    """
    nom = (
        company.get("name")
        or company.get("company_name")
        or company.get("legal_name")
        or "SGI INFORMATIQUE"
    ).strip()

    # Karlia /company renvoie 'address' comme dict imbriqué ; on accepte aussi
    # le format plat (champs au niveau racine) au cas où l'API évolue.
    addr_obj = company.get("address")
    if isinstance(addr_obj, dict):
        line1 = (addr_obj.get("address") or "").strip() or None
        zip_code = (addr_obj.get("zip_code") or addr_obj.get("postal_code") or "").strip() or None
        city = (addr_obj.get("city") or "").strip() or None
        country_raw = addr_obj.get("country") or addr_obj.get("country_code")
    else:
        line1 = company.get("address_1") or (addr_obj if isinstance(addr_obj, str) else None)
        if isinstance(line1, str):
            line1 = line1.strip() or None
        zip_code = company.get("zip_code") or company.get("postal_code") or None
        city = company.get("city") or None
        country_raw = company.get("country") or company.get("country_code")

    tva = (company.get("vat_number") or company.get("vat") or "").strip() or None
    if not tva:
        tva = _compute_fr_vat_number(siret_emetteur)
    if not tva:
        logger.warning(
            "TVA intracom émetteur indisponible (SIRET=%s). "
            "BR-S-02 EN 16931 fera rejeter le XML si une ligne est taxée standard.",
            siret_emetteur,
        )

    return TradeParty(
        nom=nom,
        siret=siret_emetteur,
        code_postal=zip_code,
        ville=city,
        adresse_ligne1=line1,
        pays=_normalize_country(country_raw),
        tva_intracom=tva,
    )


def build_destinataire(facture: FactureKarlia, client: Optional[ClientCache]) -> TradeParty:
    """BuyerTradeParty depuis le cache local (FactureKarlia + ClientCache)."""
    if client is None:
        return TradeParty(
            nom=facture.client_nom or "",
            siret=facture.client_siret or "",
            pays="FR",
        )
    return TradeParty(
        nom=client.nom or facture.client_nom or "",
        siret=facture.client_siret or client.siret or "",
        code_postal=client.code_postal,
        ville=client.ville,
        adresse_ligne1=client.adresse_ligne1,
        pays=_normalize_country(client.pays),
    )


def build_facture_input(
    facture: FactureKarlia,
    client: Optional[ClientCache],
    karlia_doc: Dict[str, Any],
    karlia_company: Dict[str, Any],
    siret_emetteur: str,
    payment_means: Optional[PaymentMeansInput] = None,
) -> FactureInput:
    """Assemble le FactureInput consommé par facturx_cii_builder."""
    date_end = _parse_date(karlia_doc.get("date_end"))
    # BT-10 BuyerReference : on laisse les deux sources à None pour que le
    # builder tombe sur le cas 3 (élément ram:BuyerReference absent du XML).
    # Karlia ne fournit pas de référence acheteur fiable (customer_reference
    # est libre côté fournisseur, code_service_destinataire pas garanti),
    # et BT-10 est optionnel en EN 16931 BASIC : "pas de référence" est
    # accepté par Chorus Pro. Pas de valeur bidon -> élément omis.
    return FactureInput(
        numero_facture=facture.numero_facture,
        date_facture=facture.date_facture,
        date_echeance=facture.date_echeance or date_end,
        emetteur=build_emetteur(siret_emetteur, karlia_company),
        destinataire=build_destinataire(facture, client),
        lignes=map_lignes(karlia_doc.get("products_list") or []),
        montant_ht_total=facture.montant_ht or Decimal("0"),
        montant_tva_total=facture.montant_tva or Decimal("0"),
        montant_ttc_total=facture.montant_ttc or Decimal("0"),
        numero_engagement=None,
        code_service_destinataire=None,
        payment_means=payment_means,
    )


# ── Accès DB ──────────────────────────────────────────────────────────────

def _load_param(db: Session, key: str) -> Optional[str]:
    p = db.query(Parametre).filter(Parametre.cle == key).first()
    return p.valeur if (p and p.valeur) else None


def _load_facture(db: Session, karlia_document_id: int) -> FactureKarlia:
    f = (
        db.query(FactureKarlia)
        .filter(FactureKarlia.karlia_document_id == karlia_document_id)
        .first()
    )
    if not f:
        raise FacturxOrchestrationError(
            f"FactureKarlia karlia_document_id={karlia_document_id} absente du cache local."
        )
    return f


def _load_client(db: Session, karlia_id: int) -> Optional[ClientCache]:
    return (
        db.query(ClientCache)
        .filter(ClientCache.karlia_id == str(karlia_id))
        .first()
    )


# ── API publique ──────────────────────────────────────────────────────────

async def build_facturx_for_karlia_document(
    db: Session,
    karlia_document_id: int,
) -> FacturxBuildResult:
    """
    Pipeline complet : Karlia + DB locale -> PDF Factur-X final (en mémoire).

    Args:
        db: session SQLAlchemy ouverte par l'appelant.
        karlia_document_id: identifiant du document Karlia (= FactureKarlia.karlia_document_id).

    Returns:
        FacturxBuildResult contenant le PDF Factur-X final et les artefacts
        intermédiaires (XML CII, PDF Karlia, PDF/A-3) pour traçage.

    Raises:
        FacturxOrchestrationError: paramètre/clé manquant ou ressource absente.
        Exception (factur-x): si le XML CII échoue à la validation XSD/Schematron.
    """
    # Paramètres en base (jamais .env, cf. règles projet)
    siret_emetteur = _load_param(db, "chorus_siret_emetteur")
    if not siret_emetteur:
        raise FacturxOrchestrationError("Paramètre 'chorus_siret_emetteur' absent ou vide en base.")
    api_key = _load_param(db, "karlia_api_key")
    if not api_key:
        raise FacturxOrchestrationError("Paramètre 'karlia_api_key' absent ou vide en base.")
    # Paramètres bancaires (optionnels). Si chorus_iban absent → bloc PaymentMeans
    # omis du XML (comportement actuel préservé).
    iban_param = _load_param(db, "chorus_iban")
    payment_means = PaymentMeansInput(
        iban=iban_param,
        bic=_load_param(db, "chorus_bic"),
        titulaire_compte=_load_param(db, "chorus_titulaire_compte"),
    ) if iban_param else None

    facture = _load_facture(db, karlia_document_id)
    client = _load_client(db, facture.client_karlia_id)

    logger.info(
        "Factur-X: démarrage pipeline pour facture %r (karlia_document_id=%s, client=%s)",
        facture.numero_facture, karlia_document_id, facture.client_nom,
    )

    # Karlia : métadonnées + identité émetteur + PDF source
    karlia_doc = await _fetch_karlia_document(api_key, karlia_document_id)
    karlia_company = await _fetch_karlia_company(api_key)
    pdf_karlia = await _fetch_karlia_pdf(api_key, karlia_doc)
    logger.info("Factur-X: PDF Karlia récupéré (%d bytes)", len(pdf_karlia))

    # Mapping
    facture_input = build_facture_input(
        facture, client, karlia_doc, karlia_company, siret_emetteur,
        payment_means=payment_means,
    )

    # Génération XML CII (warnings BR-CO-10/13 émis par le builder si écart)
    xml_cii_bytes = build_xml_cii_basic(facture_input)
    logger.info("Factur-X: XML CII généré (%d bytes)", len(xml_cii_bytes))

    # Normalisation PDF/A-3 via Ghostscript
    pdf_pdfa3_bytes = normalize_to_pdfa3(pdf_karlia)
    logger.info("Factur-X: PDF/A-3 normalisé (%d bytes)", len(pdf_pdfa3_bytes))

    # Assemblage final (validation XSD + schematron par la lib factur-x)
    pdf_facturx_bytes = package_facturx(pdf_pdfa3_bytes, xml_cii_bytes, level="basic", check_xsd=True)
    logger.info("Factur-X: PDF final assemblé (%d bytes)", len(pdf_facturx_bytes))

    return FacturxBuildResult(
        facture_input=facture_input,
        xml_cii_bytes=xml_cii_bytes,
        pdf_karlia_bytes=pdf_karlia,
        pdf_pdfa3_bytes=pdf_pdfa3_bytes,
        pdf_facturx_bytes=pdf_facturx_bytes,
    )
