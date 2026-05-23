"""
Assemblage Factur-X : prend un PDF/A-3 + un XML CII et produit un PDF Factur-X
(PDF/A-3 avec XML embarqué en AssociatedFiles).

Wrapper minimal au-dessus de la librairie `factur-x` (>=4.x). On utilise
des fichiers temporaires car la lib opère sur des chemins.

Le contrôle XSD de la lib est ACTIVÉ (check_xsd=True) : le XML produit
par facturx_cii_builder est validé contre le schéma CII Factur-X officiel
au moment de l'assemblage ; toute erreur de structure remonte ici.
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Literal

import facturx

logger = logging.getLogger(__name__)

FacturxLevel = Literal["minimum", "basicwl", "basic", "en16931", "extended"]


def package_facturx(
    pdf_pdfa3_bytes: bytes,
    xml_cii_bytes: bytes,
    level: FacturxLevel = "basic",
    check_xsd: bool = True,
) -> bytes:
    """
    Assemble le Factur-X final.

    Args:
        pdf_pdfa3_bytes: PDF/A-3 produit par `pdfa3_normalizer.normalize_to_pdfa3`.
        xml_cii_bytes  : XML CII produit par `facturx_cii_builder.build_xml_cii_basic`.
        level          : niveau Factur-X. "basic" par défaut (cohérent avec le builder).
        check_xsd      : validation XSD du XML CII par la lib factur-x.

    Returns:
        Le PDF Factur-X (PDF/A-3 + XML embarqué) sous forme d'octets.

    Raises:
        ValueError, RuntimeError : si la lib factur-x rejette l'assemblage
        (XML non conforme XSD, PDF source invalide, etc.).
    """
    if not pdf_pdfa3_bytes.startswith(b"%PDF-"):
        raise ValueError("L'entrée pdf_pdfa3_bytes ne commence pas par '%PDF-'.")
    if not xml_cii_bytes.lstrip().startswith(b"<?xml"):
        raise ValueError("L'entrée xml_cii_bytes ne ressemble pas à un document XML.")

    with tempfile.TemporaryDirectory(prefix="facturx_pack_") as workdir:
        in_pdf = os.path.join(workdir, "in.pdf")
        out_pdf = os.path.join(workdir, "out.pdf")

        with open(in_pdf, "wb") as f:
            f.write(pdf_pdfa3_bytes)

        logger.info(
            "facturx.generate_from_file(level=%s, check_xsd=%s, pdf_in=%d bytes, xml=%d bytes)",
            level, check_xsd, len(pdf_pdfa3_bytes), len(xml_cii_bytes),
        )
        facturx.generate_from_file(
            in_pdf,
            xml_cii_bytes,
            output_pdf_file=out_pdf,
            flavor="factur-x",
            level=level,
            check_xsd=check_xsd,
        )
        if not os.path.exists(out_pdf):
            raise RuntimeError("facturx.generate_from_file n'a pas produit de fichier de sortie.")
        with open(out_pdf, "rb") as f:
            return f.read()
