"""
Génération XML CII Factur-X — profil BASIC (EN 16931 compliant).

Voie de transmission Chorus Pro : POST /cpro/factures/v1/deposer/flux
(syntaxe IN_DP_E2_CII_FACTURX). Le XML produit ici est destiné à être
embarqué dans un PDF/A-3 via la librairie factur-x.

Profil BASIC = EN 16931 minimum avec lignes :
  GuidelineSpecifiedDocumentContextParameter/ID
    = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic"

Le builder est isolé : aucune dépendance ORM/DB, il prend des arguments
explicites pour rester testable et réutilisable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from lxml import etree

logger = logging.getLogger(__name__)


# ── Namespaces CII / Factur-X ──────────────────────────────────────────────
NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}

GUIDELINE_BASIC = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic"
BUSINESS_PROCESS_A1 = "A1"   # Dépôt direct fournisseur (Chorus Pro)
TYPE_CODE_FACTURE = "380"    # CII Document Type : Facture commerciale
SCHEME_SIRET = "0002"         # ISO 6523 : SIREN/SIRET France
COUNTRY_FR = "FR"
CURRENCY_EUR = "EUR"
VAT_TYPE_CODE = "VAT"
VAT_CATEGORY_STANDARD = "S"   # Standard rate


# ── Modèles d'entrée (dataclasses, pas d'ORM) ──────────────────────────────

@dataclass
class TradeParty:
    """Partie au commerce (émetteur ou destinataire)."""
    nom: str
    siret: str                                 # 14 chiffres, sans espaces
    code_postal: Optional[str] = None
    ville: Optional[str] = None
    adresse_ligne1: Optional[str] = None
    pays: str = COUNTRY_FR
    tva_intracom: Optional[str] = None         # ex. "FR00531891307" (côté émetteur)


@dataclass
class LigneFacture:
    """Ligne de facture (mappée vers IncludedSupplyChainTradeLineItem)."""
    numero: int                                # ordre 1..N
    designation: str
    quantite: Decimal
    prix_unitaire_ht: Decimal
    taux_tva: Decimal                          # ex. Decimal("20.00")
    unite: str = "C62"                         # UNECE Recommendation 20 : "C62" = unit
    reference: Optional[str] = None            # SellerAssignedID éventuel

    def montant_ligne_ht(self) -> Decimal:
        return (self.quantite * self.prix_unitaire_ht).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class FactureInput:
    """
    Description complète d'une facture pour génération CII BASIC.

    Stratégie BT-10 (BuyerReference) — référence acheteur côté collectivité,
    pas une donnée fournisseur :
      1) numero_engagement renseigné -> BT-10 = numero_engagement
      2) sinon code_service_destinataire renseigné -> BT-10 = code_service_destinataire
      3) sinon -> BT-10 n'est PAS émis dans le XML (élément absent).
    On ne met JAMAIS le numéro de facture en BT-10 : c'est une donnée
    fournisseur, mettre une fausse valeur acheteur peut entraîner rejet ou
    mauvais acheminement côté Chorus Pro.
    """
    numero_facture: str
    date_facture: date
    date_echeance: Optional[date]
    emetteur: TradeParty
    destinataire: TradeParty
    lignes: List[LigneFacture] = field(default_factory=list)
    montant_ht_total: Decimal = Decimal("0")
    montant_tva_total: Decimal = Decimal("0")
    montant_ttc_total: Decimal = Decimal("0")
    # Référence acheteur (BT-10) — voir stratégie dans la docstring de la classe.
    numero_engagement: Optional[str] = None
    code_service_destinataire: Optional[str] = None


# ── Helpers d'écriture XML ─────────────────────────────────────────────────

def _qn(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _sub(parent, prefix_tag: str, text=None, attrib: Optional[dict] = None):
    prefix, tag = prefix_tag.split(":", 1)
    el = etree.SubElement(parent, _qn(prefix, tag), attrib=attrib or {})
    if text is not None:
        el.text = str(text)
    return el


def _fmt_money(d: Decimal) -> str:
    """Montant CII : toujours 2 décimales, point, pas de séparateur de milliers."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _fmt_qty(d: Decimal) -> str:
    """Quantité CII : 4 décimales max (laisse strip des zéros utile)."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return f"{d.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):.4f}"


def _fmt_percent(d: Decimal) -> str:
    """Taux TVA : pourcentage avec 2 décimales."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _fmt_date_102(d: date) -> str:
    return d.strftime("%Y%m%d")


