import requests
import time
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed

MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
DETTAGLI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/dettaglio"

# Setup session factory
SessionLocal = sessionmaker(bind=engine)
token_lock = Lock()
shared_token = {"value": None}
fail_lock = Lock()
codici_falliti = []
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
            response = requests.post(MOTORN_AUTH_URL, data=data)
            response.raise_for_status()
            token = response.json().get('access_token')
            shared_token["value"] = token
            return token
        except requests.exceptions.RequestException as e:
            print(f"❌ Errore durante richiesta token (tentativo {attempt+1}): {e}")
            time.sleep(2)
    raise Exception("❌ Impossibile ottenere il token dopo 3 tentativi.")

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
            INSERT INTO mnet_dettagli (
                codice_motornet_uni, alimentazione, cilindrata, hp, kw, euro,
                consumo_medio, consumo_urbano, consumo_extraurbano, emissioni_co2,
                tipo_cambio, trazione, porte, posti, lunghezza, larghezza, altezza,
                peso, velocita, accelerazione, bagagliaio, foto, prezzo_listino,
                data_listino, descrizione_breve, neo_patentati, architettura,
                peso_potenza, coppia, numero_giri, valvole, passo,
                pneumatici_anteriori, pneumatici_posteriori, massa_p_carico,
                indice_carico, codice_velocita, cap_serb_litri, peso_vuoto,
                paese_prod, tipo_guida, cambio_descrizione, marce, tipo_motore,
                descrizione_motore, codice_costruttore, modello_breve_carrozzeria,
                nome_cambio, segmento, segmento_descrizione, tipo, tipo_descrizione,
                cavalli_fiscali, cilindri, altezza_minima, autonomia_media,
                autonomia_massima, cavalli_ibrido, cavalli_totale, potenza_ibrido,
                potenza_totale, coppia_ibrido, coppia_totale, equipaggiamento,
                garanzia_km, garanzia_tempo, guado, hc, nox, numero_giri_ibrido,
                numero_giri_totale, sosp_pneum, tipo_batteria, traino, volumi,
                portata, posti_max, pm10, ricarica_standard, ricarica_veloce,
                ridotte, pendenza_max, cap_serb_kg, motore_elettrico, motore_ibrido,
                capacita_nominale_batteria, capacita_netta_batteria,
                cavalli_elettrico_max, cavalli_elettrico_boost_max,
                potenza_elettrico_max, potenza_elettrico_boost_max, wltp, freni
            )
            VALUES (
                :codice_uni, :alimentazione, :cilindrata, :hp, :kw, :euro,
                :consumo_medio, :consumo_urbano, :consumo_extraurbano, :emissioni_co2,
                :tipo_cambio, :trazione, :porte, :posti, :lunghezza, :larghezza, :altezza,
                :peso, :velocita, :accelerazione, :bagagliaio, :foto, :prezzo_listino,
                :data_listino, :descrizione_breve, :neo_patentati, :architettura,
                :peso_potenza, :coppia, :numero_giri, :valvole, :passo,
                :pneumatici_anteriori, :pneumatici_posteriori, :massa_p_carico,
                :indice_carico, :codice_velocita, :cap_serb_litri, :peso_vuoto,
                :paese_prod, :tipo_guida, :cambio_descrizione, :marce, :tipo_motore,
                :descrizione_motore, :codice_costruttore, :modello_breve_carrozzeria,
                :nome_cambio, :segmento, :segmento_descrizione, :tipo, :tipo_descrizione,
                :cavalli_fiscali, :cilindri, :altezza_minima, :autonomia_media,
                :autonomia_massima, :cavalli_ibrido, :cavalli_totale, :potenza_ibrido,
                :potenza_totale, :coppia_ibrido, :coppia_totale, :equipaggiamento,
                :garanzia_km, :garanzia_tempo, :guado, :hc, :nox, :numero_giri_ibrido,
                :numero_giri_totale, :sosp_pneum, :tipo_batteria, :traino, :volumi,
                :portata, :posti_max, :pm10, :ricarica_standard, :ricarica_veloce,
                :ridotte, :pendenza_max, :cap_serb_kg, :motore_elettrico, :motore_ibrido,
                :capacita_nominale_batteria, :capacita_netta_batteria,
                :cavalli_elettrico_max, :cavalli_elettrico_boost_max,
                :potenza_elettrico_max, :potenza_elettrico_boost_max, :wltp, :freni
            )
        """), {
            "codice_uni": codice_uni,
            "alimentazione": modello["alimentazione"]["descrizione"] if modello.get("alimentazione") else None,
            "cilindrata": modello.get("cilindrata"),
            "hp": modello.get("hp"),
            "kw": modello.get("kw"),
            "euro": modello.get("euro"),
            "consumo_medio": modello.get("consumoMedio"),
            "consumo_urbano": modello.get("consumoUrbano"),
            "consumo_extraurbano": modello.get("consumoExtraurbano"),
            "emissioni_co2": modello.get("emissioniCo2"),
            "tipo_cambio": modello["cambio"]["descrizione"] if modello.get("cambio") else None,
            "trazione": modello["trazione"]["descrizione"] if modello.get("trazione") else None,
            "porte": modello.get("porte"),
            "posti": modello.get("posti"),
            "lunghezza": modello.get("lunghezza"),
            "larghezza": modello.get("larghezza"),
            "altezza": modello.get("altezza"),
            "peso": modello.get("peso"),
            "velocita": modello.get("velocita"),
            "accelerazione": modello.get("accelerazione"),
            "bagagliaio": modello.get("bagagliaio"),
            "foto": modello.get("immagine"),
            "prezzo_listino": modello.get("prezzoListino"),
            "data_listino": modello.get("dataListino"),
            "descrizione_breve": modello.get("descrizioneBreve"),
            "neo_patentati": bool(modello.get("neoPatentati")) if modello.get("neoPatentati") is not None else None,
            "architettura": modello["architettura"]["descrizione"] if modello.get("architettura") else None,
            "peso_potenza": modello.get("pesoPotenza"),
            "coppia": modello.get("coppia"),
            "numero_giri": modello.get("numeroGiri"),
            "valvole": modello.get("valvole"),
            "passo": modello.get("passo"),
            "pneumatici_anteriori": modello.get("pneumaticiAnteriori"),
            "pneumatici_posteriori": modello.get("pneumaticiPosteriori"),
            "massa_p_carico": modello.get("massaPCarico"),
            "indice_carico": modello.get("indiceCarico"),
            "codice_velocita": modello.get("codVel"),
            "cap_serb_litri": modello.get("capSerbLitri"),
            "peso_vuoto": modello.get("pesoVuoto"),
            "paese_prod": modello.get("paeseProd"),
            "tipo_guida": modello.get("tipoGuida"),
            "cambio_descrizione": modello.get("descrizioneMarce"),
            "marce": modello.get("descrizioneMarce"),
            "tipo_motore": modello.get("tipoMotore"),
            "descrizione_motore": modello.get("descrizioneMotore"),
            "codice_costruttore": modello.get("codiceCostruttore"),
            "modello_breve_carrozzeria": modello.get("modelloBreveCarrozzeria"),
            "nome_cambio": modello.get("nomeCambio"),
            "segmento": modello["segmento"]["codice"] if modello.get("segmento") else None,
            "segmento_descrizione": modello["segmento"]["descrizione"] if modello.get("segmento") else None,
            "tipo": modello["tipo"]["codice"] if modello.get("tipo") else None,
            "tipo_descrizione": modello["tipo"]["descrizione"] if modello.get("tipo") else None,
            "cavalli_fiscali": modello.get("cavalliFiscali"),
            "cilindri": modello.get("cilindri"),
            "altezza_minima": modello.get("altezzaMinima"),
            "autonomia_media": modello.get("autonomiaMedia"),
            "autonomia_massima": modello.get("autonomiaMassima"),
            "cavalli_ibrido": modello.get("cavalliIbrido"),
            "cavalli_totale": modello.get("cavalliTotale"),
            "potenza_ibrido": modello.get("potenzaIbrido"),
            "potenza_totale": modello.get("potenzaTotale"),
            "coppia_ibrido": modello.get("coppiaIbrido"),
            "coppia_totale": modello.get("coppiaTotale"),
            "equipaggiamento": modello.get("equipaggiamento"),
            "garanzia_km": modello.get("garanziaKm"),
            "garanzia_tempo": modello.get("garanziaTempo"),
            "guado": modello.get("guado"),
            "hc": modello.get("hc"),
            "nox": modello.get("nox"),
            "numero_giri_ibrido": modello.get("numeroGiriIbrido"),
            "numero_giri_totale": modello.get("numeroGiriTotale"),
            "sosp_pneum": bool(modello.get("sospPneum")) if modello.get("sospPneum") is not None else None,
            "tipo_batteria": modello.get("tipoBatteria"),
            "traino": modello.get("traino"),
            "volumi": modello.get("volumi"),
            "portata": modello.get("portata"),
            "posti_max": modello.get("postiMax"),
            "pm10": modello.get("pm10"),
            "ricarica_standard": modello.get("ricaricaStandard"),
            "ricarica_veloce": modello.get("ricaricaVeloce"),
            "ridotte": bool(modello.get("ridotte")) if modello.get("ridotte") is not None else None,
            "pendenza_max": modello.get("pendenzaMax"),
            "cap_serb_kg": modello.get("capSerbKg"),
            "motore_elettrico": modello["motoreElettrico"]["descrizione"] if modello.get("motoreElettrico") and isinstance(modello["motoreElettrico"], dict) else None,
            "motore_ibrido": modello["motoreIbrido"]["descrizione"] if modello.get("motoreIbrido") and isinstance(modello["motoreIbrido"], dict) else None,
            "capacita_nominale_batteria": modello.get("capacitaNominaleBatteria"),
            "capacita_netta_batteria": modello.get("capacitaNettaBatteria"),
            "cavalli_elettrico_max": modello.get("cavalliElettricoMax"),
            "cavalli_elettrico_boost_max": modello.get("cavalliElettricoBoostMax"),
            "potenza_elettrico_max": modello.get("potenzaElettricoMax"),
            "potenza_elettrico_boost_max": modello.get("potenzaElettricoBoostMax"),
            "wltp": modello.get("wltp"),
            "freni": modello["freni"]["descrizione"] if modello.get("freni") else None,
        })
        db.commit()
        print(f"✅ Inserito {codice_uni}")
    except Exception as e:
        print(f"❌ Errore salvataggio {codice_uni}: {e}")
        db.rollback()
    finally:
        db.close()

def sync_dettagli_auto():
    db = SessionLocal()
    get_motornet_token()

    allestimenti = db.execute(text("""
        SELECT a.codice_motornet_uni
        FROM mnet_allestimenti a
        LEFT JOIN mnet_dettagli d ON a.codice_motornet_uni = d.codice_motornet_uni
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

    db.close()


if __name__ == "__main__":
    sync_dettagli_auto()
