from fastapi import APIRouter, HTTPException, Depends
import requests
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from app.routes.auth import get_current_user
from app.database import get_db  # ✅ Import corretto per il DB
from app.models import User  # ✅ Import del modello User se necessario
from datetime import datetime



router = APIRouter()



# Configurazioni API Motornet
MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MOTORN_MARCHE_URL = "https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/marche"


# Credenziali API Motornet
MOTORN_CLIENT_ID = "azure447"
MOTORN_CLIENT_SECRET = "azwsn557"

import time

cached_token = None
token_expiry = 0

def get_motornet_token():
    """Ottiene e memorizza il token di accesso da Motornet per evitare richieste ripetute"""
    global cached_token, token_expiry

    # Se abbiamo un token valido, lo riutilizziamo
    if cached_token and time.time() < token_expiry:
        print("🔍 DEBUG: Riutilizzo token esistente")
        return cached_token

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    payload = {
        "grant_type": "password",
        "client_id": "webservice",
        "username": MOTORN_CLIENT_ID,
        "password": MOTORN_CLIENT_SECRET
    }

    response = requests.post(MOTORN_AUTH_URL, headers=headers, data=payload)

    print(f"🔍 DEBUG: Status Code Token Motornet = {response.status_code}")

    if response.status_code == 200:
        token_data = response.json()
        cached_token = token_data.get("access_token")
        token_expiry = time.time() + token_data.get("expires_in", 300) - 10  # Riduciamo 10 sec per sicurezza

        print(f"🔍 DEBUG: Nuovo token salvato: {cached_token}")
        return cached_token
    
    print(f"❌ DEBUG: Errore nel recupero del token: {response.text}")
    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero del token")


@router.get("/marche", tags=["Motornet"])
async def get_marche(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera la lista delle marche da Motornet solo per utenti autenticati"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet

    headers = {
        "Authorization": f"Bearer {token}"
    }

    response = requests.get(MOTORN_MARCHE_URL, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Marche: {response.text}")  # 🔹 Stampa il JSON ricevuto

    if response.status_code == 200:
        data = response.json()

        # Estraggo solo i dati utili
        marche_pulite = [
            {
                "acronimo": marca.get("acronimo"),
                "nome": marca.get("nome"),
                "logo": marca.get("logo")
            }
            for marca in data.get("marche", [])
        ]

        return marche_pulite

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero delle marche")

@router.get("/modelli/{codice_marca}", tags=["Motornet"])
async def get_modelli(codice_marca: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera la lista dei modelli per una marca specifica"""
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    motornet_url = f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/marca/modelli?codice_marca={codice_marca}"

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta completa di Motornet:")
    print(response.text)  # 🔹 Stampiamo il JSON completo per analizzarlo

    if response.status_code == 200:
        data = response.json()

        # Estraggo solo i dati utili
        modelli_puliti = [
    {
        "codice": modello["gammaModello"]["codice"] if modello.get("gammaModello") else None,
        "descrizione": modello["gammaModello"]["descrizione"] if modello.get("gammaModello") else None,
        "inizio_produzione": modello.get("inizioProduzione"),
        "fine_produzione": modello.get("fineProduzione"),
        "gruppo_storico": modello["gruppoStorico"]["descrizione"] if modello.get("gruppoStorico") else None,
        "serie_gamma": modello["serieGamma"]["descrizione"] if modello.get("serieGamma") else None,
        "codice_desc_modello": modello["codDescModello"]["codice"] if modello.get("codDescModello") else None,
        "descrizione_dettagliata": modello["codDescModello"]["descrizione"] if modello.get("codDescModello") else None
    }
    for modello in data.get("modelli", [])
]



        return modelli_puliti

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero dei modelli")

@router.get("/allestimenti/{codice_marca}/{codice_modello}", tags=["Motornet"])
async def get_allestimenti(codice_marca: str, codice_modello: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera la lista degli allestimenti per un modello specifico"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    motornet_url = f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/modello/versioni?codice_modello={codice_modello}&codice_marca={codice_marca}"

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Allestimenti: {response.text}")  # 🔹 Stampa la risposta ricevuta

    if response.status_code == 200:
        data = response.json()

        # Estraggo solo i dati utili
        allestimenti_puliti = [
    {
        "codice_univoco": versione.get("codiceMotornetUnivoco"),
        "versione": versione.get("nome"),  # 🔹 Nome dell'allestimento
        "inizio_produzione": versione.get("inizioProduzione"),  # 🔹 Data di inizio produzione
        "fine_produzione": versione.get("fineProduzione"),  # 🔹 Data di fine produzione
        "marca": versione["marca"]["nome"] if versione.get("marca") else None  # 🔹 Nome della marca
    }
    for versione in data.get("versioni", [])
]


        return allestimenti_puliti

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero degli allestimenti")

@router.get("/dettagli/{codice_motornet}", tags=["Motornet"])
async def get_dettagli_auto(codice_motornet: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera tutti i dettagli di un'auto specifica tramite il codice Motornet univoco"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    motornet_url = f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/dettaglio?codice_motornet_uni={codice_motornet}"

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Dettagli Auto: {response.text}")  # 🔹 Stampa la risposta ricevuta

    if response.status_code == 200:
        data = response.json()
        return data  # 🔹 Restituiamo tutti i dati ricevuti senza modificarli

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero dei dettagli del veicolo")


@router.get("/valutazione/{codice_motornet}/{anno_immatricolazione}/{mese_immatricolazione}", tags=["Motornet"])
async def get_valutazione_auto(
    codice_motornet: str,
    anno_immatricolazione: int,
    mese_immatricolazione: int,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """Recupera la quotazione base e il deprezzamento di un veicolo rispetto alla data di immatricolazione"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    # 📌 Impostiamo automaticamente la data di valutazione a OGGI
    oggi = datetime.today()
    anno_valutazione = oggi.year
    mese_valutazione = oggi.month

    motornet_url = (
        f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/valutazione/deprezzamento"
        f"?codice_motornet_uni={codice_motornet}"
        f"&anno_immatricolazione={anno_immatricolazione}"
        f"&mese_immatricolazione={mese_immatricolazione}"
        f"&anno_valutazione={anno_valutazione}"
        f"&mese_valutazione={mese_valutazione}"
    )

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Valutazione: {response.text}")  # 🔹 Stampa la risposta ricevuta

    if response.status_code == 200:
        data = response.json()
        return data  # 🔹 Restituiamo l'intero JSON senza modificarlo

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero della valutazione")

@router.get("/marche/{anno}", tags=["Motornet"])
async def get_marche_per_anno(anno: int, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera la lista delle marche per un anno specifico"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    motornet_url = f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/marche/{anno}"

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Marche per anno: {response.text}")  # 🔹 Stampa la risposta ricevuta

    if response.status_code == 200:
        data = response.json()

        # Estraggo solo i dati utili
        marche_pulite = [
            {
                "acronimo": marca.get("acronimo"),
                "nome": marca.get("nome")
            }
            for marca in data.get("marche", [])
        ]

        return marche_pulite

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero delle marche per l'anno specificato")