def _resolve_buyer_reference(facture: "FactureInput") -> Optional[str]:
    """
    Stratégie BT-10 BuyerReference (cf. docstring FactureInput).
    Retourne la valeur à émettre, ou None pour ne PAS émettre l'élément.
    """
    if facture.numero_engagement:
        return facture.numero_engagement.strip() or None
    if facture.code_service_destinataire:
        return facture.code_service_destinataire.strip() or None
    return None


# ── Construction des blocs CII ─────────────────────────────────────────────

def _build_document_context(root):
    ctx = _sub(root, "rsm:ExchangedDocumentContext")
    bp = _sub(ctx, "ram:BusinessProcessSpecifiedDocumentContextParameter")
    _sub(bp, "ram:ID", BUSINESS_PROCESS_A1)
    gp = _sub(ctx, "ram:GuidelineSpecifiedDocumentContextParameter")
    _sub(gp, "ram:ID", GUIDELINE_BASIC)


def _build_document(root, facture: FactureInput):
    doc = _sub(root, "rsm:ExchangedDocument")
    _sub(doc, "ram:ID", facture.numero_facture)
    _sub(doc, "ram:TypeCode", TYPE_CODE_FACTURE)
    dt = _sub(doc, "ram:IssueDateTime")
    _sub(dt, "udt:DateTimeString", _fmt_date_102(facture.date_facture), {"format": "102"})


def _build_trade_party(parent_el, party: TradeParty, with_tva_intra: bool):
    p = _sub(parent_el, "ram:SellerTradeParty" if with_tva_intra else "ram:BuyerTradeParty")
    _sub(p, "ram:Name", party.nom)
    legal = _sub(p, "ram:SpecifiedLegalOrganization")
    _sub(legal, "ram:ID", party.siret, {"schemeID": SCHEME_SIRET})
    if any([party.adresse_ligne1, party.code_postal, party.ville, party.pays]):
        addr = _sub(p, "ram:PostalTradeAddress")
        if party.code_postal:
            _sub(addr, "ram:PostcodeCode", party.code_postal)
        if party.adresse_ligne1:
            _sub(addr, "ram:LineOne", party.adresse_ligne1)
        if party.ville:
            _sub(addr, "ram:CityName", party.ville)
        _sub(addr, "ram:CountryID", party.pays)
    if with_tva_intra and party.tva_intracom:
        tax = _sub(p, "ram:SpecifiedTaxRegistration")
        _sub(tax, "ram:ID", party.tva_intracom, {"schemeID": "VA"})


def _build_line(transaction_el, ligne: LigneFacture):
    line = _sub(transaction_el, "ram:IncludedSupplyChainTradeLineItem")

    # Identifiant de ligne
    assoc = _sub(line, "ram:AssociatedDocumentLineDocument")
    _sub(assoc, "ram:LineID", str(ligne.numero))

    # Produit — profil BASIC restreint SpecifiedTradeProduct à (GlobalID?, Name).
    # SellerAssignedID n'est PAS autorisé en BASIC (réservé EN 16931/EXTENDED),
    # le XSD le rejette. On ignore donc ligne.reference ici ; ce champ sera
    # utilisable si on passe à un profil supérieur.
    product = _sub(line, "ram:SpecifiedTradeProduct")
    _sub(product, "ram:Name", ligne.designation)

    # Prix net unitaire
    agreement = _sub(line, "ram:SpecifiedLineTradeAgreement")
    net_price = _sub(agreement, "ram:NetPriceProductTradePrice")
    _sub(net_price, "ram:ChargeAmount", _fmt_money(ligne.prix_unitaire_ht))

    # Quantité facturée
    delivery = _sub(line, "ram:SpecifiedLineTradeDelivery")
    _sub(delivery, "ram:BilledQuantity", _fmt_qty(ligne.quantite), {"unitCode": ligne.unite})

    # Règlement ligne : TVA ligne + total ligne HT
    settlement = _sub(line, "ram:SpecifiedLineTradeSettlement")
    tax_line = _sub(settlement, "ram:ApplicableTradeTax")
    _sub(tax_line, "ram:TypeCode", VAT_TYPE_CODE)
    _sub(tax_line, "ram:CategoryCode", VAT_CATEGORY_STANDARD)
    _sub(tax_line, "ram:RateApplicablePercent", _fmt_percent(ligne.taux_tva))
    sum_line = _sub(settlement, "ram:SpecifiedTradeSettlementLineMonetarySummation")
    _sub(sum_line, "ram:LineTotalAmount", _fmt_money(ligne.montant_ligne_ht()))


