from fastapi import APIRouter, HTTPException, Depends
import requests
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from app.routes.auth import get_current_user
from app.database import get_db  # ✅ Import corretto per il DB
from app.models import User  # ✅ Import del modello User se necessario


router = APIRouter()

# Configurazioni API Motornet
MOTORN_API_BASE_URL = "https://webservice.motornet.it/api/v3_0/rest"
MOTORN_AUTH_URL = f"{MOTORN_API_BASE_URL}/auth/token"
MOTORN_MARCHE_URL = f"{MOTORN_API_BASE_URL}/public/usato/auto/marche"

# Credenziali API Motornet
MOTORN_CLIENT_ID = "IL_TUO_CLIENT_ID"
MOTORN_CLIENT_SECRET = "IL_TUO_CLIENT_SECRET"

def get_motornet_token():
    """Ottiene il token di accesso da Motornet"""
    payload = {
        "grant_type": "password",
        "client_id": "webservice",
        "username": "azure447",
        "password": "azwsn557"
    }

    response = requests.post(MOTORN_AUTH_URL, data=payload)
    print(f"🔍 DEBUG: Status Code Motornet = {response.status_code}")
    print(f"🔍 DEBUG: Risposta Motornet = {response.text}")  

    if response.status_code == 200:
        return response.json().get("access_token")
    
    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero del token")



@router.get("/marche", tags=["Motornet"])
async def get_marche(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera la lista delle marche da Motornet solo per utenti autenticati"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT
    user_email = Authorize.get_jwt_subject()  # 🔹 Ottiene l'email dell'utente autenticato

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()

    headers = {
        "Authorization": f"Bearer {token}"
    }

    response = requests.get(MOTORN_MARCHE_URL, headers=headers, params={"libro": "false"})

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

