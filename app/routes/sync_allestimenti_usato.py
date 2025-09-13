import requests
import time
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine

SessionLocal = sessionmaker(bind=engine)

# Motornet endpoints
MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
VERSIONI_URL = "https://webservice.motornet.it/api/v2_0/rest/proxy/usato/auto/versioni"

shared_token = {"value": None}

def get_motornet_token():
    for attempt in range(3):
        try:
            data = {
                'grant_type': 'password',
                'client_id': 'webservice',
                'username': 'azure447',
                'password': 'azwsn557',
            }
            resp = requests.post(MOTORN_AUTH_URL, data=data)
            resp.raise_for_status()
            shared_token["value"] = resp.json().get("access_token")
            return shared_token["value"]
        except Exception as e:
            print(f"❌ Errore token (tentativo {attempt+1}): {e}")
            time.sleep(2)
    raise Exception("❌ Impossibile ottenere il token Motornet")

def parse_date(val):
    try:
        return datetime.strptime(val, "%Y-%m-%d").date() if val else None
    except:
        return None

def fetch_with_retry(url, headers, max_attempts=5):
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, headers=headers, timeout=20)

            if resp.status_code == 401:
                print("🔄 Token scaduto, rinnovo...")
                get_motornet_token()
                headers["Authorization"] = f"Bearer {shared_token['value']}"
                continue

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 15))
                print(f"⏳ Rate limit, attendo {wait}s (tentativo {attempt+1})")
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                print(f"⚠️ Errore {resp.status_code}, retry...")
                time.sleep(3 * (attempt + 1))
                continue

            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"❌ Errore fetch {url} (tentativo {attempt+1}): {e}")
            time.sleep(3 * (attempt + 1))
    return None

def process_allestimenti(marca, anno, codice_modello, esistenti):
    if codice_modello in esistenti:
        print(f"⏭️  {marca}-{anno}-{codice_modello}: già presenti allestimenti")
        return True

    db = SessionLocal()
    headers = {"Authorization": f"Bearer {shared_token['value']}"}
    url_versioni = f"{VERSIONI_URL}?codice_modello={codice_modello}&anno={anno}&libro=false"

    try:
        versioni_data = fetch_with_retry(url_versioni, headers)
        if not versioni_data:
            print(f"❌ Fallimento fetch versioni {marca}-{anno}-{codice_modello}")
            return False

        versioni = versioni_data.get("versioni", [])
        if not versioni:
            print(f"⚠️ Nessuna versione valida per {marca}-{anno}-{codice_modello}")
            return True

        inseriti = 0
        for v in versioni:
            codice_motornet = v.get("codiceMotornet")
            if not codice_motornet:
                continue

            result = db.execute(text("""
                INSERT INTO mnet_allestimenti_usato (
                    codice_motornet_uni, acronimo_marca,
                    codice_modello, versione,
                    inizio_produzione, fine_produzione,
                    inizio_commercializzazione, fine_commercializzazione,
                    codice_eurotax
                ) VALUES (
                    :codice_motornet_uni, :acronimo_marca,
                    :codice_modello, :versione,
                    :inizio_produzione, :fine_produzione,
                    :inizio_commercializzazione, :fine_commercializzazione,
                    :codice_eurotax
                )
                ON CONFLICT (codice_motornet_uni) DO NOTHING
            """), {
                "codice_motornet_uni": codice_motornet,
                "acronimo_marca": marca,
                "codice_modello": codice_modello,
                "versione": v.get("nome"),
                "inizio_produzione": parse_date(v.get("inizioProduzione")),
                "fine_produzione": parse_date(v.get("fineProduzione")),
                "inizio_commercializzazione": parse_date(v.get("da")),
                "fine_commercializzazione": parse_date(v.get("a")),
                "codice_eurotax": v.get("codiceEurotax")
            })
            if result.rowcount == 1:
                inseriti += 1

        db.commit()
        print(f"✅ {marca}-{anno}-{codice_modello}: {inseriti} allestimenti salvati")
        return True

    except Exception as e:
        db.rollback()
        print(f"❌ Errore DB {marca}-{anno}-{codice_modello}: {e}")
        return False
    finally:
        db.close()

def sync_allestimenti_usato():
    db = SessionLocal()
    get_motornet_token()

    # ✅ Modelli già esistenti → evitiamo doppie chiamate
    existing_rows = db.execute(text("""
        SELECT DISTINCT codice_modello FROM mnet_allestimenti_usato
    """)).fetchall()
    esistenti = {r[0] for r in existing_rows}

    # ✅ Tutti i modelli da elaborare
    rows = db.execute(text("""
        SELECT DISTINCT 
            m.marca_acronimo, a.anno, m.codice_modello
        FROM mnet_modelli_usato m
        JOIN mnet_anni_usato a ON a.marca_acronimo = m.marca_acronimo
        WHERE a.anno >= 2000
        ORDER BY m.marca_acronimo, a.anno, m.codice_modello
    """)).fetchall()
    rows = [(r[0], r[1], r[2]) for r in rows]

    print(f"\n🔧 Avvio sync allestimenti per {len(rows)} combinazioni marca+anno+modello")

    da_fare = rows
    round_num = 1
    while da_fare:
        print(f"🚀 Round {round_num} con {len(da_fare)} combinazioni")
        next_round = []
        for marca, anno, codice_modello in da_fare:
            ok = process_allestimenti(marca, anno, codice_modello, esistenti)
            if not ok:
                next_round.append((marca, anno, codice_modello))
            time.sleep(0.4)  # throttling leggero
        if da_fare == next_round:
            print("⚠️ Nessun progresso, fermo per evitare loop infinito.")
            break
        da_fare = next_round
        round_num += 1

    if not da_fare:
        print("🏁 Sync completato con successo.")
    else:
        print(f"⚠️ Rimaste non completate: {len(da_fare)} combinazioni.")

    db.close()


if __name__ == "__main__":
    sync_allestimenti_usato()
