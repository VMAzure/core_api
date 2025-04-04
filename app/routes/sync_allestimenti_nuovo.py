import requests
from datetime import datetime
from sqlalchemy import text
from app.database import SessionLocal
import requests
import time
from sqlalchemy.orm import Session
from app.models import MnetModelli

MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
VERSIONI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/versioni"
ANNO_CORRENTE = datetime.now().year

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

def sync_allestimenti():
    db = SessionLocal()
    modelli = db.execute(text("""
    SELECT m.codice_modello
    FROM mnet_modelli m
    JOIN mnet_marche ma ON m.marca_acronimo = ma.acronimo
    WHERE ma.utile IS TRUE
""")).fetchall()


    for row in modelli:
        codice_modello = row[0]
        print(f"\n🔎 Recupero allestimenti per modello: {codice_modello}")

        token = get_motornet_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{VERSIONI_URL}?codice_modello={codice_modello}&anno={ANNO_CORRENTE}"

        for attempt in range(5):
            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                break
            elif response.status_code == 401:
                print("🔄 Token scaduto o non valido, rigenero...")
                token = get_motornet_token()
                headers = {"Authorization": f"Bearer {token}"}
                time.sleep(1.5)
            else:
                print(f"❌ Errore {response.status_code} per modello {codice_modello}, tentativo {attempt+1}")
                time.sleep(1.5)
        else:
            print(f"❌ Errore permanente su modello {codice_modello}, salto.")
            continue

        versioni = response.json().get("versioni", [])

        for v in versioni:
            codice_uni = v["codiceMotornetUnivoco"]
            nome = v["nome"]
            data_da = v.get("da")
            data_a = v.get("a")

            check = db.execute(
                text("SELECT 1 FROM mnet_allestimenti WHERE codice_motornet_uni = :cod"),
                {"cod": codice_uni}
            ).fetchone()

            if check:
                print(f"⏩ Allestimento {codice_uni} già presente, salto.")
                continue

            insert_query = text("""
                INSERT INTO mnet_allestimenti (
                    codice_modello, codice_motornet_uni, nome, data_da, data_a
                ) VALUES (
                    :codice_modello, :codice_motornet_uni, :nome, :data_da, :data_a
                )
            """)

            db.execute(insert_query, {
                "codice_modello": codice_modello,
                "codice_motornet_uni": codice_uni,
                "nome": nome,
                "data_da": data_da,
                "data_a": data_a
            })
            db.commit()
            print(f"✅ Inserito allestimento {codice_uni}")

    db.close()


if __name__ == "__main__":
    sync_allestimenti()
