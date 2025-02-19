import sys
import os

# Otteniamo il percorso assoluto del progetto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

# Aggiungiamo il percorso del progetto a sys.path se non è già presente
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

print(f"🔍 DEBUG: Il percorso del progetto è stato aggiunto a sys.path → {PROJECT_ROOT}")

import traceback
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import OAuth2PasswordBearer
from fastapi_jwt_auth import AuthJWT
from pydantic import BaseModel
# Importiamo database e modelli
from app.database import engine
from app.models import Base
from app.routes.auth import router as auth_router
from app.routes.users import router as users_router
from app.routes.transactions import router as transactions_router
from app import models  # Importiamo i modelli prima di avviare l'app




# Aggiungiamo il percorso della cartella principale al sys.path per evitare errori di import
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Creazione dell'istanza di FastAPI
app = FastAPI(title="CORE API", version="1.0")
# Marketplace
from app.routes.marketplace import marketplace_router
app.include_router(marketplace_router, prefix="/api")
# Configurazione dello schema di autenticazione Bearer per Swagger UI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def refresh_openapi():
    app.openapi_schema = None
    return get_openapi(
        title="CORE API",
        version="1.0",
        description="API per la gestione di utenti e crediti",
        routes=app.routes,
    )

app.openapi = refresh_openapi

# Funzione per personalizzare OpenAPI senza eliminare la documentazione

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="CORE API",
        version="1.0",
        description="API per la gestione di utenti e crediti",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


# Middleware per la gestione delle richieste e della sicurezza
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusione delle route (senza prefisso duplicato)
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(users_router, prefix="/users", tags=["Users"])
app.include_router(transactions_router, prefix="/transactions", tags=["Transactions"])

@app.get("/")
def read_root():
    return {"message": "Welcome to CORE API"}

# Avvio dell'applicazione solo se il file viene eseguito direttamente
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
    
@app.post("/debug/test")
def debug_test():
    return {"message": "API sta ricevendo le richieste"}
    

@app.get("/debug/jwt-key")
def get_jwt_key():
    return {"AUTHJWT_SECRET_KEY": os.getenv("AUTHJWT_SECRET_KEY")}