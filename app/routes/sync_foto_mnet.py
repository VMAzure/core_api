import requests
import time
from sqlalchemy import text
from app.database import SessionLocal
from app.models import MnetAllestimenti, MnetImmagini
from datetime import datetime
from sync_dettagli_nuovo import get_motornet_token
import requests
import time
import logging


MOTORN_FOTO_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/foto"

def sync_foto_mnet(max_retries=5, delay_base=2):
    db = SessionLocal()

    allestimenti = db.query(MnetAllestimenti.codice_motornet_uni).all()
    logging.info(f"📸 Avvio sync_foto_mnet: {len(allestimenti)} allestimenti da processare")

    token = get_motornet_token()
    headers = {"Authorization": f"Bearer {token}"}

    for (codice_uni,) in allestimenti:
        attempt = 0
        while attempt < max_retries:
            try:
                url = f"{MOTORN_FOTO_URL}?codice_motornet_uni={codice_uni}&risoluzione=H"
                r = requests.get(url, headers=headers, timeout=30)

                # Gestione token scaduto
                if r.status_code == 401:
                    logging.warning(f"🔑 Token scaduto durante {codice_uni}, rinnovo...")
                    token = get_motornet_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    attempt += 1
                    continue

                # Gestione rate limit
                if r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", "10"))
                    wait_time = retry_after + attempt * delay_base
                    logging.warning(f"⏳ Rate limit 429 per {codice_uni}, attendo {wait_time}s...")
                    time.sleep(wait_time)
                    attempt += 1
                    continue

                r.raise_for_status()
                data = r.json()

                nuove = 0
                for img in data.get("immagini", []):
                    exists = db.query(MnetImmagini).filter_by(
                        codice_motornet_uni=codice_uni,
                        url=img["url"]
                    ).first()
                    if exists:
                        continue

                    rec = MnetImmagini(
                        codice_motornet_uni=codice_uni,
                        url=img["url"],
                        codice_fotografia=img.get("codiceFotografia"),
                        codice_visuale=img.get("codiceVisuale"),
                        descrizione_visuale=img.get("descrizioneVisuale"),
                        risoluzione=img.get("risoluzione"),
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(rec)
                    nuove += 1

                db.commit()
                if nuove > 0:
                    logging.info(f"✅ Inserite {nuove} nuove immagini per {codice_uni}")
                else:
                    logging.debug(f"⏩ Nessuna nuova immagine per {codice_uni}")

                break  # uscita dal ciclo retry su successo

            except requests.exceptions.RequestException as e:
                wait_time = delay_base * (attempt + 1)
                logging.error(f"❌ Errore rete su {codice_uni} ({e}), retry in {wait_time}s...")
                time.sleep(wait_time)
                attempt += 1
                continue

            except Exception as e:
                db.rollback()
                logging.error(f"❌ Errore grave su {codice_uni}: {e}")
                break

    db.close()
    logging.info("🏁 sync_foto_mnet completato")
