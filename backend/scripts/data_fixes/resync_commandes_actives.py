"""
Re-synchronisation Karlia des commandes ACTIVES pour peupler les champs de
catégorisation manquants sur leurs lignes (section_karlia au premier chef,
+ id_product_category / product_category).

Contexte : commandes antérieures à l'arrivée du marqueur section_karlia →
lignes d'intitulé non marquées (section_karlia=NULL) → prestations parasites
remontant à tort dans l'écran d'affectation (cf D26-0498, D26-0472).

DEUX CHEMINS (le piège : _update_commande SUPPRIME+RÉINSÈRE les lignes, ce qui
orphelinerait les prestations via FK ON DELETE SET NULL) :

  - statut 'nouvelle' (0 prestation) : _update_commande tel quel (sûr).
  - statut 'a_planifier' / 'planifiee' (avec prestations) : UPDATE IN-PLACE.
    On relit Karlia (get_devis_detail), on apparie chaque ligne locale à un
    produit Karlia (par karlia_product_id, désambiguïsé par ordre), et on met
    à jour section_karlia / id_product_category / product_category SUR LA LIGNE
    EXISTANTE (aucun DELETE, aucun nouvel id → prestations préservées).

Karlia = source de vérité : on relit, on ne devine pas.

Modes (variables d'env) :
  - DRY_RUN (défaut) : aucun commit. Les chemins in-place font les appels
    Karlia en lecture seule pour calculer le diff ; le chemin 'nouvelle' ne
    fait AUCUN appel (juste un comptage).
  - APPLY=1 : applique et committe.

Rate limit : 1s entre deux commandes touchant Karlia.

    docker compose cp backend/scripts/data_fixes/resync_commandes_actives.py backend:/tmp/resync.py
    docker compose exec -T backend python3 /tmp/resync.py            # dry-run
    docker compose exec -T backend env APPLY=1 python3 /tmp/resync.py # apply
"""
import os
import asyncio
import logging

from app.core.database import SessionLocal
from app.models.models import Commande, CommandeLigne, Prestation
from app.services.karlia_devis_service import karlia_devis_service as svc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resync_commandes")

APPLY = os.environ.get("APPLY") == "1"
MODE = "APPLY" if APPLY else "DRY_RUN"
RATE_LIMIT_S = 1.0
STATUTS_CIBLE = ("nouvelle", "a_planifier", "planifiee")


def log(msg):
    print(msg, flush=True)
    logger.info(msg)


def _karlia_products_normalises(devis_detail, index, ref):
    """Normalise products_list Karlia → liste de dicts {idx, pid, section,
    cat_id, cat_nom, raw_section}, avec la MÊME logique que _update_commande."""
    out = []
    for idx, product in enumerate(devis_detail.get("products_list") or []):
        pid = str(product.get("id_product") or "")
        cat_id, cat_nom = index.get(pid, (None, None))
        out.append({
            "idx": idx,
            "pid": pid,
            "section": svc._parse_section(product.get("section"), ref),
            "cat_id": cat_id,
            "cat_nom": cat_nom,
            "raw_section": product.get("section"),
        })
    return out


def _apparier(lignes_triees, kprods):
    """Apparie chaque ligne locale à un produit Karlia.
    Priorité 1 : karlia_product_id ; ambiguïté (même pid) → priorité 2 : ordre.
    Retourne (pairs, lignes_non_appariees, produits_non_apparies)."""
    used = set()
    pairs = []
    lignes_orphelines = []
    for ligne in lignes_triees:
        lpid = ligne.karlia_product_id or ""
        cands = [k for k in kprods if k["pid"] == lpid and k["idx"] not in used]
        chosen = None
        if len(cands) == 1:
            chosen = cands[0]
        elif len(cands) > 1:
            # Désambiguïsation par ordre (intitulés partagent souvent pid '0').
            same_ordre = [k for k in cands if k["idx"] == ligne.ordre]
            if same_ordre:
                chosen = same_ordre[0]
            # sinon : ambigu → on NE touche pas, on signale.
        if chosen is None:
            lignes_orphelines.append(ligne)
        else:
            used.add(chosen["idx"])
            pairs.append((ligne, chosen))
    produits_orphelins = [k for k in kprods if k["idx"] not in used]
    return pairs, lignes_orphelines, produits_orphelins


