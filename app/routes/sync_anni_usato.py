import requests
import time
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine
from datetime import datetime

# Configurazioni Motornet
MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
ANNI_URL = "https://webservice.motornet.it/api/v2_0/rest/proxy/usato/auto/anni"

# DB session
SessionLocal = sessionmaker(bind=engine)

# Token condiviso
shared_token = {"value": None}

def get_motornet_token():
    """Ottieni un token JWT valido per le API Motornet."""
    data = {
        'grant_type': 'password',
        'client_id': 'webservice',
        'username': 'azure447',   # TODO: sposta in variabili d'ambiente
        'password': 'azwsn557',   # TODO: sposta in variabili d'ambiente
    }
    for attempt in range(3):
        try:
            resp = requests.post(MOTORN_AUTH_URL, data=data, timeout=15)
            resp.raise_for_status()
            shared_token["value"] = resp.json().get("access_token")
            return shared_token["value"]
        except Exception as e:
            print(f"❌ Errore richiesta token (tentativo {attempt+1}): {e}")
            time.sleep(2)
    raise Exception("❌ Impossibile ottenere token Motornet")

def sync_anni_usato(acronimo):
    """Scarica anni disponibili per una marca e salva in mnet_anni_usato."""
    db = SessionLocal()

    # Skip se la marca è già presente
    esiste = db.execute(text("""
        SELECT 1 FROM mnet_anni_usato WHERE marca_acronimo = :marca LIMIT 1
    """), {"marca": acronimo}).fetchone()
    if esiste:
        print(f"⏭️  {acronimo}: già presente in mnet_anni_usato, skippo")
        db.close()
        return True

    try:
        url = f"{ANNI_URL}?codice_marca={acronimo}"
        headers = {"Authorization": f"Bearer {shared_token['value']}"}

        # Retry con backoff
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code == 401:
                    print("🔄 Token scaduto, rinnovo...")
                    get_motornet_token()
                    headers = {"Authorization": f"Bearer {shared_token['value']}"}
                    resp = requests.get(url, headers=headers, timeout=20)

                resp.raise_for_status()
                break
            except Exception as e:
                print(f"⚠️ Errore anni {acronimo} (tentativo {attempt+1}): {e}")
                time.sleep(5 * (attempt + 1))
        else:
            print(f"⛔ Fallito definitivamente anni per {acronimo}")
            return False

        anni = resp.json().get("anni", [])
        if not anni:
            print(f"⚠️ Nessun anno trovato per {acronimo}")
            return True

        inseriti = 0
        for anno in anni:
            # l’API ritorna solo interi (anni)
            result = db.execute(text("""
                INSERT INTO mnet_anni_usato (marca_acronimo, anno, mese)
                VALUES (:marca, :anno, 0)
                ON CONFLICT (marca_acronimo, anno, mese) DO NOTHING
            """), {"marca": acronimo, "anno": int(anno)})
            if result.rowcount == 1:
                inseriti += 1

        db.commit()
        print(f"✅ {acronimo}: inseriti {inseriti} anni")
        return True

    except Exception as e:
        db.rollback()
        print(f"❌ Errore sync anni {acronimo}: {e}")
        return False
    finally:
        db.close()

def sync_all_marche():
    """Cicla tutte le marche registrate e popola mnet_anni_usato con retry e riaccodamento."""
    db = SessionLocal()
    get_motornet_token()
    try:
        acronimi = db.execute(text("SELECT acronimo FROM mnet_marche_usato")).fetchall()
        acronimi = [row[0] for row in acronimi]
        print(f"🔧 Avvio sync anni per {len(acronimi)} marche")

        da_fare = acronimi
        round_num = 1
        while da_fare:
            print(f"🚀 Round {round_num} con {len(da_fare)} marche")
            next_round = []
            for acronimo in da_fare:
                ok = sync_anni_usato(acronimo)
                if not ok:
                    next_round.append(acronimo)
                time.sleep(0.5)  # throttling
            if da_fare == next_round:
                print("⚠️ Nessun progresso, stop per evitare loop infinito")
                break
            da_fare = next_round
            round_num += 1

        if not da_fare:
            print("🏁 Tutte le marche completate")
        else:
            print(f"⚠️ Rimaste non completate: {da_fare}")

    finally:
        db.close()

if __name__ == "__main__":
    sync_all_marche()
