from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import SessionLocal
from app.models import Services, PurchasedServices

from app.routes.auth import get_db



marketplace_router = APIRouter(prefix="/marketplace", tags=["Marketplace"])

# 1️⃣ Super Admin: Aggiunta di un nuovo servizio
@marketplace_router.post("/services")
def add_service(name: str, description: str, price: float, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()
    user = db.query(Users).filter(Users.id == user_id).first()
    if user.role != 'superadmin':
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    new_service = Services(name=name, description=description, price=price)
    db.add(new_service)
    db.commit()
    return {"message": "Servizio aggiunto con successo"}

# 2️⃣ Super Admin: Lista servizi disponibili nel marketplace
@marketplace_router.get("/services")
def list_services(db: Session = Depends(get_db)):
    services = db.query(Services).all()
    return [{"id": s.id, "name": s.name, "price": s.price} for s in services]

# 3️⃣ Admin: Acquisto di un servizio
@marketplace_router.post("/services/{service_id}/purchase")
def purchase_service(service_id: int, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()
    user = db.query(Users).filter(Users.id == user_id).first()
    if user.role != 'admin':
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    service = db.query(Services).filter(Services.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Servizio non trovato")
    
    if user.credit < service.price:
        raise HTTPException(status_code=400, detail="Credito insufficiente")
    
    user.credit -= service.price
    new_purchase = PurchasedServices(admin_id=user.id, service_id=service.id)
    db.add(new_purchase)
    db.commit()
    return {"message": "Servizio acquistato con successo"}

# 4️⃣ Admin: Assegnazione di un servizio a un Dealer
@marketplace_router.post("/services/{service_id}/assign/{dealer_id}")
def assign_service(service_id: int, dealer_id: int, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()
    user = db.query(Users).filter(Users.id == user_id).first()
    if user.role != 'admin':
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    dealer = db.query(Users).filter(Users.id == dealer_id, Users.parent_id == user.id).first()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer non trovato o non autorizzato")
    
    assigned_service = AssignedServices(admin_id=user.id, dealer_id=dealer.id, service_id=service_id)
    db.add(assigned_service)
    db.commit()
    return {"message": "Servizio assegnato con successo"}

# 5️⃣ Controllo servizi attivi
@marketplace_router.get("/services/status")
def service_status(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_id = Authorize.get_jwt_subject()
    user = db.query(Users).filter(Users.id == user_id).first()
    
    if user.role == 'admin':
        services = db.query(PurchasedServices).filter(PurchasedServices.admin_id == user.id).all()
    elif user.role == 'dealer':
        services = db.query(AssignedServices).filter(AssignedServices.dealer_id == user.id).all()
    else:
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")
    
    return [{"service_id": s.service_id, "status": s.status} for s in services]