def _build_header_trade_agreement(transaction_el, facture: FactureInput):
    agreement = _sub(transaction_el, "ram:ApplicableHeaderTradeAgreement")

    # BT-10 BuyerReference : émis SEULEMENT si on a une vraie référence acheteur
    # (engagement ou code service destinataire). Sinon élément absent — voir
    # FactureInput docstring pour la justification.
    buyer_ref = _resolve_buyer_reference(facture)
    if buyer_ref:
        _sub(agreement, "ram:BuyerReference", buyer_ref)
        logger.debug(
            "BuyerReference émis : %r (source=%s)",
            buyer_ref,
            "numero_engagement" if facture.numero_engagement else "code_service_destinataire",
        )
    else:
        logger.debug(
            "BuyerReference NON émis (ni numero_engagement ni code_service_destinataire fournis)."
        )

    _build_trade_party(agreement, facture.emetteur, with_tva_intra=True)
    _build_trade_party(agreement, facture.destinataire, with_tva_intra=False)


def _build_header_trade_delivery(transaction_el, facture: FactureInput):
    """
    ApplicableHeaderTradeDelivery (BG-13) — obligatoire dans la séquence CII
    SupplyChainTradeTransaction, mais le schematron EN 16931
    (PEPPOL-EN16931-R008) interdit qu'il soit vide. On émet donc au minimum
    ActualDeliverySupplyChainEvent/OccurrenceDateTime à la date de facture
    (livraison effective = date d'émission pour une prestation immédiate),
    convention conforme EN 16931 BT-72.
    """
    delivery = _sub(transaction_el, "ram:ApplicableHeaderTradeDelivery")
    event = _sub(delivery, "ram:ActualDeliverySupplyChainEvent")
    occ = _sub(event, "ram:OccurrenceDateTime")
    _sub(occ, "udt:DateTimeString", _fmt_date_102(facture.date_facture), {"format": "102"})


