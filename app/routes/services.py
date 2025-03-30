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
from app.auth_helpers import get_admin_id, get_dealer_id, is_admin_user, is_dealer_user

@service_router.get("/{service_id}")
def get_service(
    service_id: int,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    try:
        Authorize.jwt_required()

        user_email = Authorize.get_jwt_subject()
        if not user_email:
            raise HTTPException(status_code=401, detail="Utente non autenticato")

        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            raise HTTPException(status_code=401, detail="Utente non trovato")

        # Controlla se il servizio esiste ed è attivo
        service = db.query(Services).filter(Services.id == service_id, Services.is_active == True).first()
        if not service:
            raise HTTPException(status_code=404, detail="Servizio non trovato")

        # Verifica accesso al servizio
        access_granted = False

        if is_admin_user(user):
            admin_id = get_admin_id(user)
            purchased = db.query(PurchasedServices).filter_by(
                admin_id=admin_id,
                service_id=service_id,
                status='active'
            ).first()
            access_granted = bool(purchased)

        elif is_dealer_user(user):
            dealer_id = get_dealer_id(user)
            assigned = db.query(AssignedServices).filter_by(
                dealer_id=dealer_id,
                service_id=service_id,
                status='active'
            ).first()
            access_granted = bool(assigned)

        if not access_granted:
            raise HTTPException(status_code=403, detail="Accesso negato a questo servizio")

        # Restituisce i dettagli
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
