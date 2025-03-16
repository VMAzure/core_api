from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Any  # 👈 aggiungi questo
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import SmtpSettings, User

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
    db: Session = Depends(SessionLocal)
):
    Authorize.jwt_required()
    current_user_id = Authorize.get_jwt_subject()
    
    current_user = db.query(User).filter(User.id == current_user_id).first()

    if not current_user or current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Non autorizzato")

    existing_settings = db.query(SmtpSettings).filter(SmtpSettings.admin_id == current_user.id).first()

    if existing_settings:
        existing_settings.smtp_host = settings.smtp_host
        existing_settings.smtp_port = settings.smtp_port
        existing_settings.use_ssl = settings.use_ssl
        existing_settings.smtp_user = settings.smtp_user
        existing_settings.smtp_password = settings.smtp_password
    else:
        existing_settings = SmtpSettings(
            admin_id=current_user.id,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            use_ssl=settings.use_ssl,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password
        )
        db.add(existing_settings)

    db.commit()

    return {"success": True, "message": "Impostazioni SMTP salvate con successo."}

