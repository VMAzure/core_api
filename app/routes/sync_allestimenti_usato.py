import requests
import time
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine
from datetime import datetime

SessionLocal = sessionmaker(bind=engine)

MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
PORTE_URL = "https://webservice.motornet.it/api/v2_0/rest/proxy/usato/auto/porte"
VERSIONI_URL = "https://webservice.motornet.it/api/v2_0/rest/proxy/usato/auto/versioni"

shared_token = {"value": None}


def get_motornet_token():
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
                print(f"⏳ Rate limit, attendo {wait}s (tentativo {attempt+1}/{max_attempts})")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"⚠️ Errore richiesta {url} (tentativo {attempt+1}/{max_attempts}): {e}")
            time.sleep(5 * (attempt + 1))
            continue
    return None


def process_allestimenti(marca, anno, codice_desc_modello):
    """Scarica allestimenti (porte + versioni) per marca+anno+modello e salva in DB."""
    db = SessionLocal()
    inseriti = 0

    try:
        # Skip se già abbiamo versioni per quel modello
        esiste = db.execute(text("""
            SELECT 1 FROM mnet_allestimenti_usato
            WHERE acronimo_marca = :marca AND codice_desc_modello = :codice
            LIMIT 1
        """), {"marca": marca, "codice": codice_desc_modello}).fetchone()
        if esiste:
            print(f"⏭️  {marca}-{anno}-{codice_desc_modello}: già presenti allestimenti, skippo")
            db.close()
            return True

        headers = {"Authorization": f"Bearer {shared_token['value']}"}

        # Step 1: Porte
        url_porte = f"{PORTE_URL}?codice_modello={codice_desc_modello}&anno={anno}"
        porte_data = fetch_with_retry(url_porte, headers)
        if not porte_data:
            print(f"❌ Nessuna porta per {marca}-{anno}-{codice_desc_modello}")
            db.close()
            return False

        porte_list = porte_data.get("porte", [])
        if not porte_list:
            print(f"⚠️ Nessuna porta valida per {marca}-{anno}-{codice_desc_modello}")
            db.close()
            return True

        # Step 2: Versioni per ogni porta
        for porta in porte_list:
            url_versioni = f"{VERSIONI_URL}?codice_modello={codice_desc_modello}&anno={anno}&porte={porta}&libro=false"
            versioni_data = fetch_with_retry(url_versioni, headers)
            if not versioni_data:
                continue

            versioni = versioni_data.get("versioni", [])
            for v in versioni:
                codice_motornet = v.get("codiceMotornet")
                if not codice_motornet:
                    continue

                result = db.execute(text("""
                    INSERT INTO mnet_allestimenti_usato (
                        codice_motornet_uni, acronimo_marca, codice_desc_modello, versione,
                        inizio_produzione, fine_produzione,
                        inizio_commercializzazione, fine_commercializzazione,
                        codice_eurotax
                    ) VALUES (
                        :codice_motornet_uni, :acronimo_marca, :codice_desc_modello, :versione,
                        :inizio_produzione, :fine_produzione,
                        :inizio_commercializzazione, :fine_commercializzazione,
                        :codice_eurotax
                    )
                    ON CONFLICT (codice_motornet_uni) DO NOTHING
                """), {
                    "codice_motornet_uni": codice_motornet,
                    "acronimo_marca": marca,
                    "codice_desc_modello": codice_desc_modello,
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
        print(f"✅ {marca}-{anno}-{codice_desc_modello}: {inseriti} allestimenti salvati")
        return True

    except Exception as e:
        db.rollback()
        print(f"❌ Errore allestimenti {marca}-{anno}-{codice_desc_modello}: {e}")
        return False
    finally:
        db.close()


def sync_allestimenti_usato():
    db = SessionLocal()
    get_motornet_token()
    try:
        rows = db.execute(text("""
            SELECT DISTINCT m.marca_acronimo, a.anno, m.codice_desc_modello
            FROM mnet_modelli_usato m
            JOIN mnet_anni_usato a ON a.marca_acronimo = m.marca_acronimo
            WHERE a.anno >= 2000

            ORDER BY m.marca_acronimo, a.anno, m.codice_desc_modello
        """)).fetchall()
        rows = [(r[0], r[1], r[2]) for r in rows]

        print(f"🔧 Avvio sync allestimenti per {len(rows)} combinazioni marca+anno+modello")

        da_fare = rows
        round_num = 1
        while da_fare:
            print(f"🚀 Round {round_num} con {len(da_fare)} combinazioni")
            next_round = []
            for marca, anno, codice in da_fare:
                ok = process_allestimenti(marca, anno, codice)
                if not ok:
                    next_round.append((marca, anno, codice))
                time.sleep(0.5)  # throttling
            if da_fare == next_round:
                print("⚠️ Nessun progresso, stop per evitare loop infinito")
                break
            da_fare = next_round
            round_num += 1

        if not da_fare:
            print("🏁 Tutti gli allestimenti completati")
        else:
            print(f"⚠️ Rimasti non completati: {da_fare}")

    finally:
        db.close()


if __name__ == "__main__":
    sync_allestimenti_usato()
