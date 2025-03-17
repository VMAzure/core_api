from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import SiteAdminSettings, User
from app.schemas import SiteAdminSettingsSchema
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix="/api/site-settings", tags=["Site Settings"])

@router.get("/", response_model=SiteAdminSettingsSchema)
def get_site_settings(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Accesso non autorizzato")

    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.admin_id == user.id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Configurazione non trovata")

    return settings

@router.post("/")
def save_admin_settings(
    settings_data: SiteAdminSettingsSchema,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Accesso non autorizzato")

    existing_settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.admin_id == user.id).first()

    if existing_settings:
        for key, value in settings_data.dict(exclude_unset=True).items():
            setattr(existing_settings, key, value)
        existing_settings.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing_settings)

        return {"msg": "Impostazioni aggiornate", "settings": existing_settings}

    # Creare nuove impostazioni se non esistenti
    new_settings = SiteAdminSettings(**settings_data.dict(), admin_id=user.id)
    db.add(new_settings)
    db.commit()
    db.refresh(new_settings)

    return {"msg": "Impostazioni salvate", "settings": new_settings}
