import requests
from datetime import datetime
from sqlalchemy import text
from app.database import SessionLocal
import requests
import time
from sqlalchemy.orm import Session
from app.models import MnetModelli

MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MARCHE_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/marche"

def get_motornet_token():
    data = {
        'grant_type': 'password',
        'client_id': 'webservice',
        'username': 'azure447',
        'password': 'azwsn557',
    }
    response = requests.post(MOTORN_AUTH_URL, data=data)
    response.raise_for_status()
    return response.json().get('access_token')

def sync_marche():
    db = SessionLocal()

    try:
        token = get_motornet_token()
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.get(MARCHE_URL, headers=headers)
        response.raise_for_status()
        marche = response.json().get("marche", [])

        for marca in marche:
            acronimo = marca["acronimo"]
            nome = marca["nome"]
            logo = marca["logo"]

            # controlla se già presente
            exists = db.execute(
                text("SELECT 1 FROM mnet_marche WHERE acronimo = :acronimo"),
                {"acronimo": acronimo}
            ).fetchone()

            if exists:
                print(f"⏩ Marca {acronimo} già presente, salto.")
                continue

            insert_query = text("""
                INSERT INTO mnet_marche (acronimo, nome, logo, utile)
                VALUES (:acronimo, :nome, :logo, FALSE)
            """)

            db.execute(insert_query, {
                "acronimo": acronimo,
                "nome": nome,
                "logo": logo
            })
            db.commit()
            print(f"✅ Inserita nuova marca: {acronimo}")

    except Exception as e:
        print(f"❌ Errore nella sincronizzazione marche: {e}")

    finally:
        db.close()

if __name__ == "__main__":
    sync_marche()