def _check_coherence_ht_lignes(facture: FactureInput) -> None:
    """
    Vérification BR-CO-10 / BR-CO-13 : somme des LineTotalAmount = TaxBasisTotalAmount.

    Le builder NE corrige PAS silencieusement les écarts — il logge un
    avertissement explicite. Un écart ferait rejeter le XML par le validateur
    EN 16931 ou par Chorus Pro en aval ; on veut le voir avant le dépôt.
    """
    if not facture.lignes:
        return
    somme_lignes = sum((l.montant_ligne_ht() for l in facture.lignes), Decimal("0"))
    somme_lignes = somme_lignes.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_header = facture.montant_ht_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) \
        if isinstance(facture.montant_ht_total, Decimal) \
        else Decimal(str(facture.montant_ht_total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ecart = (somme_lignes - total_header).copy_abs()
    if ecart > Decimal("0.00"):
        logger.warning(
            "Écart de cohérence HT (BR-CO-10/13) sur facture %r : "
            "somme(lignes HT) = %s EUR, montant_ht_total header = %s EUR, "
            "écart = %s EUR. XML émis tel quel — un écart fait rejeter le "
            "document par EN 16931 et/ou Chorus Pro.",
            facture.numero_facture,
            _fmt_money(somme_lignes),
            _fmt_money(total_header),
            _fmt_money(ecart),
        )


def _build_header_trade_settlement(transaction_el, facture: FactureInput):
    settlement = _sub(transaction_el, "ram:ApplicableHeaderTradeSettlement")
    _sub(settlement, "ram:InvoiceCurrencyCode", CURRENCY_EUR)

    # Cohérence HT lignes vs header : warning explicite si écart (pas de fix silencieux).
    _check_coherence_ht_lignes(facture)

    # Récap TVA par taux : ici un seul taux est dérivé du taux de la première ligne
    # (cas usuel SGI : 20% sur la totalité). Si plusieurs taux apparaissaient
    # côté lignes, il faudrait grouper par taux et émettre plusieurs blocs.
    taux_distincts = sorted({ligne.taux_tva for ligne in facture.lignes}) if facture.lignes else [Decimal("20.00")]
    for taux in taux_distincts:
        base_taux = sum(
            (l.montant_ligne_ht() for l in facture.lignes if l.taux_tva == taux),
            Decimal("0"),
        )
        # En présence d'un seul taux sur l'ensemble des lignes, on aligne le
        # récap sur les totaux header (montant_ht_total / montant_tva_total)
        # pour éviter les micro-écarts d'arrondi de calcul ligne par ligne.
        # Si la cohérence n'est pas respectée, _check_coherence_ht_lignes a
        # déjà émis un warning explicite ci-dessus.
        if len(taux_distincts) == 1:
            base_taux = facture.montant_ht_total
            tva_taux = facture.montant_tva_total
        else:
            tva_taux = (base_taux * taux / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        tax = _sub(settlement, "ram:ApplicableTradeTax")
        _sub(tax, "ram:CalculatedAmount", _fmt_money(tva_taux))
        _sub(tax, "ram:TypeCode", VAT_TYPE_CODE)
        _sub(tax, "ram:BasisAmount", _fmt_money(base_taux))
        _sub(tax, "ram:CategoryCode", VAT_CATEGORY_STANDARD)
        _sub(tax, "ram:RateApplicablePercent", _fmt_percent(taux))

    # Conditions de paiement (échéance)
    if facture.date_echeance is not None:
        terms = _sub(settlement, "ram:SpecifiedTradePaymentTerms")
        due = _sub(terms, "ram:DueDateDateTime")
        _sub(due, "udt:DateTimeString", _fmt_date_102(facture.date_echeance), {"format": "102"})

    # Synthèse monétaire (obligatoire BASIC)
    summary = _sub(settlement, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    # LineTotalAmount = somme des LineTotalAmount des lignes
    if facture.lignes:
        line_total = sum((l.montant_ligne_ht() for l in facture.lignes), Decimal("0"))
    else:
        line_total = facture.montant_ht_total
    _sub(summary, "ram:LineTotalAmount", _fmt_money(line_total))
    _sub(summary, "ram:ChargeTotalAmount", _fmt_money(Decimal("0")))
    _sub(summary, "ram:AllowanceTotalAmount", _fmt_money(Decimal("0")))
    _sub(summary, "ram:TaxBasisTotalAmount", _fmt_money(facture.montant_ht_total))
    _sub(summary, "ram:TaxTotalAmount", _fmt_money(facture.montant_tva_total), {"currencyID": CURRENCY_EUR})
    _sub(summary, "ram:GrandTotalAmount", _fmt_money(facture.montant_ttc_total))
    _sub(summary, "ram:TotalPrepaidAmount", _fmt_money(Decimal("0")))
    _sub(summary, "ram:DuePayableAmount", _fmt_money(facture.montant_ttc_total))


# ── API publique ──────────────────────────────────────────────────────────

def build_xml_cii_basic(facture: FactureInput) -> bytes:
    """
    Construit le XML CII Factur-X niveau BASIC, retourne les octets UTF-8.

    Validation amont : tous les champs requis EN 16931 BASIC doivent être
    présents dans `facture`. Le builder n'effectue pas de validation XSD ici ;
    la validation est faite en aval par la lib factur-x lors de l'assemblage
    (check_xsd=True dans facturx_packager).
    """
    root = etree.Element(_qn("rsm", "CrossIndustryInvoice"), nsmap=NS)
    _build_document_context(root)
    _build_document(root, facture)

    transaction = _sub(root, "rsm:SupplyChainTradeTransaction")
    for ligne in facture.lignes:
        _build_line(transaction, ligne)
    _build_header_trade_agreement(transaction, facture)
    _build_header_trade_delivery(transaction, facture)
    _build_header_trade_settlement(transaction, facture)

    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        standalone=False,
    )
