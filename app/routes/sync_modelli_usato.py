import requests
import time
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

# Disattiva log SQLAlchemy verbosi
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MODELLI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/marca/modelli"

SessionLocal = sessionmaker(bind=engine)
token_lock = Lock()
shared_token = {"value": None}
fail_lock = Lock()
codici_falliti = []

def get_motornet_token():
    for attempt in range(3):
        try:
            data = {
                'grant_type': 'password',
                'client_id': 'webservice',
                'username': 'azure447',
                'password': 'azwsn557',
            }
            response = requests.post(MOTORN_AUTH_URL, data=data)
            response.raise_for_status()
            token = response.json().get('access_token')
            shared_token["value"] = token
            return token
        except requests.exceptions.RequestException as e:
            print(f"❌ Errore richiesta token (tentativo {attempt+1}): {e}")
            time.sleep(2)
    raise Exception("❌ Impossibile ottenere il token dopo 3 tentativi")

from datetime import datetime

from datetime import datetime

def process_modelli(acronimo):
    db = SessionLocal()
    inseriti = 0
    skippati = 0
    falliti = 0

    for attempt in range(3):
        try:
            headers = {"Authorization": f"Bearer {shared_token['value']}"}
            url = f"{MODELLI_URL}?codice_marca={acronimo}"
            response = requests.get(url, headers=headers)

            if response.status_code == 401:
                print(f"🔄 Token scaduto per {acronimo}, rinnovo...")
                get_motornet_token()
                time.sleep(1)
                continue

            if response.status_code == 412:
                print(f"⚠️ 412 Precondition per {acronimo}, salto.")
                return

            response.raise_for_status()
            break
        except Exception as e:
            print(f"❌ Errore modelli {acronimo} (tentativo {attempt+1}): {e}")
            time.sleep(1.5)
    else:
        print(f"⛔ Fallito definitivamente {acronimo}, salto.")
        db.close()
        return

    try:
        modelli = response.json().get("modelli", [])
        print(f"📦 {acronimo}: ricevuti {len(modelli)} modelli")

        def parse_date(val):
            try:
                return datetime.strptime(val, "%Y-%m-%d").date() if val else None
            except:
                return None

        for modello in modelli:
            codice = modello.get("codDescModello", {}).get("codice")
            if not codice:
                skippati += 1
                print(f"⚠️  Skipping modello senza codice ({acronimo})")
                continue

            try:
                result = db.execute(text("""
                    INSERT INTO mnet_modelli_usato (
                        marca_acronimo, codice_desc_modello, codice_modello, descrizione, descrizione_dettagliata,
                        gruppo_storico, inizio_produzione, fine_produzione,
                        inizio_commercializzazione, fine_commercializzazione, segmento, tipo, serie_gamma,
                        created_at
                    ) VALUES (
                        :marca_acronimo, :codice_desc_modello, :codice_modello, :descrizione, :descrizione_dettagliata,
                        :gruppo_storico, :inizio_produzione, :fine_produzione,
                        :inizio_commercializzazione, :fine_commercializzazione, :segmento, :tipo, :serie_gamma,
                        :created_at
                    )
                    ON CONFLICT (marca_acronimo, codice_desc_modello) DO NOTHING
                """), {
                    "marca_acronimo": acronimo,
                    "codice_desc_modello": codice,
                    "codice_modello": codice,
                    "descrizione": modello.get("codDescModello", {}).get("descrizione"),
                    "descrizione_dettagliata": modello.get("gammaModello", {}).get("descrizione"),
                    "gruppo_storico": modello.get("gruppoStorico", {}).get("descrizione"),
                    "inizio_produzione": parse_date(modello.get("inizioProduzione")),
                    "fine_produzione": parse_date(modello.get("fineProduzione")),
                    "inizio_commercializzazione": parse_date(modello.get("inizioCommercializzazione")),
                    "fine_commercializzazione": parse_date(modello.get("fineCommercializzazione")),
                    "segmento": None,
                    "tipo": None,
                    "serie_gamma": modello.get("serieGamma", {}).get("descrizione"),
                    "created_at": datetime.utcnow().date()
                })

                # SQLite returns None, Postgres returns rowcount
                if result.rowcount == 1:
                    inseriti += 1
                    print(f"✅ Inserito: {codice} - {modello.get('codDescModello', {}).get('descrizione')}")
                else:
                    skippati += 1
                    print(f"🟡 Esiste già: {codice}")

            except Exception as e:
                falliti += 1
                print(f"❌ Errore {codice}: {e}")

        db.commit()
        print(f"🟩 {acronimo}: {inseriti} nuovi / 🟡 {skippati} già presenti / ❌ {falliti} errori")

    except Exception as e:
        print(f"❌ Errore globale salvataggio {acronimo}: {e}")
        db.rollback()
    finally:
        db.close()


def sync_modelli_usato():
    db = SessionLocal()
    get_motornet_token()

    acronimi = db.execute(text("SELECT acronimo FROM mnet_marche_usato")).fetchall()
    acronimi = [row[0] for row in acronimi]

    print(f"🔧 Avvio sync modelli per {len(acronimi)} marche")
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(process_modelli, acronimo) for acronimo in acronimi]
        for future in as_completed(futures):
            future.result()

    db.close()

if __name__ == "__main__":
    sync_modelli_usato()
