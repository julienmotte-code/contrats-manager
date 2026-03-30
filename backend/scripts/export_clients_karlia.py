#!/usr/bin/env python3
"""
Export clients vers Karlia avec gestion du quota (100/heure).
Fait 85 clients puis attend 1h, en boucle.
"""
import sys
import os
import time
import httpx
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.models import ClientCache, Parametre

KARLIA_URL = settings.KARLIA_API_URL.rstrip('/')
BATCH_SIZE = 85  # clients par heure (marge sous 100)
DELAY_BETWEEN_REQUESTS = 2.0  # 2 sec entre chaque requête dans un lot
WAIT_BETWEEN_BATCHES = 3660  # 61 minutes entre lots


def get_api_key(db):
    param = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
    return param.valeur if param and param.valeur else ""


def create_customer_in_karlia(client, api_key: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "name": client.nom,
        "individual": 0,
        "prospect": 0,
        "client_number": client.numero_client or "",
        "email": client.email or "",
        "phone": client.telephone or "",
        "mobile": client.mobile or "",
        "siret": client.siret or "",
        "vat_number": client.tva_intracom or "",
        "legal_form": client.forme_juridique or "",
    }
    
    if client.adresse_ligne1 or client.ville:
        payload["address_list"] = [{
            "type": "main",
            "address": client.adresse_ligne1 or "",
            "zip_code": client.code_postal or "",
            "city": client.ville or "",
            "country": client.pays or "France"
        }]
    
    with httpx.Client(timeout=30.0) as http:
        resp = http.post(f"{KARLIA_URL}/customers", headers=headers, json=payload)
        return {
            "ok": resp.status_code in [200, 201],
            "status": resp.status_code,
            "data": resp.json() if resp.status_code in [200, 201] else None,
            "error": resp.text[:100] if resp.status_code not in [200, 201] else None
        }


def get_pending_clients(db, limit=None):
    """Clients non synchronisés ou synchro ancienne."""
    cutoff = datetime(2026, 3, 27, 17, 0, tzinfo=timezone.utc)
    query = db.query(ClientCache).filter(
        (ClientCache.synchro_at == None) | (ClientCache.synchro_at < cutoff)
    ).order_by(ClientCache.numero_client)
    if limit:
        query = query.limit(limit)
    return query.all()


def main():
    db = SessionLocal()
    api_key = get_api_key(db)
    
    if not api_key:
        print("❌ Clé API non configurée!", flush=True)
        sys.exit(1)
    
    print(f"🔑 API: {api_key[:10]}...", flush=True)
    print(f"📦 Lot: {BATCH_SIZE} clients/h", flush=True)
    
    total_success = 0
    total_errors = 0
    batch_num = 0
    
    while True:
        batch_num += 1
        pending = get_pending_clients(db)
        remaining = len(pending)
        
        if remaining == 0:
            print(f"\n✅ TERMINÉ! {total_success} clients exportés", flush=True)
            break
        
        batch = pending[:BATCH_SIZE]
        print(f"\n{'='*60}", flush=True)
        print(f"📦 LOT {batch_num} - {len(batch)} clients ({remaining} restants)", flush=True)
        print(f"⏰ {datetime.now().strftime('%H:%M:%S')}", flush=True)
        print(f"{'='*60}", flush=True)
        
        batch_success = 0
        batch_errors = 0
        
        for idx, client in enumerate(batch, 1):
            try:
                result = create_customer_in_karlia(client, api_key)
                
                if result["ok"]:
                    new_id = result["data"].get("id") if result["data"] else None
                    if new_id:
                        client.karlia_id = str(new_id)
                        client.synchro_at = datetime.now(timezone.utc)
                        db.commit()
                        print(f"[{idx}/{len(batch)}] ✓ {client.numero_client} → {new_id}", flush=True)
                        batch_success += 1
                    else:
                        print(f"[{idx}/{len(batch)}] ⚠ {client.numero_client} - pas d'ID", flush=True)
                        batch_errors += 1
                elif result["status"] == 429:
                    print(f"[{idx}/{len(batch)}] ⏸️ Quota atteint - arrêt du lot", flush=True)
                    batch_errors += 1
                    break
                else:
                    print(f"[{idx}/{len(batch)}] ✗ {client.numero_client} - {result['error']}", flush=True)
                    batch_errors += 1
                
                time.sleep(DELAY_BETWEEN_REQUESTS)
                
            except Exception as e:
                print(f"[{idx}/{len(batch)}] ✗ {client.numero_client} - {str(e)[:50]}", flush=True)
                batch_errors += 1
                time.sleep(5)
        
        total_success += batch_success
        total_errors += batch_errors
        
        # Vérifier s'il reste des clients
        remaining_after = len(get_pending_clients(db))
        if remaining_after == 0:
            print(f"\n✅ TERMINÉ! {total_success} clients exportés", flush=True)
            break
        
        # Attendre avant le prochain lot
        next_time = datetime.now().strftime('%H:%M')
        wait_min = WAIT_BETWEEN_BATCHES // 60
        print(f"\n⏳ Pause {wait_min} min... Prochain lot ~{next_time}", flush=True)
        print(f"📊 Progression: {total_success} OK / {total_errors} erreurs", flush=True)
        time.sleep(WAIT_BETWEEN_BATCHES)
    
    print(f"\n{'='*60}", flush=True)
    print(f"📊 FINAL: {total_success} succès, {total_errors} erreurs", flush=True)
    print(f"{'='*60}", flush=True)
    db.close()


if __name__ == "__main__":
    main()
