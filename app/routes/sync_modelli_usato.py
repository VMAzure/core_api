import requests
import time
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine
from datetime import datetime

SessionLocal = sessionmaker(bind=engine)

MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MODELLI_PROXY_URL = "https://webservice.motornet.it/api/v2_0/rest/proxy/usato/auto/modelli"

shared_token = {"value": None}

def get_motornet_token():
    data = {
        'grant_type': 'password',
        'client_id': 'webservice',
        'username': 'azure447',   # TODO: spostare in env var
        'password': 'azwsn557',   # TODO: spostare in env var
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

def process_modelli(marca, anno):
    """Scarica i modelli per una marca+anno e salva in mnet_modelli_usato. Ritorna True/False."""
    db = SessionLocal()

    # Skip se abbiamo già almeno un modello per marca+anno
    esiste = db.execute(text("""
        SELECT 1 FROM mnet_modelli_usato
        WHERE marca_acronimo = :marca
        AND inizio_produzione <= make_date(:anno, 12, 31)
        LIMIT 1
    """), {"marca": marca, "anno": anno}).fetchone()

    if esiste:
        print(f"⏭️  {marca}-{anno}: già presenti modelli, skippo")
        db.close()
        return True

    url = f"{MODELLI_PROXY_URL}?codice_marca={marca}&anno={anno}&libro=false"
    headers = {"Authorization": f"Bearer {shared_token['value']}"}

    for attempt in range(5):
        try:
            resp = requests.get(url, headers=headers, timeout=20)

            if resp.status_code == 401:
                print(f"🔄 Token scaduto per {marca}-{anno}, rinnovo...")
                get_motornet_token()
                headers = {"Authorization": f"Bearer {shared_token['value']}"}
                time.sleep(1)
                continue

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 15))
                print(f"⏳ Rate limit {marca}-{anno}, attendo {wait}s (tentativo {attempt+1}/5)")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            modelli = resp.json().get("modelli", [])
            print(f"📦 {marca}-{anno}: ricevuti {len(modelli)} modelli")

            inseriti = 0
            for modello in modelli:
                codice = modello.get("codDescModello", {}).get("codice")
                if not codice:
                    continue

                result = db.execute(text("""
                    INSERT INTO mnet_modelli_usato (
                        marca_acronimo, codice_desc_modello, codice_modello, descrizione, descrizione_dettagliata,
                        gruppo_storico, inizio_produzione, fine_produzione,
                        inizio_commercializzazione, fine_commercializzazione,
                        segmento, tipo, serie_gamma, created_at
                    ) VALUES (
                        :marca_acronimo, :codice_desc_modello, :codice_modello, :descrizione, :descrizione_dettagliata,
                        :gruppo_storico, :inizio_produzione, :fine_produzione,
                        :inizio_commercializzazione, :fine_commercializzazione,
                        :segmento, :tipo, :serie_gamma, :created_at
                    )
                    ON CONFLICT (marca_acronimo, codice_desc_modello) DO NOTHING
                """), {
                    "marca_acronimo": marca,
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
                if result.rowcount == 1:
                    inseriti += 1

            db.commit()
            print(f"✅ {marca}-{anno}: {inseriti} nuovi modelli salvati")
            return True

        except Exception as e:
            print(f"⚠️ Errore {marca}-{anno} (tentativo {attempt+1}/5): {e}")
            time.sleep(5 * (attempt + 1))
            continue
        finally:
            db.rollback()

    db.close()
    print(f"⛔ Fallito definitivamente {marca}-{anno}")
    return False

def sync_modelli_usato():
    db = SessionLocal()
    get_motornet_token()
    try:
        rows = db.execute(text("""
            SELECT DISTINCT marca_acronimo, anno
            FROM mnet_anni_usato
            ORDER BY marca_acronimo, anno
        """)).fetchall()
        rows = [(r[0], r[1]) for r in rows]

        print(f"🔧 Avvio sync modelli per {len(rows)} combinazioni marca+anno")

        da_fare = rows
        round_num = 1
        while da_fare:
            print(f"🚀 Round {round_num} con {len(da_fare)} combinazioni")
            next_round = []
            for marca, anno in da_fare:
                ok = process_modelli(marca, anno)
                if not ok:
                    next_round.append((marca, anno))
                time.sleep(0.5)  # throttling
            if da_fare == next_round:
                print("⚠️ Nessun progresso, stop per evitare loop infinito")
                break
            da_fare = next_round
            round_num += 1

        if not da_fare:
            print("🏁 Tutti i modelli completati")
        else:
            print(f"⚠️ Rimaste non completate: {da_fare}")

    finally:
        db.close()

if __name__ == "__main__":
    sync_modelli_usato()
