from fastapi import APIRouter, HTTPException, Depends
import requests
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from app.routes.auth import get_current_user
from app.database import get_db  # ✅ Import corretto per il DB
from app.models import User  # ✅ Import del modello User se necessario


router = APIRouter()



# Configurazioni API Motornet
MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MOTORN_MARCHE_URL = "https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/marche"


# Credenziali API Motornet
MOTORN_CLIENT_ID = "azure447"
MOTORN_CLIENT_SECRET = "azwsn557"

def get_motornet_token():
    """Ottiene il token di accesso da Motornet"""
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

    print(f"🔍 DEBUG: Status Code Motornet = {response.status_code}")
    print(f"🔍 DEBUG: Risposta Motornet = {response.text}")  # 🔹 Stampiamo la risposta per debug

    if response.status_code == 200:
        return response.json().get("access_token")
    
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
                "codice": modello.get("codice"),
                "descrizione": modello.get("descrizione")
            }
            for modello in data.get("modelli", [])  # 🔹 Verifichiamo se "modelli" esiste
        ]

        return modelli_puliti

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero dei modelli")


