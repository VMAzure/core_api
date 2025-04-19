from sqlalchemy.orm import Session
from fastapi import Depends, APIRouter, HTTPException
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import SmtpSettings, User
from pydantic import BaseModel
from app.auth_helpers import get_admin_id, is_admin_user
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr



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
    current_user_id = Authorize.get_jwt_subject()

    current_user = db.query(User).filter(User.email == current_user_id).first()

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
        new_settings = SmtpSettings(
            admin_id=current_user.id,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            use_ssl=settings.use_ssl,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password
        )
        db.add(new_settings)

    db.commit()

    return {"success": True, "message": "Impostazioni SMTP salvate con successo."}

class SMTPTestSchema(BaseModel):
    test_email: str

@router.post("/smtp-settings/test-email")
async def test_smtp_settings(
    test: SMTPTestSchema,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    current_user_id = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == current_user_id).first()

    if not current_user or current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Non autorizzato")

    smtp_settings = db.query(SmtpSettings).filter(SmtpSettings.admin_id == current_user.id).first()

    if not smtp_settings:
        raise HTTPException(status_code=400, detail="Configurazione SMTP mancante.")

    try:
        msg = MIMEText("Questa è una email di test.", "plain", "utf-8")
        msg["Subject"] = "Test Impostazioni SMTP"
        msg["From"] = formataddr((current_user.email, smtp_settings.smtp_user))
        msg["To"] = test.test_email

        if smtp_settings.use_ssl:
            server = smtplib.SMTP_SSL(smtp_settings.smtp_host, smtp_settings.smtp_port)
        else:
            server = smtplib.SMTP(smtp_settings.smtp_host, smtp_settings.smtp_port)
            server.starttls()

        server.login(smtp_settings.smtp_user, smtp_settings.smtp_password)
        server.send_message(msg)
        server.quit()

        return {"success": True, "message": f"Email inviata con successo a {test.test_email}"}

    except Exception as e:
        print("❌ Errore durante il test SMTP:", e)
        raise HTTPException(status_code=500, detail=str(e))
