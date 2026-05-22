"""
Normalisation d'un PDF en PDF/A-3 via Ghostscript.

Ce module est volontairement minimal :
  - une fonction publique `normalize_to_pdfa3(pdf_in_bytes) -> bytes`
  - une vérification post-normalisation `inspect_pdfa3(pdf_bytes) -> dict`

Prérequis runtime : binaire `gs` installé dans l'image (cf. Dockerfile),
plus le profil ICC sRGB livré avec ghostscript (dans
/usr/share/ghostscript/<version>/iccprofiles/).

Pourquoi cette étape ? Les PDF générés par dompdf (Karlia) ne sont pas
PDF/A : polices PostScript non embarquées, pas de métadonnées XMP pdfaid,
pas d'OutputIntent. Pour un Factur-X conforme, on doit produire un PDF/A-3
puis y embarquer le XML CII via la lib factur-x.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional

import pikepdf

logger = logging.getLogger(__name__)


GS_BIN = "gs"

# Le PDFA_def.ps est un fichier PostScript d'amorçage utilisé par Ghostscript
# en mode -dPDFA. Il déclare l'OutputIntent et pointe vers le profil ICC sRGB
# à embarquer. Ghostscript fournit lui-même un profil ICC dans son répertoire
# de ressources ; on le localise dynamiquement pour rester portable.
ICC_CANDIDATES_GLOBS = [
    "/usr/share/ghostscript/*/iccprofiles/default_rgb.icc",
    "/usr/share/ghostscript/*/iccprofiles/srgb.icc",
    "/usr/share/color/icc/sRGB.icc",
    "/usr/share/color/icc/colord/sRGB.icc",
]


def _find_icc_profile() -> str:
    for pattern in ICC_CANDIDATES_GLOBS:
        if "*" in pattern:
            matches = sorted(glob.glob(pattern))
            if matches:
                return matches[0]
        elif os.path.exists(pattern):
            return pattern
    raise RuntimeError(
        "Aucun profil ICC sRGB trouvé sur le système. "
        "Vérifier l'installation ghostscript (apt-get install ghostscript)."
    )


def _build_pdfa_def_ps(icc_path: str) -> str:
    """
    PDFA_def.ps minimal — déclare un OutputIntent sRGB.

    Note Ghostscript : le chemin du fichier ICC doit utiliser des séparateurs
    PostScript ('/'). On échappe les éventuelles parenthèses.
    """
    safe_icc = icc_path.replace("(", r"\(").replace(")", r"\)")
    return f"""\
%!
% PDFA_def.ps - genere par pdfa3_normalizer.py
% Declare un OutputIntent sRGB pour la conversion PDF/A-3.

