from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal
from app.models import Services, PurchasedServices, AssignedServices, User

# ✅ Creiamo il router per l'endpoint
service_router = APIRouter(prefix="/services", tags=["Services"])

# ✅ Funzione per ottenere la sessione DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ API per ottenere i dettagli di un servizio
@service_router.get("/{service_id}")
def get_service(
    service_id: int,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    try:
        # ✅ Verifica il token JWT
        Authorize.jwt_required()

        # 🔹 Recupera l'utente autenticato dal token JWT
        user_id = Authorize.get_jwt_subject()
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")

        # 🔹 Controlla se il servizio esiste e se è attivo
        service = db.query(Services).filter(Services.id == service_id, Services.is_active == True).first()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        # 🔹 Controlla se l'utente ha acquistato o è assegnato al servizio
        purchased = db.query(PurchasedServices).filter_by(user_id=user_id, service_id=service_id, status='attivo').first()
        assigned = db.query(AssignedServices).filter_by(dealer_id=user_id, service_id=service_id, status='attivo').first()

        if not purchased and not assigned:
            raise HTTPException(status_code=403, detail="Access denied")

        # 🔹 Restituisce i dettagli del servizio
        return {
            "id": service.id,
            "name": service.name,
            "description": service.description,
            "price": float(service.price),
            "image_url": service.image_url,
            "is_active": service.is_active
        }

    except Exception as e:
        print(f"❌ ERRORE: {str(e)}")
        raise HTTPException(status_code=500, detail="Errore interno del server")


