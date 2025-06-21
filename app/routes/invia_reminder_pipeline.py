import httpx
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import NltPipeline, NltPreventivi, Cliente, User, NltPipelineLog
from app.utils.email import send_email
import logging


logging.basicConfig(level=logging.INFO)
logging.info("🔁 Esecuzione invia_reminder_pipeline avviata")

def prossima_fascia_lavorativa(da: datetime) -> datetime:
    if da.weekday() >= 5:
        giorni_da_lunedi = 7 - da.weekday()
        return da.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=giorni_da_lunedi)
    elif da.hour >= 17:
        return da.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif da.hour < 9:
        return da.replace(hour=9, minute=0, second=0, microsecond=0)
    return da

def invia_reminder_pipeline():
    db: Session = SessionLocal()
    now = datetime.now()

    pipelines = db.query(NltPipeline).filter(
        NltPipeline.stato_pipeline == 'preventivo',
        NltPipeline.email_reminder_inviata == False,
        NltPipeline.scadenza_azione <= now
    ).all()

    print(f"🎯 Pipeline selezionate per invio reminder: {len(pipelines)}")


    for p in pipelines:
        logging.info(f"➡️  Pipeline ID: {p.id} | scadenza_azione: {p.scadenza_azione}")

        giorno = now.weekday()
        ora = now.hour

        if giorno < 5 and 9 <= ora < 17:
            preventivo = db.query(NltPreventivi).filter_by(id=p.preventivo_id).first()
            if not preventivo:
                logging.warning(f"⚠️ Preventivo non trovato per pipeline ID {p.id}")

                continue

            cliente = db.query(Cliente).filter_by(id=preventivo.cliente_id).first()
            assegnatario = db.query(User).filter_by(id=p.assegnato_a).first()

            if not cliente or not assegnatario:
                logging.warning(f"⚠️ Cliente o assegnatario non trovati per pipeline ID {p.id}")

                continue

            admin_id = assegnatario.parent_id or assegnatario.id

            try:
                logging.info(f"📨 Invio email a {cliente.email} per pipeline ID {p.id}")

                # ✅ Versione sincrona della richiesta al frontend
                template_res = httpx.get("https://corewebapp-azcore.up.railway.app/templates/email_reminder.html", timeout=10)
                template_res.raise_for_status()
                template_html = template_res.text

                # Sostituzioni base
                template_html = template_html.replace("{{cliente_nome}}", cliente.nome or "")
                template_html = template_html.replace("{{modello}}", preventivo.modello or "")
                template_html = template_html.replace("{{marca}}", preventivo.marca or "")
                template_html = template_html.replace("{{dealer_nome}}", f"{assegnatario.nome} {assegnatario.cognome}")
                template_html = template_html.replace("{{url_download}}", preventivo.file_url or "#")
                template_html = template_html.replace("{{email}}", assegnatario.email or "")
                template_html = template_html.replace("{{telefono}}", assegnatario.cellulare or "")
                template_html = template_html.replace("{{indirizzo}}", assegnatario.indirizzo or "")
                template_html = template_html.replace("{{citta}}", assegnatario.citta or "")
                template_html = template_html.replace("{{logo_url}}", assegnatario.logo_url or "")

                send_email(
                    admin_id=admin_id,
                    to_email=cliente.email,
                    subject="Hai valutato il tuo preventivo?",
                    body=template_html,
                    # reply_to_email=assegnatario.email  # solo se implementato
                )

                p.email_reminder_inviata = True

                db.add(NltPipelineLog(
                    pipeline_id=p.id,
                    tipo_azione="[AUTO] Reminder inviato",
                    note=f"Email automatica inviata a {cliente.email}",
                    data_evento=now,
                    utente_id=assegnatario.id
                ))

                logging.info(f"🔔 Reminder inviato a {cliente.email} per preventivo {preventivo.id}")

            except Exception as e:
                import traceback
                logging.error(f"❌ Errore invio reminder: {str(e)}")
                logging.error(traceback.format_exc())

        else:
            fascia = prossima_fascia_lavorativa(now)
            logging.info(f"⏳ Fuori orario. Reminder rimandato per pipeline {p.id} a: {fascia}")
            p.email_reminder_scheduled = fascia


    db.commit()
    db.close()