def _diff_ligne(ligne, kprod):
    """Liste des champs à mettre à jour (val_locale → val_karlia)."""
    changes = []
    if ligne.section_karlia != kprod["section"]:
        changes.append(("section_karlia", ligne.section_karlia, kprod["section"]))
    if ligne.id_product_category != kprod["cat_id"]:
        changes.append(("id_product_category", ligne.id_product_category, kprod["cat_id"]))
    if (ligne.product_category or None) != (kprod["cat_nom"] or None):
        changes.append(("product_category", ligne.product_category, kprod["cat_nom"]))
    return changes


async def traiter_in_place(db, commande, index, stats):
    """Chemin a_planifier / planifiee : UPDATE in-place, sans delete."""
    ref = commande.reference_devis or f"id={commande.id}"
    detail = await svc.get_devis_detail(commande.karlia_document_id)
    if not detail:
        stats["erreurs"].append((ref, "get_devis_detail a renvoyé None (404 / vide)"))
        log(f"  [ERREUR] {ref} : aucun détail Karlia")
        return
    kprods = _karlia_products_normalises(detail, index, ref)
    lignes = sorted(commande.lignes, key=lambda l: ((l.ordre if l.ordre is not None else 0), l.id))
    pairs, lignes_orph, prods_orph = _apparier(lignes, kprods)

    nb_maj = 0
    for ligne, kprod in pairs:
        changes = _diff_ligne(ligne, kprod)
        if not changes:
            continue
        nb_maj += 1
        for champ, avant, apres in changes:
            log(f"    ligne#{ligne.id} ordre={ligne.ordre} [{(ligne.designation or '')[:30]}] "
                f"{champ}: {avant!r} → {apres!r}")
            if champ == "section_karlia":
                if avant is None and apres == 1:
                    stats["sec_null_to_1"] += 1
                elif avant is None and apres == 0:
                    stats["sec_null_to_0"] += 1
            if champ == "id_product_category":
                stats["cat_changes"] += 1
        if APPLY:
            ligne.section_karlia = kprod["section"]
            ligne.id_product_category = kprod["cat_id"]
            ligne.product_category = kprod["cat_nom"]

    for ligne in lignes_orph:
        stats["lignes_non_appariees"].append(
            (ref, ligne.id, ligne.ordre, (ligne.designation or "")[:30], ligne.karlia_product_id))
        log(f"  [NON APPARIÉE] {ref} ligne#{ligne.id} ordre={ligne.ordre} "
            f"pid={ligne.karlia_product_id!r} — non touchée")
    for kp in prods_orph:
        stats["produits_non_apparies"].append((ref, kp["idx"], kp["pid"]))

    statut_tag = "MAJ" if nb_maj else "rien à changer"
    log(f"  [{commande.statut}] {ref} : {len(lignes)} ligne(s), {nb_maj} à mettre à jour "
        f"({statut_tag}){' [APPLIQUÉ]' if (APPLY and nb_maj) else ''}")
    if APPLY and nb_maj:
        commande.updated_at = __import__("datetime").datetime.utcnow()
        db.commit()
        stats["cmd_touchees"] += 1
    stats["lignes_maj"] += nb_maj


