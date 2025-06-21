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

        if giorno < 6 and 9 <= ora < 24:
            preventivo = db.query(NltPreventivi).filter_by(id=p.preventivo_id).first()
            if not preventivo:
                logging.warning(f"⚠️ Preventivo non trovato per pipeline {p.id}")
                continue

            cliente = db.query(Cliente).filter_by(id=preventivo.cliente_id).first()
            assegnatario = db.query(User).filter_by(id=p.assegnato_a).first()
            if not cliente or not assegnatario:
                logging.warning(f"⚠️ Cliente o assegnatario mancanti per pipeline {p.id}")
                continue

            # 🔍 Admin e ID per fallback
            admin_id = assegnatario.parent_id or assegnatario.id
            admin = db.query(User).filter_by(id=admin_id).first()

            # 🔍 Recupera le impostazioni dealer (prima per dealer_id, poi per admin_id)
            dealer_settings = db.query(SiteAdminSettings).filter_by(dealer_id=assegnatario.id).first()
            if not dealer_settings:
                dealer_settings = (
                    db.query(SiteAdminSettings)
                    .filter_by(admin_id=admin.id)
                    .order_by(SiteAdminSettings.id.asc())
                    .first()
                )

            # 🎯 Slug vetrina
            slug = dealer_settings.slug if dealer_settings and dealer_settings.slug else "default"
            url_vetrina = f"https://www.azcore.it/vetrina-offerte/{slug}"
            url_non_interessato = f"https://coreapi-production-ca29.up.railway.app/api/pipeline/concludi/{p.id}"
            url_contatto_personale= f"https://www.azcore.it/AZUREpeople/conferma-appuntamento.html?id={p.id}"


            # 🧠 Dati dealer con fallback su admin
            def fallback(attr):
                dealer_val = getattr(assegnatario, attr, None)
                admin_val = getattr(admin, attr, None)
                return dealer_val if dealer_val not in [None, ""] else admin_val

            dealer_nome = f"{fallback('nome')} {fallback('cognome')}"
            indirizzo = fallback('indirizzo') or ""
            citta = fallback('citta') or ""
            telefono = fallback('cellulare') or ""
            email_contatto = fallback('email') or ""
            logo_url = fallback('logo_url') or ""

            # 🔍 Altri preventivi per decidere template
            # Calcolo dell'admin di riferimento dell’assegnatario corrente
            admin_id_corrente = assegnatario.parent_id or assegnatario.id

            # Trova altri preventivi con lo stesso cliente e stesso dealer
            altri = db.query(NltPipeline).join(NltPreventivi).join(User, NltPipeline.assegnato_a == User.id).filter(
                NltPipeline.id != p.id,
                NltPreventivi.cliente_id == preventivo.cliente_id,
                (User.parent_id == admin_id_corrente) | (User.id == admin_id_corrente)
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
                html = html.replace("{{dealer_nome}}", dealer_nome)
                html = html.replace("{{url_download}}", preventivo.file_url or "#")
                html = html.replace("{{email}}", email_contatto)
                html = html.replace("{{telefono}}", telefono)
                html = html.replace("{{indirizzo}}", indirizzo)
                html = html.replace("{{citta}}", citta)
                html = html.replace("{{logo_url}}", logo_url)
                html = html.replace("{{url_vetrina_dealer}}", url_vetrina)

                html = html.replace("{{url_contatto_personale}}", url_contatto_personale)
                html = html.replace("{{url_altre_proposte}}", url_vetrina)
                html = html.replace("{{url_non_interessato}}", url_non_interessato)


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

