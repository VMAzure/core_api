import sys
import os
import logging

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("uvicorn")

logger.debug("✅ DEBUG: Logger FastAPI/Uvicorn attivo")

# Otteniamo il percorso assoluto del progetto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

# Aggiungiamo il percorso del progetto a sys.path se non è già presente
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

print(f"🔍 DEBUG: Il percorso del progetto è stato aggiunto a sys.path → {PROJECT_ROOT}")

import traceback
import uvicorn
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import OAuth2PasswordBearer
from fastapi_jwt_auth import AuthJWT
from fastapi_jwt_auth.exceptions import AuthJWTException
from pydantic import BaseSettings

# Importiamo database e modelli
from app.database import engine
from app.models import Base
from app.routes.auth import router as auth_router
from app.routes.users import router as users_router
from app.routes.transactions import router as transactions_router
from app.routes.marketplace import marketplace_router
from app.routes.logs import logs_router
from app import models  # Importiamo i modelli prima di avviare l'app
import threading
from app.tasks import run_scheduler
from fastapi import FastAPI


# Creazione dell'istanza di FastAPI
app = FastAPI(title="CORE API", version="1.0")

# ✅ Avvia il cron job in un thread separato all'avvio dell'app
@app.on_event("startup")
def start_cron_job():
    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()
    print("✅ Cron job avviato!")

# Configurazione dello schema di autenticazione Bearer per Swagger UI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# 🔹 CONFIGURAZIONE JWT (Versione 0.5.0)
class Settings(BaseSettings):
    authjwt_secret_key: str = os.getenv("AUTHJWT_SECRET_KEY", "chiave-di-default")
    authjwt_algorithm: str = "HS256"

@AuthJWT.load_config
def get_config():
    return Settings()

# 🔹 Handler per errori JWT
@app.exception_handler(AuthJWTException)
def authjwt_exception_handler(request, exc):
    return HTTPException(status_code=exc.status_code, detail=exc.message)

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
    allow_origins=["https://corewebapp-azcore.up.railway.app"],  # ❌ Deve essere aggiornato quando cambi dominio
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"]
    app.add_middleware(
    )
)

# Inclusione delle route (senza prefisso duplicato)
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(users_router, prefix="/users", tags=["Users"])
app.include_router(transactions_router, prefix="/transactions", tags=["Transactions"])
app.include_router(marketplace_router, prefix="/api")
app.include_router(logs_router)
app.include_router(users_router, prefix="/users", tags=["Users"])
                                                )

@app.get("/")
def read_root():
    return {"message": "Welcome to CORE API"}

# Endpoint di debug
@app.post("/debug/test")
def debug_test():
    return {"message": "API sta ricevendo le richieste"}

@app.get("/debug/jwt-config")
def get_jwt_config(Authorize: AuthJWT = Depends()):
    """Verifica la configurazione JWT e genera un token di test"""
    try:
        token_test = Authorize.create_access_token(subject="test-user")
        return {
            "authjwt_secret_key": os.getenv("AUTHJWT_SECRET_KEY", "chiave-di-default"),
            "token_test": token_test
        }
    except Exception as e:
        return {"error": str(e)}

# Avvio dell'applicazione solo se il file viene eseguito direttamente
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
