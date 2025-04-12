import sys
import os
import logging
import traceback
from sqlalchemy import false
import uvicorn
from fastapi import FastAPI, APIRouter, Depends, HTTPException, File, UploadFile, Form
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import OAuth2PasswordBearer
from fastapi_jwt_auth import AuthJWT
from fastapi_jwt_auth.exceptions import AuthJWTException
from pydantic import BaseSettings
from dotenv import load_dotenv  # ✅ Importiamo dotenv PRIMA di qualsiasi import dipendente dalle variabili
from fastapi.responses import JSONResponse


# ✅ Carichiamo le variabili d'ambiente PRIMA di qualsiasi import di moduli che le usano
load_dotenv()

# ✅ Ora possiamo importare i moduli che dipendono dalle variabili d'ambiente
from app.database import engine
from app.models import Base
from app.routes.auth import router as auth_router
from app.routes.users import router as users_router
from app.routes.transactions import router as transactions_router
from app.routes.marketplace import marketplace_router  # 🔹 Importato DOPO dotenv!
from app.routes.logs import logs_router
from app import models
import threading
from app.routes.services import service_router
from app.routes.customers import router as customers_router
from app.routes.nlt import router as nlt_router
from app.routes import status
from app.tasks import scheduler
from app.routes.smtp_settings import router as smtp_router
from app.routes.site_settings import router as site_settings_router
from app.routes.motornet import router_usato, router_nuovo, router_generic
from app.routes.azlease import router as azlease_router
from app.schemas import AutoUsataCreate
from app.routes.openapi import router as openapi_router
from app.routes.pdf import router as pdf_router
from app.routes.nlt_offerte import router as nlt_offerte_router
from app.routes import tools
from app.routes.image import router as image_router






# ✅ Configuriamo il logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("uvicorn")

logger.debug("✅ DEBUG: Logger FastAPI/Uvicorn attivo")

# ✅ Debug delle variabili Supabase
print("✅ DEBUG (main.py) - SUPABASE_URL:", os.getenv("SUPABASE_URL"))
print("✅ DEBUG (main.py) - SUPABASE_KEY:", os.getenv("SUPABASE_KEY"))

# ✅ Creazione dell'istanza di FastAPI
app = FastAPI(title="CORE API", version="1.0")

# ✅ Avvia il cron job in un thread separato all'avvio dell'app

@app.on_event("startup")
def start_cron_job():
    scheduler.start()
    print("✅ Cron job APScheduler avviato!")

# ✅ Configurazione dello schema di autenticazione Bearer per Swagger UI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# 🔹 CONFIGURAZIONE JWT
class Settings(BaseSettings):
    authjwt_secret_key: str = os.getenv("AUTHJWT_SECRET_KEY", "chiave-di-default")
    authjwt_algorithm: str = "HS256"

@AuthJWT.load_config
def get_config():
    return Settings()

@app.exception_handler(AuthJWTException)
def authjwt_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message}
    )


# ✅ Personalizzazione OpenAPI
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

#app.add_middleware(
#    CORSMiddleware,
#    allow_origins=[
#       "https://corewebapp-azcore.up.railway.app",
#       "https://cigpdfgenerator-production.up.railway.app",
#       "https://localhost:7125",  
#       "http://localhost:7125",   
#       "http://localhost",        
#    ],

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:7026",
        "https://localhost:7026",# 👉 la tua app in locale
        "https://corewebapp-azcore.up.railway.app",  # 👉 dominio pubblico
        "https://cigpdfgenerator-production.up.railway.app",
        "https://cig.up.railway.app/",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
#   allow_credentials=True,
#     allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
#     allow_headers=["Authorization", "Content-Type"]




# ✅ Inclusione delle route (senza prefisso duplicato)
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(users_router, prefix="/users", tags=["Users"])
app.include_router(transactions_router, prefix="/transactions", tags=["Transactions"])
app.include_router(marketplace_router, prefix="/api")  # ✅ Ora Marketplace viene importato con le variabili già caricate!
app.include_router(logs_router)
app.include_router(service_router, prefix="/api")  # 🔹 Aggiunto il prefisso /api"
app.include_router(customers_router, prefix="/customers", tags=["Customers"])
app.include_router(nlt_router, prefix="")
app.include_router(status.router, prefix="/api")
app.include_router(smtp_router, prefix="/api")
app.include_router(site_settings_router, prefix="/api")
app.include_router(azlease_router, prefix="/api/azlease")
app.include_router(openapi_router, prefix="/api")
app.include_router(pdf_router, prefix="/pdf",tags=["PDF"])
app.include_router(nlt_offerte_router)
app.include_router(router_generic, prefix="/api")
app.include_router(router_usato, prefix="/api")
app.include_router(router_nuovo, prefix="/api")
app.include_router(tools.router, prefix="/tools", tags=["Tools"])
app.include_router(image_router)
app.include_router(quotazioni_router)




@app.get("/")
def read_root():
    return {"message": "Welcome to CORE API"}

# ✅ Endpoint di debug
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

# ✅ Avvio dell'applicazione
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
