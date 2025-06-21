import httpx
import logging
import traceback
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import NltPipeline, NltPreventivi, Cliente, User, NltPipelineLog,SiteAdminSettings
from app.utils.email import send_email

# Logging globale
logging.basicConfig(level=logging.INFO)
logging.info("🔁 Esecuzione invia_reminder_pipeline avviata")

def prossima_fascia_lavorativa(da: datetime) -> datetime:
    if da.weekday() >= 5:  # Sabato o Domenica
        giorni_da_lunedi = 7 - da.weekday()
        return da.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=giorni_da_lunedi)
    elif da.hour >= 21:
        return da.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif da.hour < 9:
        return da.replace(hour=9, minute=0, second=0, microsecond=0)
    return da


def invia_reminder_pipeline():
    db: Session = SessionLocal()
    now = datetime.utcnow() + timedelta(hours=2)

    pipelines = db.query(NltPipeline).filter(
        NltPipeline.stato_pipeline == 'preventivo',
        NltPipeline.email_reminder_inviata == False,
        NltPipeline.scadenza_azione <= now
    ).all()

    logging.info(f"🎯 Pipeline selezionate per invio welcome: {len(pipelines)}")

    for p in pipelines:
        logging.info(f"➡️ Pipeline ID: {p.id} | scadenza_azione: {p.scadenza_azione}")
        giorno = now.weekday()
        ora = now.hour

        if giorno < 6 and 9 <= ora < 21:
            preventivo = db.query(NltPreventivi).filter_by(id=p.preventivo_id).first()
            if not preventivo:
                logging.warning(f"⚠️ Preventivo non trovato per pipeline {p.id}")
                continue

            cliente = db.query(Cliente).filter_by(id=preventivo.cliente_id).first()
            assegnatario = db.query(User).filter_by(id=p.assegnato_a).first()
            if not cliente or not assegnatario:
                logging.warning(f"⚠️ Cliente o assegnatario mancanti per pipeline {p.id}")
                continue

            admin_id = assegnatario.parent_id or assegnatario.id

            # Recupera lo slug del dealer da SiteAdminSettings
            admin_settings = db.query(SiteAdminSettings).filter_by(admin_id=admin_id).first()
            slug = admin_settings.slug if admin_settings and admin_settings.slug else "default"
            url_vetrina = f"https://www.azcore.it/vetrina-offerte/{slug}"


            # 🔍 Quanti preventivi ha lo stesso cliente?
            altri = db.query(NltPipeline).join(NltPreventivi).filter(
                NltPipeline.id != p.id,
                NltPreventivi.cliente_id == preventivo.cliente_id
            ).all()

            usa_template_multiplo = len(altri) > 0
            template_url = (
                "https://corewebapp-azcore.up.railway.app/templates/email_welcome_multipli.html"
                if usa_template_multiplo else
                "https://corewebapp-azcore.up.railway.app/templates/email_welcome_singolo.html"
            )

            try:
                logging.info(f"📨 Invio email a {cliente.email} (template: {'multiplo' if usa_template_multiplo else 'singolo'})")

                template_res = httpx.get(template_url, timeout=10)
                template_res.raise_for_status()
                html = template_res.text

                html = html.replace("{{cliente_nome}}", cliente.nome or "")
                html = html.replace("{{modello}}", preventivo.modello or "")
                html = html.replace("{{marca}}", preventivo.marca or "")
                html = html.replace("{{dealer_nome}}", f"{assegnatario.nome} {assegnatario.cognome}")
                html = html.replace("{{url_download}}", preventivo.file_url or "#")
                html = html.replace("{{email}}", assegnatario.email or "")
                html = html.replace("{{telefono}}", assegnatario.cellulare or "")
                html = html.replace("{{indirizzo}}", assegnatario.indirizzo or "")
                html = html.replace("{{citta}}", assegnatario.citta or "")
                html = html.replace("{{logo_url}}", assegnatario.logo_url or "")
                html = html.replace("{{url_vetrina_dealer}}", url_vetrina)

                html = html.replace("{{url_contatto_personale}}", url_vetrina)
                html = html.replace("{{url_altre_proposte}}", url_vetrina)
                html = html.replace("{{url_non_interessato}}", url_vetrina)

                logging.info("📄 Contenuto finale email:")
                logging.info(html)
                
                send_email(
                    admin_id=admin_id,
                    to_email=cliente.email,
                    subject="Noleggio Lungo Termine",
                    body=html
                )

                p.email_reminder_inviata = True
                db.add(NltPipelineLog(
                    pipeline_id=p.id,
                    tipo_azione="[AUTO] Welcome email inviata",
                    note=f"Inviata a {cliente.email} con template {'multiplo' if usa_template_multiplo else 'singolo'}",
                    data_evento=now,
                    utente_id=assegnatario.id
                ))

                logging.info(f"✅ Email inviata a {cliente.email} per preventivo {preventivo.id}")

            except Exception as e:
                logging.error(f"❌ Errore invio email: {e}")
                logging.error(traceback.format_exc())

        else:
            fascia = prossima_fascia_lavorativa(now)
            logging.info(f"⏳ Fuori orario. Reminder rimandato per pipeline {p.id} a: {fascia}")
            p.email_reminder_scheduled = fascia

    db.commit()
    db.close()

