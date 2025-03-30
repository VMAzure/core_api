from sqlalchemy.orm import Session
from fastapi import Depends, APIRouter, HTTPException
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import SmtpSettings, User
from pydantic import BaseModel
from app.auth_helpers import get_admin_id, is_admin_user  # ✅ Import helper

router = APIRouter()

class SMTPSettingsSchema(BaseModel):
    smtp_host: str
    smtp_port: int
    use_ssl: bool
    smtp_user: str
    smtp_password: str

@router.post("/smtp-settings")
async def set_smtp_settings(
    settings: SMTPSettingsSchema,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    admin_id = get_admin_id(user)  # ✅ sempre riferito all'admin principale

    existing_settings = db.query(SmtpSettings).filter(SmtpSettings.admin_id == admin_id).first()

    if existing_settings:
        existing_settings.smtp_host = settings.smtp_host
        existing_settings.smtp_port = settings.smtp_port
        existing_settings.use_ssl = settings.use_ssl
        existing_settings.smtp_user = settings.smtp_user
        existing_settings.smtp_password = settings.smtp_password
    else:
        new_settings = SmtpSettings(
            admin_id=admin_id,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            use_ssl=settings.use_ssl,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password
        )
        db.add(new_settings)

    db.commit()

    return {"success": True, "message": "Impostazioni SMTP salvate con successo."}

@router.get("/smtp-settings", response_model=SMTPSettingsSchema)
async def get_smtp_settings(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    admin_id = get_admin_id(user)

    settings = db.query(SmtpSettings).filter(SmtpSettings.admin_id == admin_id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Impostazioni SMTP non trovate")

    return settings