[/_objdef {{icc_PDFA}} /type /stream /OBJ pdfmark
[{{icc_PDFA}} <</N 3>> /PUT pdfmark
[{{icc_PDFA}} ({safe_icc}) (r) file /PUT pdfmark

[/_objdef {{OutputIntent_PDFA}} /type /dict /OBJ pdfmark
[{{OutputIntent_PDFA}} <<
  /Type /OutputIntent
  /S /GTS_PDFA1
  /DestOutputProfile {{icc_PDFA}}
  /OutputConditionIdentifier (sRGB IEC61966-2.1)
  /Info (sRGB IEC61966-2.1)
>> /PUT pdfmark

[{{Catalog}} <</OutputIntents [ {{OutputIntent_PDFA}} ]>> /PUT pdfmark
"""


# ── Vérification post-normalisation ────────────────────────────────────────

@dataclass
class PdfaInspectResult:
    pdf_version: str
    pdfaid_part: Optional[str]
    pdfaid_conformance: Optional[str]
    has_output_intent: bool
    fonts_total: int
    fonts_embedded: int
    fonts_not_embedded: List[str]

    @property
    def is_pdfa3(self) -> bool:
        return self.pdfaid_part == "3"

    @property
    def all_fonts_embedded(self) -> bool:
        return self.fonts_total > 0 and self.fonts_embedded == self.fonts_total


def inspect_pdfa3(pdf_bytes: bytes) -> PdfaInspectResult:
    """Inspection rapide d'un PDF pour confirmer sa conformité PDF/A-3."""
    import io
    p = pikepdf.open(io.BytesIO(pdf_bytes))

    # XMP -> pdfaid:part / conformance
    pdfaid_part = None
    pdfaid_conformance = None
    try:
        if "/Metadata" in p.Root.keys():
            xmp = bytes(p.Root.Metadata.read_bytes()).decode("utf-8", errors="replace")
            m = re.search(r"<pdfaid:part>([^<]+)</pdfaid:part>", xmp)
            if m:
                pdfaid_part = m.group(1)
            m = re.search(r"<pdfaid:conformance>([^<]+)</pdfaid:conformance>", xmp)
            if m:
                pdfaid_conformance = m.group(1)
    except Exception as exc:
        logger.warning("Lecture XMP impossible : %s", exc)

    # OutputIntent
    has_oi = False
    try:
        oi = p.Root.get("/OutputIntents")
        has_oi = bool(oi) and len(list(oi)) > 0
    except Exception:
        pass

    # Polices
    seen = {}
    for page in p.pages:
        try:
            fonts = page.resources.get("/Font")
            if fonts is None:
                continue
            for fname, font_obj in dict(fonts).items():
                key = str(fname)
                if key in seen:
                    continue
                base = font_obj.get("/BaseFont")
                desc = font_obj.get("/FontDescriptor")
                descendants = font_obj.get("/DescendantFonts")
                if descendants:
                    try:
                        desc = descendants[0].get("/FontDescriptor")
                    except Exception:
                        pass
                embedded = False
                if desc:
                    for k in ("/FontFile", "/FontFile2", "/FontFile3"):
                        if desc.get(k) is not None:
                            embedded = True
                            break
                seen[key] = (str(base) if base else key, embedded)
        except Exception as exc:
            logger.debug("Erreur lecture polices : %s", exc)

    total = len(seen)
    embedded_n = sum(1 for _, e in seen.values() if e)
    not_embedded = [n for _, (n, e) in seen.items() if not e]

    return PdfaInspectResult(
        pdf_version=p.pdf_version,
        pdfaid_part=pdfaid_part,
        pdfaid_conformance=pdfaid_conformance,
        has_output_intent=has_oi,
        fonts_total=total,
        fonts_embedded=embedded_n,
        fonts_not_embedded=not_embedded,
    )


# ── API publique : normalisation ───────────────────────────────────────────

def normalize_to_pdfa3(pdf_in_bytes: bytes) -> bytes:
    """
    Convertit un PDF arbitraire en PDF/A-3 via Ghostscript.

    Args:
        pdf_in_bytes: contenu du PDF source.

    Returns:
        Le PDF/A-3 sous forme d'octets. La conformité réelle doit être
        vérifiée par `inspect_pdfa3` après cet appel.

    Raises:
        RuntimeError: si gs n'est pas disponible, ou si la conversion échoue.
        FileNotFoundError: si aucun profil ICC sRGB n'est trouvé.
    """
    icc_path = _find_icc_profile()
    logger.info("Profil ICC sRGB retenu : %s", icc_path)

    with tempfile.TemporaryDirectory(prefix="pdfa3_") as workdir:
        in_path = os.path.join(workdir, "in.pdf")
        out_path = os.path.join(workdir, "out.pdf")
        defps_path = os.path.join(workdir, "PDFA_def.ps")

        with open(in_path, "wb") as f:
            f.write(pdf_in_bytes)
        with open(defps_path, "w", encoding="ascii") as f:
            f.write(_build_pdfa_def_ps(icc_path))

        cmd = [
            GS_BIN,
            "-dPDFA=3",
            "-dBATCH",
            "-dNOPAUSE",
            "-dNOOUTERSAVE",
            "-sColorConversionStrategy=RGB",
            "-sDEVICE=pdfwrite",
            "-dPDFACompatibilityPolicy=1",
            "-dPDFSETTINGS=/printer",
            f"-sOutputFile={out_path}",
            defps_path,
            in_path,
        ]
        logger.info("ghostscript : %s", " ".join(cmd))
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "ghostscript a échoué "
                f"(returncode={proc.returncode})\nstdout:\n{proc.stdout.decode('utf-8', 'replace')}\n"
                f"stderr:\n{proc.stderr.decode('utf-8', 'replace')}"
            )
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("ghostscript n'a pas produit de fichier de sortie exploitable.")

        with open(out_path, "rb") as f:
            return f.read()