async def main():
    db = SessionLocal()
    log(f"===== RESYNC COMMANDES ACTIVES — MODE {MODE} =====")
    prest_avant = db.query(Prestation).count()
    log(f"Prestations en base (avant) : {prest_avant}")

    index = svc._build_articles_categorie_index(db)
    log(f"Index catégories articles : {len(index)} entrées")

    commandes = (db.query(Commande)
                 .filter(Commande.statut.in_(STATUTS_CIBLE),
                         Commande.karlia_document_id.isnot(None))
                 .order_by(Commande.statut, Commande.id)
                 .all())

    nouvelles = [c for c in commandes if c.statut == "nouvelle"]
    in_place = [c for c in commandes if c.statut in ("a_planifier", "planifiee")]
    log(f"Périmètre : {len(commandes)} commandes "
        f"({len(nouvelles)} 'nouvelle' → _update_commande, "
        f"{len(in_place)} 'a_planifier/planifiee' → UPDATE in-place)")

    stats = {
        "cmd_touchees": 0, "lignes_maj": 0,
        "sec_null_to_1": 0, "sec_null_to_0": 0, "cat_changes": 0,
        "lignes_non_appariees": [], "produits_non_apparies": [], "erreurs": [],
    }

    # ── Chemin 'nouvelle' ────────────────────────────────────────────────────
    log("\n--- Commandes 'nouvelle' (0 prestation → _update_commande) ---")
    if not APPLY:
        log(f"  [DRY-RUN] {len(nouvelles)} commande(s) 'nouvelle' seraient "
            f"resynchronisées via _update_commande (delete+reinsert, sûr car 0 "
            f"prestation). Aucun appel Karlia en dry-run.")
    else:
        for c in nouvelles:
            ref = c.reference_devis or f"id={c.id}"
            # Sécurité : ne JAMAIS passer ici une commande avec prestations.
            if db.query(Prestation).filter(Prestation.commande_id == c.id).count() > 0:
                stats["erreurs"].append((ref, "SKIP : 'nouvelle' avec prestations (anormal)"))
                log(f"  [SKIP] {ref} : prestations présentes, _update_commande non appliqué")
                continue
            try:
                await svc._update_commande(db, c, {"id": c.karlia_document_id}, articles_cat_index=index)
                stats["cmd_touchees"] += 1
                log(f"  [OK] {ref} resynchronisée")
            except Exception as e:
                stats["erreurs"].append((ref, f"_update_commande: {e}"))
                log(f"  [ERREUR] {ref} : {e}")
            await asyncio.sleep(RATE_LIMIT_S)

    # ── Chemin in-place ──────────────────────────────────────────────────────
    log("\n--- Commandes 'a_planifier' / 'planifiee' (UPDATE in-place) ---")
    for c in in_place:
        try:
            await traiter_in_place(db, c, index, stats)
        except Exception as e:
            ref = c.reference_devis or f"id={c.id}"
            stats["erreurs"].append((ref, f"in-place: {e}"))
            log(f"  [ERREUR] {ref} : {e}")
        await asyncio.sleep(RATE_LIMIT_S)

    # ── Récap ────────────────────────────────────────────────────────────────
    prest_apres = db.query(Prestation).count()
    log("\n===== RÉCAP =====")
    log(f"Mode : {MODE}")
    log(f"Commandes 'nouvelle' : {len(nouvelles)}")
    log(f"Commandes in-place    : {len(in_place)}")
    log(f"Commandes touchées (committées) : {stats['cmd_touchees']}")
    log(f"Lignes mises à jour : {stats['lignes_maj']}")
    log(f"  dont section_karlia NULL→1 : {stats['sec_null_to_1']}")
    log(f"  dont section_karlia NULL→0 : {stats['sec_null_to_0']}")
    log(f"  dont id_product_category modifié : {stats['cat_changes']}")
    log(f"Lignes non appariées (non touchées) : {len(stats['lignes_non_appariees'])}")
    log(f"Produits Karlia non appariés : {len(stats['produits_non_apparies'])}")
    log(f"Erreurs : {len(stats['erreurs'])}")
    for ref, msg in stats["erreurs"]:
        log(f"    - {ref} : {msg}")
    log(f"Prestations en base : avant={prest_avant}  après={prest_apres}  "
        f"{'OK (identique)' if prest_avant == prest_apres else 'ALERTE : DIFFÉRENT !'}")
    if not APPLY:
        log("\n[DRY-RUN] Aucune modification écrite. Relancer avec APPLY=1 pour appliquer.")

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
