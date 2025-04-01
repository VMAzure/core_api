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
# NUOVO - Endpoint Motornet per veicoli NUOVI
MOTORN_NUOVO_MARCHE_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/marche"
MOTORN_NUOVO_MODELLI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/marca/modelli"
MOTORN_NUOVO_ALLESTIMENTI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/modello/versioni"

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

import httpx

@router.get("/dettagli/{codice_motornet}", tags=["Motornet"])
async def get_dettagli_auto(codice_motornet: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()

    headers = {
        "Authorization": f"Bearer {token}"
    }

    motornet_url = f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/dettaglio?codice_motornet_uni={codice_motornet}"

    async with httpx.AsyncClient() as client:
        response = await client.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Dettagli Auto: {response.text}")

    if response.status_code == 200:
        return response.json()

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

@router.get("/accessori/{codice_motornet}/{anno}/{mese}", tags=["Motornet"])
async def get_accessori_auto(
    codice_motornet: str,
    anno: int,
    mese: int,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """Recupera tutti gli accessori di un veicolo usato tramite il codice Motornet univoco"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    motornet_url = (
        f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/accessori"
        f"?codice_motornet_uni={codice_motornet}"
        f"&anno={anno}"
        f"&mese={mese}"
    )

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Accessori: {response.text}")  # 🔹 Stampa la risposta ricevuta

    if response.status_code == 200:
        data = response.json()
        return data  # 🔹 Restituiamo tutti i dati ricevuti senza modificarli

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero degli accessori del veicolo")

@router.get("/nuovo/marche", tags=["Motornet"])
async def get_marche_nuovo(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera la lista delle marche da Motornet per il mercato del NUOVO (utenti autenticati)"""
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()

    headers = {
        "Authorization": f"Bearer {token}"
    }

    response = requests.get(MOTORN_NUOVO_MARCHE_URL, headers=headers)

    if response.status_code == 200:
        data = response.json()

        marche_pulite = [
            {
                "acronimo": marca.get("acronimo"),
                "nome": marca.get("nome"),
                "logo": marca.get("logo")
            }
            for marca in data.get("marche", [])
        ]

        return marche_pulite

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero delle marche (nuovo)")

from datetime import datetime

@router.get("/nuovo/modelli/{codice_marca}", tags=["Motornet"])
async def get_modelli_nuovo(
    codice_marca: str,
    anno: int = None,
    codice_tipo: str = None,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()
    headers = {"Authorization": f"Bearer {token}"}

    if anno is None:
        anno = datetime.today().year

    # Componiamo l'URL dinamicamente
    motornet_url = (
        f"https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/modelli"
        f"?codice_marca={codice_marca}&anno={anno}"
    )

    if codice_tipo:
        motornet_url += f"&codice_tipo={codice_tipo}"

    response = requests.get(motornet_url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        modelli_puliti = [
            {
                "codice": modello["gammaModello"]["codice"] if modello.get("gammaModello") else None,
                "descrizione": modello["gammaModello"]["descrizione"] if modello.get("gammaModello") else None,
                "inizio_produzione": modello.get("inizioProduzione"),
                "fine_produzione": modello.get("fineProduzione"),
                "gruppo_storico": modello["gruppoStorico"]["descrizione"] if modello.get("gruppoStorico") else None,
                "serie_gamma": modello["serieGamma"]["descrizione"] if modello.get("serieGamma") else None,
                "codice_desc_modello": modello["codDescModello"]["codice"] if modello.get("codDescModello") else None,
                "descrizione_dettagliata": modello["codDescModello"]["descrizione"] if modello.get("codDescModello") else None,
                "inizio_commercializzazione": modello.get("inizioCommercializzazione"),
                "fine_commercializzazione": modello.get("fineCommercializzazione"),
                "modello": modello.get("modello"),
                "foto": modello.get("foto"),
                "prezzo_minimo": modello.get("prezzoMinimo"),
                "modello_breve_carrozzeria": modello.get("modelloBreveCarrozzeria")
            }
            for modello in data.get("modelli", [])
        ]
        return modelli_puliti

    raise HTTPException(status_code=response.status_code, detail="Errore recupero modelli nuovo")

@router.get("/nuovo/versioni/{codice_marca}/{codice_modello}", tags=["Motornet"])
async def get_versioni_nuovo(
    codice_marca: str,
    codice_modello: str,
    anno: int = None,
    codice_alimentazione: str = None,
    tipologia: str = None,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()
    headers = {"Authorization": f"Bearer {token}"}

    if anno is None:
        anno = datetime.today().year

    params = {
        "codice_modello": codice_modello,
        "anno": anno,
        "codice_marca": codice_marca,
    }

    if codice_alimentazione:
        params["codice_alimentazione"] = codice_alimentazione

    if tipologia:
        params["tipologia"] = tipologia

    motornet_url = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/versioni"

    response = requests.get(motornet_url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        versioni_pulite = [
            {
                "codice_univoco": versione.get("codiceMotornetUnivoco"),
                "codice_motornet": versione.get("codiceMotornet"),
                "da": versione.get("da"),
                "a": versione.get("a"),
                "inizio_produzione": versione.get("inizioProduzione"),
                "fine_produzione": versione.get("fineProduzione"),
                "nome": versione.get("nome"),
                "marca_acronimo": versione["marca"]["acronimo"] if versione.get("marca") else None,
                "marca_nome": versione["marca"]["nome"] if versione.get("marca") else None,
            }
            for versione in data.get("versioni", [])
        ]
        return versioni_pulite

    raise HTTPException(status_code=response.status_code, detail="Errore recupero versioni nuovo")

@router.get("/nuovo/alimentazioni/{codice_modello}", tags=["Motornet"])
async def get_alimentazioni_nuovo(
    codice_modello: str,
    anno: int = None,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    if anno is None:
        anno = datetime.today().year

    token = get_motornet_token()
    headers = {"Authorization": f"Bearer {token}"}

    motornet_url = (
        f"https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/alimentazioni"
        f"?codice_modello={codice_modello}&anno={anno}"
    )

    response = requests.get(motornet_url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        alimentazioni = [
            {
                "codice": alimentazione.get("codice"),
                "descrizione": alimentazione.get("descrizione")
            }
            for alimentazione in data.get("alimentazioni", [])
        ]
        return alimentazioni

    raise HTTPException(status_code=response.status_code, detail="Errore recupero alimentazioni nuovo")










