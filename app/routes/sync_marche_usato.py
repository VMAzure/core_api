import requests
import time
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed

MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MARCHE_URL = "https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/marche"

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

def process_marca(marca):
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO mnet_marche_usato (acronimo, nome, logo)
            VALUES (:acronimo, :nome, :logo)
            ON CONFLICT (acronimo) DO NOTHING
        """), {
            "acronimo": marca.get("acronimo"),
            "nome": marca.get("nome"),
            "logo": marca.get("logo")
        })
        db.commit()
        print(f"✅ Inserita marca {marca.get('nome')}")
    except Exception as e:
        print(f"❌ Errore salvataggio marca {marca.get('acronimo')}: {e}")
        db.rollback()
    finally:
        db.close()

def sync_marche_usato():
    db = SessionLocal()
    get_motornet_token()

    headers = {"Authorization": f"Bearer {shared_token['value']}"}
    try:
        response = requests.get(MARCHE_URL, headers=headers)
        response.raise_for_status()
        marche = response.json().get("marche", [])
    except Exception as e:
        print(f"❌ Errore durante fetch marche: {e}")
        return

    print(f"🔧 Avvio sync per {len(marche)} marche")
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(process_marca, marca) for marca in marche]
        for future in as_completed(futures):
            future.result()

    db.close()

if __name__ == "__main__":
    sync_marche_usato()
