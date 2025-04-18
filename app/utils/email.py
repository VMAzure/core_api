import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from sqlalchemy.orm import Session
from app.models import SmtpSettings
from app.database import SessionLocal

def get_smtp_settings(admin_id: int, db: Session):
    return db.query(SmtpSettings).filter(SmtpSettings.admin_id == admin_id).first()

def send_reset_email(admin_id: int, to_email: str, token: str):
    db = SessionLocal()
    smtp_settings = get_smtp_settings(admin_id, db)

    if not smtp_settings:
        db.close()
        raise Exception("Impostazioni SMTP non configurate per questo admin.")

    reset_url = f"https://corewebapp-azcore.up.railway.app/Account/ResetPassword?token={token}"
    body = f"Clicca sul seguente link per reimpostare la tua password:\n\n{reset_url}"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Reset Password"

    sender_alias = smtp_settings.smtp_alias or smtp_settings.smtp_user
    msg["From"] = formataddr((sender_alias, smtp_settings.smtp_user))
    msg["To"] = to_email

    try:
        if smtp_settings.use_ssl:
            print(f"✅ Connessione SSL SMTP: host={smtp_settings.smtp_host}, port={smtp_settings.smtp_port}")
            server = smtplib.SMTP_SSL(smtp_settings.smtp_host, smtp_settings.smtp_port)
        else:
            print(f"✅ Connessione SMTP senza SSL: host={smtp_settings.smtp_host}, port={smtp_settings.smtp_port}")
            server = smtplib.SMTP(smtp_settings.smtp_host, smtp_settings.smtp_port)
            server.starttls()

        print(f"✅ Login SMTP con utente: {smtp_settings.smtp_user}")
        server.login(smtp_settings.smtp_user, smtp_settings.smtp_password)

        print(f"✅ Invio email a {to_email}")
        server.send_message(msg)

        server.quit()
        print("✅ Email inviata correttamente a", to_email)
    except Exception as e:
        print("❌ Errore dettagliato nell'invio email:", e)
        raise e  # Ri-solleviamo errore per mostrare nel log chiaramente
    finally:
        db.close()
