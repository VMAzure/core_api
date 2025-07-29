import requests
import time
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine

# URL e autenticazione
MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
VERSIONI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/modello/versioni"

SessionLocal = sessionmaker(bind=engine)
shared_token = {"value": None}

# Ottenere il token Motornet
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

# Chiamata API per ottenere versioni per marca+modello
def fetch_versioni(codice_marca, codice_modello):
    headers = {"Authorization": f"Bearer {shared_token['value']}"}
    url = f"{VERSIONI_URL}?codice_marca={codice_marca}&codice_modello={codice_modello}"
    response = requests.get(url, headers=headers)

    if response.status_code == 401:
        print(f"🔄 Token scaduto, rinnovo...")
        get_motornet_token()
        headers = {"Authorization": f"Bearer {shared_token['value']}"}
        response = requests.get(url, headers=headers)

    response.raise_for_status()
    return response.json().get("versioni", [])

# Salvataggio nel DB per un modello specifico
def salva_versioni_per_modello(codice_marca, codice_desc_modello):
    db = SessionLocal()
    try:
        versioni = fetch_versioni(codice_marca, codice_desc_modello)
        if not versioni:
            print(f"⚠️ Nessuna versione per {codice_marca} - {codice_desc_modello}")
            return

        inseriti = 0
        for v in versioni:
            if not v.get("codiceMotornetUnivoco"):
                continue

            db.execute(text("""
                INSERT INTO mnet_allestimenti_usato (
                    codice_motornet_uni, acronimo_marca, codice_desc_modello, versione,
                    alimentazione, cambio, trazione, cilindrata, kw, cv
                ) VALUES (
                    :codice_motornet_uni, :acronimo_marca, :codice_desc_modello, :versione,
                    :alimentazione, :cambio, :trazione, :cilindrata, :kw, :cv
                )
                ON CONFLICT (codice_motornet_uni) DO NOTHING
            """), {
                "codice_motornet_uni": v["codiceMotornetUnivoco"],
                "acronimo_marca": v.get("marca", {}).get("acronimo", codice_marca),
                "codice_desc_modello": codice_desc_modello,
                "versione": v.get("nome"),
                "alimentazione": None,
                "cambio": None,
                "trazione": None,
                "cilindrata": None,
                "kw": None,
                "cv": None,
            })
            inseriti += 1

        db.commit()
        print(f"✅ {codice_marca} - {codice_desc_modello}: {inseriti} versioni salvate")
    except Exception as e:
        print(f"❌ Errore per {codice_marca}-{codice_desc_modello}: {e}")
        db.rollback()
    finally:
        db.close()

# Ciclo su tutti i modelli della tabella
def sync_allestimenti_usato():
    db = SessionLocal()
    get_motornet_token()

    try:
        righe = db.execute(text("SELECT marca_acronimo, codice_desc_modello FROM mnet_modelli_usato")).fetchall()
        print(f"🔍 Trovati {len(righe)} modelli")

        for marca_acronimo, codice_desc_modello in righe:
            salva_versioni_per_modello(marca_acronimo, codice_desc_modello)
            time.sleep(0.4)  # throttling leggero per sicurezza

    finally:
        db.close()

if __name__ == "__main__":
    sync_allestimenti_usato()
