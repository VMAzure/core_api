import requests
import time

from datetime import datetime
from sqlalchemy.orm import Session
from app.utils.modelli import pulisci_modello
from app.database import SessionLocal
from app.models import MnetModelli
from sqlalchemy import text


MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MOTORN_NUOVO_MODELLI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/modelli"


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

def fetch_modelli_with_retry(marca, max_retries=3):
    attempt = 0
    while attempt < max_retries:
        try:
            token = get_motornet_token()
            headers = {"Authorization": f"Bearer {token}"}
            response = requests.get(
                f"https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/modelli?codice_marca={marca}&anno=2025",
                headers=headers,
            )
            if response.status_code == 200:
                return response.json().get("modelli", [])
            elif response.status_code == 401:
                print(f"🔄 Token scaduto o non valido per {marca}, rigenero... (tentativo {attempt + 1})")
                attempt += 1
                time.sleep(1.5)
            else:
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"❌ Errore di rete su {marca}: {e}")
            attempt += 1
            time.sleep(2)
    raise Exception(f"❌ Errore permanente: impossibile ottenere modelli per {marca} dopo {max_retries} tentativi.")

def sync_modelli():
    db = SessionLocal()

    marche = db.execute(text("SELECT acronimo FROM mnet_marche WHERE utile IS TRUE")).fetchall()

    for marca_tuple in marche:
        marca = marca_tuple[0]
        print(f"🟢 Inizio elaborazione per: {marca}")

        try:
            modelli = fetch_modelli_with_retry(marca)

            for modello_data in modelli:
                if modello_data["fineProduzione"] is None:
                    codice_modello = modello_data["gammaModello"]["codice"]

                    check_query = text("SELECT codice_modello FROM mnet_modelli WHERE codice_modello = :codice_modello")
                    esistente = db.execute(check_query, {"codice_modello": codice_modello}).fetchone()

                    if esistente:
                        print(f"⏩ Modello {codice_modello} già presente, salto.")
                        continue

                    insert_query = text("""
                        INSERT INTO mnet_modelli (
                            codice_modello, descrizione, marca_acronimo, inizio_produzione,
                            fine_produzione, gruppo_storico_codice, gruppo_storico_descrizione,
                            serie_gamma_codice, serie_gamma_descrizione,
                            inizio_commercializzazione, fine_commercializzazione
                        ) VALUES (
                            :codice_modello, :descrizione, :marca_acronimo, :inizio_produzione,
                            :fine_produzione, :gruppo_storico_codice, :gruppo_storico_descrizione,
                            :serie_gamma_codice, :serie_gamma_descrizione,
                            :inizio_commercializzazione, :fine_commercializzazione
                        )
                    """)

                    db.execute(insert_query, {
                        "codice_modello": codice_modello,
                        "descrizione": modello_data["gammaModello"]["descrizione"],
                        "marca_acronimo": marca,
                        "inizio_produzione": modello_data["inizioProduzione"],
                        "fine_produzione": None,
                        "gruppo_storico_codice": modello_data["gruppoStorico"]["codice"],
                        "gruppo_storico_descrizione": modello_data["gruppoStorico"]["descrizione"],
                        "serie_gamma_codice": modello_data["serieGamma"]["codice"],
                        "serie_gamma_descrizione": modello_data["serieGamma"]["descrizione"],
                        "inizio_commercializzazione": modello_data["inizioCommercializzazione"],
                        "fine_commercializzazione": None,
                    })

                    db.commit()
                    print(f"✅ Inserito modello {codice_modello}")

            print(f"✅ Completata marca: {marca}")

        except Exception as e:
            print(f"❌ Errore su marca {marca}: {e}")

    db.close()

if __name__ == "__main__":
    sync_modelli()