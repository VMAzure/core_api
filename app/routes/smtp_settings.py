from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from dependencies import get_db, get_current_user
from models import SmtpSettings, User

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Non autorizzato")

    existing_settings = db.query(SmtpSettings).filter(SmtpSettings.admin_id == current_user.id).first()

    if existing_settings:
        # 🔄 Aggiorna impostazioni esistenti
        existing_settings.smtp_host = settings.smtp_host
        existing_settings.smtp_port = settings.smtp_port
        existing_settings.use_ssl = settings.use_ssl
        existing_settings.smtp_user = settings.smtp_user
        existing_settings.smtp_password = settings.smtp_password
    else:
        # ✨ Crea nuove impostazioni
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
