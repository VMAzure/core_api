import requests
import time
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import os

load_dotenv()

MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
DETTAGLI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/dettaglio"

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

def safe_bool(val):
    return bool(val) if isinstance(val, bool) else None

def safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

def process_codice(codice_uni):
    db = SessionLocal()
    url = f"{DETTAGLI_URL}?codice_motornet_uni={codice_uni}"

    for attempt in range(5):
        headers = {"Authorization": f"Bearer {shared_token['value']}"}
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            break
        elif response.status_code == 401:
            print(f"🔄 Token scaduto per {codice_uni}, rinnovo...")
            get_motornet_token()
        elif response.status_code == 429:
            print(f"⏳ RATE LIMIT per {codice_uni} (tentativo {attempt+1}), attendo 15s...")
            time.sleep(15)
        else:
            print(f"❌ Errore {response.status_code} per {codice_uni} (tentativo {attempt+1})")
            time.sleep(1.5)
    else:
        print(f"❌ Fallito {codice_uni}, reinserisco in coda.")
        with fail_lock:
            codici_falliti.append(codice_uni)
        db.close()
        return

    modello = response.json().get("modello", {})
    if not modello:
        print(f"⚠️ Nessun modello per {codice_uni}")
        db.close()
        return

    try:
        db.execute(text("""
            INSERT INTO mnet_dettagli_usato (
                codice_motornet_uni, modello, allestimento, immagine, codice_costruttore, codice_motore,
                prezzo_listino, prezzo_accessori, data_listino,
                marca_nome, marca_acronimo,
                gamma_codice, gamma_descrizione, gruppo_storico, serie_gamma,
                categoria, segmento, tipo,
                tipo_motore, descrizione_motore, euro, cilindrata, cavalli_fiscali, hp, kw,
                emissioni_co2, consumo_urbano, consumo_extraurbano, consumo_medio,
                accelerazione, velocita,
                descrizione_marce, cambio, trazione, passo,
                porte, posti, altezza, larghezza, lunghezza,
                bagagliaio, pneumatici_anteriori, pneumatici_posteriori,
                coppia, numero_giri, cilindri, valvole, peso, peso_vuoto,
                massa_p_carico, portata, tipo_guida, neo_patentati,
                alimentazione, architettura, ricarica_standard, ricarica_veloce,
                sospensioni_pneumatiche, emissioni_urbe, emissioni_extraurb, descrizione_breve,
                peso_potenza, volumi, ridotte, paese_prod
            ) VALUES (
                :codice_motornet_uni, :modello, :allestimento, :immagine, :codice_costruttore, :codice_motore,
                :prezzo_listino, :prezzo_accessori, :data_listino,
                :marca_nome, :marca_acronimo,
                :gamma_codice, :gamma_descrizione, :gruppo_storico, :serie_gamma,
                :categoria, :segmento, :tipo,
                :tipo_motore, :descrizione_motore, :euro, :cilindrata, :cavalli_fiscali, :hp, :kw,
                :emissioni_co2, :consumo_urbano, :consumo_extraurbano, :consumo_medio,
                :accelerazione, :velocita,
                :descrizione_marce, :cambio, :trazione, :passo,
                :porte, :posti, :altezza, :larghezza, :lunghezza,
                :bagagliaio, :pneumatici_anteriori, :pneumatici_posteriori,
                :coppia, :numero_giri, :cilindri, :valvole, :peso, :peso_vuoto,
                :massa_p_carico, :portata, :tipo_guida, :neo_patentati,
                :alimentazione, :architettura, :ricarica_standard, :ricarica_veloce,
                :sospensioni_pneumatiche, :emissioni_urbe, :emissioni_extraurb, :descrizione_breve,
                :peso_potenza, :volumi, :ridotte, :paese_prod
            )
            ON CONFLICT (codice_motornet_uni) DO NOTHING

        """), {
            "codice_motornet_uni": codice_uni,
            "modello": modello.get("modello"),
            "allestimento": modello.get("allestimento"),
            "immagine": modello.get("immagine"),
            "codice_costruttore": modello.get("codiceCostruttore"),
            "codice_motore": modello.get("codiceMotore"),
            "prezzo_listino": safe_float(modello.get("prezzoListino")),
            "prezzo_accessori": safe_float(modello.get("prezzoAccessori")),
            "data_listino": datetime.strptime(modello.get("dataListino"), "%Y-%m-%d").date() if modello.get("dataListino") else None,
            "marca_nome": (modello.get("marca") or {}).get("nome"),
            "marca_acronimo": (modello.get("marca") or {}).get("acronimo"),
            "gamma_codice": (modello.get("gammaModello") or {}).get("codice"),
            "gamma_descrizione": (modello.get("gammaModello") or {}).get("descrizione"),
            "gruppo_storico": (modello.get("gruppoStorico") or {}).get("descrizione"),
            "serie_gamma": (modello.get("serieGamma") or {}).get("descrizione"),
            "categoria": (modello.get("categoria") or {}).get("descrizione"),
            "segmento": (modello.get("segmento") or {}).get("descrizione"),
            "tipo": (modello.get("tipo") or {}).get("descrizione"),
            "tipo_motore": modello.get("tipoMotore"),
            "descrizione_motore": modello.get("descrizioneMotore"),
            "euro": modello.get("euro"),
            "cilindrata": modello.get("cilindrata"),
            "cavalli_fiscali": modello.get("cavalliFiscali"),
            "hp": modello.get("hp"),
            "kw": modello.get("kw"),
            "emissioni_co2": safe_float(modello.get("emissioniCo2")),
            "consumo_urbano": safe_float(modello.get("consumoUrbano")),
            "consumo_extraurbano": safe_float(modello.get("consumoExtraurbano")),
            "consumo_medio": safe_float(modello.get("consumoMedio")),
            "accelerazione": safe_float(modello.get("accelerazione")),
            "velocita": modello.get("velocita"),
            "descrizione_marce": modello.get("descrizioneMarce"),
            "cambio": (modello.get("cambio") or {}).get("descrizione"),
            "trazione": (modello.get("trazione") or {}).get("descrizione"),
            "passo": modello.get("passo"),
            "porte": modello.get("porte"),
            "posti": modello.get("posti"),
            "altezza": modello.get("altezza"),
            "larghezza": modello.get("larghezza"),
            "lunghezza": modello.get("lunghezza"),
            "bagagliaio": modello.get("bagagliaio"),
            "pneumatici_anteriori": modello.get("pneumaticiAnteriori"),
            "pneumatici_posteriori": modello.get("pneumaticiPosteriori"),
            "coppia": str(modello.get("coppia")) if modello.get("coppia") is not None else None,
            "numero_giri": modello.get("numeroGiri"),
            "cilindri": str(modello.get("cilindri")) if modello.get("cilindri") is not None else None,
            "valvole": modello.get("valvole"),
            "peso": modello.get("peso"),
            "peso_vuoto": str(modello.get("pesoVuoto")) if modello.get("pesoVuoto") is not None else None,
            "massa_p_carico": str(modello.get("massaPCarico")) if modello.get("massaPCarico") is not None else None,
            "portata": modello.get("portata"),
            "tipo_guida": modello.get("tipoGuida"),
            "neo_patentati": safe_bool(modello.get("neoPatentati")),
            "alimentazione": (modello.get("alimentazione") or {}).get("descrizione"),
            "architettura": (modello.get("architettura") or {}).get("descrizione"),
            "ricarica_standard": safe_bool(modello.get("ricaricaStandard")),
            "ricarica_veloce": safe_bool(modello.get("ricaricaVeloce")),
            "sospensioni_pneumatiche": safe_bool(modello.get("sospPneum")),
            "emissioni_urbe": safe_float(modello.get("emissUrbe")),
            "emissioni_extraurb": safe_float(modello.get("emissExtraurb")),
            "descrizione_breve": modello.get("descrizioneBreve"),
            "peso_potenza": modello.get("pesoPotenza"),
            "volumi": modello.get("volumi"),
            "ridotte": safe_bool(modello.get("ridotte")),
            "paese_prod": modello.get("paeseProd")
        })
        db.commit()
        print(f"✅ Inserito {codice_uni}")
    except Exception as e:
        print(f"❌ Errore salvataggio {codice_uni}: {e}")
        db.rollback()
    finally:
        db.close()

def sync_dettagli_usato():
    db = SessionLocal()
    get_motornet_token()

    allestimenti = db.execute(text("""
        SELECT a.codice_motornet_uni
        FROM mnet_allestimenti_usato a
        LEFT JOIN mnet_dettagli_usato d ON a.codice_motornet_uni = d.codice_motornet_uni
        WHERE d.codice_motornet_uni IS NULL
    """)).fetchall()

    codici = [row[0] for row in allestimenti]
    print(f"🔧 Avvio sync per {len(codici)} allestimenti")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process_codice, codice) for codice in codici]
        for future in as_completed(futures):
            future.result()

    if codici_falliti:
        print(f"\n🔁 Riprovo {len(codici_falliti)} codici falliti in coda...")
        time.sleep(10)
        with ThreadPoolExecutor(max_workers=6) as retry_executor:
            retry_futures = [retry_executor.submit(process_codice, codice) for codice in codici_falliti]
            for future in as_completed(retry_futures):
                future.result()

    print(f"\n✅ Completato: {len(codici)} elaborati, {len(codici_falliti)} falliti.")
    db.close()

if __name__ == "__main__":
    sync_dettagli_usato()
