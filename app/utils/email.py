import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from sqlalchemy.orm import Session
from app.models import SmtpSettings, User
from app.database import SessionLocal

def get_smtp_settings(admin_id: int, db: Session):
    return db.query(SmtpSettings).filter(SmtpSettings.admin_id == admin_id).first()


def send_reset_email(admin_id: int, to_email: str, token: str):
    db = SessionLocal()

    smtp_settings = get_smtp_settings(admin_id, db)
    current_user = db.query(User).filter(User.id == admin_id).first()

    if not smtp_settings:
        db.close()
        raise Exception("Impostazioni SMTP non configurate per questo admin.")

    reset_url = f"https://corewebapp-azcore.up.railway.app/Account/ResetPassword?token={token}"
    body = f"Clicca sul seguente link per reimpostare la tua password:\n\n{reset_url}"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Reset Password"

    # LOGICA CORRETTA QUI:
    if smtp_settings.smtp_alias and current_user.role == "superadmin":
        sender_alias = smtp_settings.smtp_alias
    else:
        sender_alias = current_user.email  # per admin regolari, alias = email di login

    msg["From"] = formataddr((sender_alias, smtp_settings.smtp_user))
    msg["To"] = to_email

    try:
        if smtp_settings.use_ssl:
            server = smtplib.SMTP_SSL(smtp_settings.smtp_host, smtp_settings.smtp_port)
        else:
            server = smtplib.SMTP(smtp_settings.smtp_host, smtp_settings.smtp_port)
            server.starttls()

        server.login(smtp_settings.smtp_user, smtp_settings.smtp_password)
        server.send_message(msg)
        server.quit()
        print("✅ Email inviata correttamente a", to_email)
    except Exception as e:
        print("❌ Errore invio email:", e)
        raise e
    finally:
        db.close()


def send_email(admin_id: int, to_email: str, subject: str, body: str):
    db = SessionLocal()

    smtp_settings = get_smtp_settings(admin_id, db)
    current_user = db.query(User).filter(User.id == admin_id).first()

    if not smtp_settings:
        db.close()
        raise Exception("Impostazioni SMTP non configurate per questo admin.")

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject

    if smtp_settings.smtp_alias and current_user.role == "superadmin":
        sender_alias = smtp_settings.smtp_alias
    else:
        sender_alias = current_user.email  # admin regolari, alias = email di login

    msg["From"] = formataddr((sender_alias, smtp_settings.smtp_user))
    msg["To"] = to_email

    try:
        if smtp_settings.use_ssl:
            server = smtplib.SMTP_SSL(smtp_settings.smtp_host, smtp_settings.smtp_port)
        else:
            server = smtplib.SMTP(smtp_settings.smtp_host, smtp_settings.smtp_port)
            server.starttls()

        server.login(smtp_settings.smtp_user, smtp_settings.smtp_password)
        server.send_message(msg)
        server.quit()
        print("✅ Email inviata correttamente a", to_email)
    except Exception as e:
        print("❌ Errore invio email:", e)
        raise e
    finally:
        db.close()
