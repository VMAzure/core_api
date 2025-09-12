import requests
import time
import logging
from datetime import datetime
from app.database import SessionLocal
from app.models import MnetAllestimenti, MnetImmagini

MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MOTORN_FOTO_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/foto"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def get_motornet_token():
    data = {
        "grant_type": "password",
        "client_id": "webservice",
        "username": "azure447",
        "password": "azwsn557",
    }
    r = requests.post(MOTORN_AUTH_URL, data=data)
    r.raise_for_status()
    return r.json().get("access_token")

def sync_foto_mnet_missing(max_retries=5, delay_base=2):
    db = SessionLocal()

    # recupera solo gli allestimenti che non hanno nessun record in mnet_immagini
    missing = db.query(MnetAllestimenti.codice_motornet_uni).filter(
        ~db.query(MnetImmagini.codice_motornet_uni)
        .filter(MnetImmagini.codice_motornet_uni == MnetAllestimenti.codice_motornet_uni)
        .exists()
    ).all()

    logging.info(f"📸 Mancanti da processare: {len(missing)}")

    token = get_motornet_token()
    headers = {"Authorization": f"Bearer {token}"}

    for (codice_uni,) in missing:
        attempt = 0
        while attempt < max_retries:
            try:
                url = f"{MOTORN_FOTO_URL}?codice_motornet_uni={codice_uni}&risoluzione=H"
                r = requests.get(url, headers=headers, timeout=30)

                if r.status_code == 401:
                    logging.warning(f"🔑 Token scaduto durante {codice_uni}, rinnovo...")
                    token = get_motornet_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    attempt += 1
                    continue

                if r.status_code == 412:
                    logging.info(f"🚫 Nessuna foto disponibile per {codice_uni}")
                    rec = MnetImmagini(
                        codice_motornet_uni=codice_uni,
                        url=None,
                        descrizione_visuale="NESSUNA FOTO DISPONIBILE",
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(rec)
                    db.commit()
                    break

                if r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", "10"))
                    wait_time = retry_after + attempt * delay_base
                    logging.warning(f"⏳ Rate limit 429 per {codice_uni}, attendo {wait_time}s...")
                    time.sleep(wait_time)
                    attempt += 1
                    continue

                if r.status_code in (500, 502, 503):
                    logging.error(f"⚠️ Errore server {r.status_code} per {codice_uni}, tentativo {attempt+1}")
                    attempt += 1
                    if attempt >= max_retries:
                        rec = MnetImmagini(
                            codice_motornet_uni=codice_uni,
                            url=None,
                            descrizione_visuale=f"ERRORE SERVER {r.status_code}",
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        db.add(rec)
                        db.commit()
                    time.sleep(delay_base * attempt)
                    continue

                r.raise_for_status()
                data = r.json()

                nuove = 0
                for img in data.get("immagini", []):
                    logging.info(
                        f"📷 {codice_uni} → {img.get('descrizioneVisuale')} "
                        f"[{img.get('risoluzione')}] {img.get('url')}"
                    )
                    rec = MnetImmagini(
                        codice_motornet_uni=codice_uni,
                        url=img.get("url"),
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
                break

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
    logging.info("🏁 sync_foto_mnet_missing completato")

if __name__ == "__main__":
    sync_foto_mnet_missing()
