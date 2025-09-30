from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import User, PurchasedServices, Services
from sqlalchemy import text
import logging
from app.utils.modelli import pulizia_massiva_modelli


# === Catena NUOVO ===
from app.routes.sync_marche_completo import sync_marche as sync_marche_nuovo
from app.routes.sync_modelli_nuovo import sync_modelli as sync_modelli_nuovo
from app.routes.sync_allestimenti_nuovo import sync_allestimenti as sync_allestimenti_nuovo
from app.routes.sync_dettagli_nuovo import sync_dettagli_auto as sync_dettagli_nuovo

# === Catena USATO ===
from app.routes.sync_marche_usato import sync_marche_usato as sync_marche_usato
from app.routes.sync_modelli_usato import sync_modelli_usato as sync_modelli_usato
from app.routes.sync_allestimenti_usato import sync_allestimenti_usato as sync_allestimenti_usato
from app.routes.sync_dettagli_usato import sync_dettagli_usato as sync_dettagli_usato
from app.routes.sync_anni_usato import sync_all_marche


from app.routes.invia_reminder_pipeline import invia_reminder_pipeline
from app.utils.aggiorna_usato_settimanale import aggiorna_usato_settimanale
from app.routes.sync_foto_mnet import sync_foto_mnet
from app.routes.sync_foto_mnet_missing import sync_foto_mnet_missing


from app.utils.notifications import inserisci_notifica
from app.utils.email import get_smtp_settings
from sqlalchemy.orm import joinedload
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
import asyncio

from app.utils.video_jobs import (
    video_daily_batch,
    video_revalidate_existing,
    video_weekly_sweep,
)

from apscheduler.triggers.interval import IntervalTrigger
from app.routes.openai_config import _gemini_get_operation, _download_bytes, _sb_upload_and_sign
from app.models import UsatoLeonardo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.task_gigi import processa_gigi_gorilla_jobs


from pytz import timezone
TZ = timezone("Europe/Rome")


# Configurazione dei log
logging.basicConfig(filename="cron_job.log", level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

def calcola_prossima_scadenza(current: datetime, cycle: str) -> datetime:
    return {
        "monthly": current + timedelta(days=30),
        "quarterly": current + timedelta(days=90),
        "semiannual": current + timedelta(days=182),
        "annual": current + timedelta(days=365)
    }.get(cycle, current + timedelta(days=30))

def check_and_charge_services():
    logging.info("🚀 CRONJOB: check_and_charge_services avviato")
    db = SessionLocal()
    now = datetime.utcnow()

    soglie_avviso = {
        "monthly": [10, 2],
        "quarterly": [10, 2],
        "semiannual": [30, 5],
        "annual": [30, 5]
    }

    try:
        servizi_attivi = db.query(PurchasedServices).join(Services).options(
            joinedload(PurchasedServices.service),
            joinedload(PurchasedServices.dealer)
        ).filter(
            PurchasedServices.status == "attivo",
            PurchasedServices.billing_cycle.isnot(None),
            PurchasedServices.next_renewal_at.isnot(None),
            PurchasedServices.dealer_id.isnot(None),
            Services.is_pay_per_use == False   # ⬅️ ESCLUDE i pay-per-use
        ).all()

        for ps in servizi_attivi:
            service = ps.service
            dealer = ps.dealer
            billing_cycle = ps.billing_cycle
            giorni_mancanti = (ps.next_renewal_at.date() - now.date()).days

            # 🔔 Avvisi pre-scadenza
            if giorni_mancanti in soglie_avviso.get(billing_cycle, []):
                admin_id = dealer.parent_id
                smtp = get_smtp_settings(admin_id, db)

                if smtp:
                    html = f"<p>Il tuo servizio <strong>{service.name}</strong> scadrà tra {giorni_mancanti} giorni.</p><p>Controlla il credito disponibile per evitare la sospensione automatica.</p>"
                    msg = MIMEText(html, "html", "utf-8")
                    msg["Subject"] = f"🔔 Servizio '{service.name}' in scadenza"
                    msg["From"] = formataddr((smtp.smtp_alias or "AZ Core", smtp.smtp_user))
                    msg["To"] = dealer.email

                    try:
                        server = smtplib.SMTP_SSL(smtp.smtp_host, smtp.smtp_port) if smtp.use_ssl else smtplib.SMTP(smtp.smtp_host, smtp.smtp_port)
                        if not smtp.use_ssl:
                            server.starttls()
                        server.login(smtp.smtp_user, smtp.smtp_password)
                        server.send_message(msg)
                        server.quit()
                        logging.info(f"📧 Avviso inviato a {dealer.email} per {service.name}")
                    except Exception as e:
                        logging.error(f"❌ Errore invio email avviso a {dealer.email}: {e}")

                # 🔔 Scrivi notifica
                inserisci_notifica(
                    db, utente_id=dealer.id,
                    tipo_codice="scadenza_servizio",
                    messaggio=f"Il servizio '{service.name}' scadrà tra {giorni_mancanti} giorni."
                )

            # 🔁 Rinnovo
            if now >= ps.next_renewal_at:
                price = {
                    "monthly": service.monthly_price,
                    "quarterly": service.quarterly_price,
                    "semiannual": service.semiannual_price,
                    "annual": service.annual_price
                }.get(billing_cycle, 0)

                if dealer.credit >= price:
                    dealer.credit -= price
                    ps.activated_at = now
                    ps.next_renewal_at = calcola_prossima_scadenza(now, billing_cycle)
                    db.commit()
                    logging.info(f"✅ Servizio rinnovato: {service.name} per {dealer.email}")
                else:
                    ps.status = "sospeso"
                    db.commit()

                    # ❌ Email sospensione
                    admin_id = dealer.parent_id
                    smtp = get_smtp_settings(admin_id, db)

                    if smtp:
                        html = f"<p>Il servizio <strong>{service.name}</strong> è stato sospeso per credito insufficiente.</p><p>Puoi riattivarlo dallo Store dopo aver ricaricato il credito.</p>"
                        msg = MIMEText(html, "html", "utf-8")
                        msg["Subject"] = f"❌ Servizio '{service.name}' sospeso"
                        msg["From"] = formataddr((smtp.smtp_alias or "AZ Core", smtp.smtp_user))
                        msg["To"] = dealer.email

                        try:
                            server = smtplib.SMTP_SSL(smtp.smtp_host, smtp.smtp_port) if smtp.use_ssl else smtplib.SMTP(smtp.smtp_host, smtp.smtp_port)
                            if not smtp.use_ssl:
                                server.starttls()
                            server.login(smtp.smtp_user, smtp.smtp_password)
                            server.send_message(msg)
                            server.quit()
                            logging.info(f"📧 Email sospensione a {dealer.email} per {service.name}")
                        except Exception as e:
                            logging.error(f"❌ Errore invio email sospensione a {dealer.email}: {e}")

                    # 🛑 Scrivi notifica sospensione
                    inserisci_notifica(
                        db, utente_id=dealer.id,
                        tipo_codice="sospensione_servizio",
                        messaggio=f"Il servizio '{service.name}' è stato sospeso per credito insufficiente."
                    )

    except Exception as e:
        db.rollback()
        logging.error(f"❌ Errore cronjob servizi: {e}")
    finally:
        db.close()


def pulisci_modelli_settimanale():
    logging.info("🧹 Avvio pulizia settimanale modelli...")
    db = SessionLocal()
    try:
        pulizia_massiva_modelli(db)
        logging.info("✅ Pulizia modelli completata.")
    except Exception as e:
        logging.error(f"❌ Errore nella pulizia modelli: {e}")
    finally:
        db.close()



from app.utils.quotazioni import aggiorna_rating_convenienza

def aggiorna_rating_convenienza_job():
    logging.info("📊 Avvio aggiornamento rating convenienza...")
    db = SessionLocal()
    try:
        aggiorna_rating_convenienza(db)
        logging.info("✅ Rating convenienza aggiornato con successo.")
    except Exception as e:
        logging.error(f"❌ Errore durante aggiornamento rating convenienza: {e}")
    finally:
        db.close()


from app.routes.openai_config import _gemini_get_operation, _download_bytes, _sb_upload_and_sign
from app.models import UsatoLeonardo
import logging
import json

async def polla_video_gemini():
    logging.warning("🚀 INIZIO polling Gemini video VEO3")
    db = SessionLocal()

    try:
        recs = db.query(UsatoLeonardo).filter(
            UsatoLeonardo.media_type == "video",
            UsatoLeonardo.status == "processing",
            UsatoLeonardo.generation_id.isnot(None)
        ).all()

        logging.warning(f"📊 Trovati {len(recs)} video in stato 'processing' da pollare")

        for rec in recs:
            logging.warning(f"🟡 Inizio polling per video ID: {rec.id} (generation_id: {rec.generation_id})")

            try:
                op = await _gemini_get_operation(rec.generation_id)

                logging.warning("📦 Risposta Gemini grezza:\n%s", json.dumps(op, indent=2))

                if not op.get("done", False):
                    logging.warning(f"⏳ Operazione ancora in corso per {rec.id}")
                    continue

                # Estrai URI video
                resp = op.get("response", {})
                uri = None

                # ✅ Caso VEO3 attuale (da generateVideoResponse.generatedSamples[].video.uri)
                samples = resp.get("generateVideoResponse", {}).get("generatedSamples") or []
                if samples:
                    video = samples[0].get("video", {})
                    uri = video.get("uri")

                # 🔁 Fallback classici (non sempre presenti)
                if not uri:
                    vids = resp.get("generatedVideos") or []
                    if vids:
                        v0 = vids[0]
                        video_obj = v0.get("video") or {}
                        uri = v0.get("uri") or video_obj.get("uri") or video_obj.get("videoUri")


                if not uri:
                    rec.status = "failed"
                    rec.error_message = "URI video mancante dal response Gemini"
                    db.commit()
                    logging.error(f"❌ URI mancante per video {rec.id}")
                    continue

                # Download video
                blob = await _download_bytes(uri)
                ext = ".mp4"
                path = f"{str(rec.id_auto)}/{str(rec.id)}{ext}"
                _, public_url = _sb_upload_and_sign(path, blob, "video/mp4")

                # Attiva solo se nessun altro attivo
                other_active = db.query(UsatoLeonardo).filter(
                    UsatoLeonardo.id_auto == rec.id_auto,
                    UsatoLeonardo.media_type == "video",
                    UsatoLeonardo.is_active == True,
                    UsatoLeonardo.id != rec.id
                ).count()

                rec.status = "completed"
                rec.public_url = public_url
                rec.storage_path = path
                rec.is_active = (other_active == 0)

                # 👉 se è Boost e non ancora messo in vetrina
                if rec.is_boost and not rec.boost_vetrina_done:
                    _put_in_vetrina(db, rec.id_auto, rec.id, priority=2)
                    rec.boost_vetrina_done = True

                db.commit()
                logging.info(f"✅ Video Gemini COMPLETATO per {rec.id} (boost_vetrina_done={rec.boost_vetrina_done}, attivo={rec.is_active})")

            except Exception as e:
                db.rollback()
                rec.status = "failed"
                rec.error_message = str(e)
                db.commit()
                logging.error(f"❌ Errore durante polling video {rec.id}: {e}")

    except Exception as e:
        db.rollback()
        logging.critical(f"🔥 ERRORE FATALE nel cronjob polling Gemini: {e}")

    finally:
        db.close()
        logging.warning("✅ Fine polling Gemini video VEO3\n")

import logging
from io import BytesIO
from PIL import Image
import requests
from collections import defaultdict

from app.database import SessionLocal
from app.models import UsatoLeonardo
from app.routes.openai_config import _gemini_generate_image_sync, _sb_upload_and_sign


def _put_in_vetrina(db, id_auto: str, media_id: str, priority: int):
    db.execute(text("""
        INSERT INTO usato_vetrina (id_auto, media_type, media_id, priority, created_at)
        VALUES (:id_auto, 'ai', :media_id, :priority, now())
        ON CONFLICT DO NOTHING
    """), {"id_auto": str(id_auto), "media_id": str(media_id), "priority": priority})
    db.commit()


MAX_RETRY = 3

def _apply_logo(final: Image.Image, logo_url: str, logo_height: int, offset_y: int) -> Image.Image:
    """Scarica e applica il logo sull'immagine finale."""
    r = requests.get(logo_url, timeout=30)
    r.raise_for_status()
    logo = Image.open(BytesIO(r.content)).convert("RGBA")
    ow, oh = logo.size
    new_h = max(1, int(logo_height or 100))
    new_w = int((ow / oh) * new_h)
    logo = logo.resize((new_w, new_h))
    if final.height < new_h + offset_y:
        raise ValueError(f"image too small for logo offset {offset_y}px")
    logo_x = (final.width - new_w) // 2
    logo_y = offset_y
    final.paste(logo, (logo_x, logo_y), logo)
    return final

async def processa_immagini_gemini():
    logging.info("🚀 INIZIO cronjob processa_immagini_gemini")
    db = SessionLocal()
    try:
        recs = db.query(UsatoLeonardo).filter(
            UsatoLeonardo.media_type == "image",
            UsatoLeonardo.status == "queued"
        ).all()

        logging.info(f"📊 Trovati {len(recs)} record immagine in coda")

        # --- Raggruppa per (id_auto, prompt, subject_url, background_url, logo_url) ---
        grouped = defaultdict(list)
        for rec in recs:
            key = (rec.id_auto, rec.prompt, rec.subject_url, rec.background_url, rec.logo_url)
            grouped[key].append(rec)

        for key, batch in grouped.items():
            try:
                logging.info(f"🟡 Generazione batch da {len(batch)} immagini per auto={batch[0].id_auto}")

                # 1) chiamata Gemini per N immagini
                responses = await _gemini_generate_image_sync(
                    batch[0].prompt,
                    subject_image_url=batch[0].subject_url,
                    background_image_url=batch[0].background_url,
                    num_images=len(batch)   # <-- importante
                )

                # responses = lista di byte immagini
                if not isinstance(responses, list):
                    responses = [responses]

                # 2) assegna immagini ai record disponibili
                for rec, img_bytes in zip(batch, responses):
                    try:
                        # 👇 fix: normalizza se Gemini restituisce lista annidata
                        if isinstance(img_bytes, list):
                            img_bytes = img_bytes[0]
                        final = Image.open(BytesIO(img_bytes)).convert("RGBA")

                        # logo opzionale
                        if rec.logo_url:
                            final = _apply_logo(final, rec.logo_url, rec.logo_height or 100, rec.logo_offset_y or 100)

                        # salva PNG
                        buf = BytesIO()
                        final.save(buf, format="PNG")
                        buf.seek(0)

                        path = f"{str(rec.id_auto)}/{str(rec.id)}.png"
                        _, public_url = _sb_upload_and_sign(path, buf.getvalue(), "image/png")

                        rec.public_url = public_url
                        rec.storage_path = path
                        rec.status = "completed"
                        rec.retry_count = 0

                        # 👉 se è Boost e non ancora messa in vetrina
                        if rec.is_boost and not rec.boost_vetrina_done:
                            _put_in_vetrina(db, rec.id_auto, rec.id, priority=1)
                            rec.boost_vetrina_done = True

                        db.commit()
                        logging.info(f"✅ Immagine completata per rec_id={rec.id} (boost_vetrina_done={rec.boost_vetrina_done})")


                    except Exception as e:
                        db.rollback()
                        rec.retry_count = (rec.retry_count or 0) + 1
                        if rec.retry_count >= MAX_RETRY:
                            rec.status = "failed"
                        rec.error_message = str(e)
                        db.commit()
                        logging.error(f"❌ Errore singolo rec_id={rec.id}: {e}")

                # 3) se Gemini ha restituito meno immagini del richiesto
                if len(responses) < len(batch):
                    missing = batch[len(responses):]
                    for rec in missing:
                        rec.retry_count = (rec.retry_count or 0) + 1
                        if rec.retry_count >= MAX_RETRY:
                            rec.status = "failed"
                        else:
                            rec.status = "queued"  # tornerà al prossimo giro
                        rec.error_message = (
                            f"Gemini non ha generato abbastanza immagini "
                            f"(richieste {len(batch)}, ricevute {len(responses)})"
                        )
                    db.commit()
                    logging.warning(
                        f"⚠️ Ricevute solo {len(responses)} immagini su {len(batch)} "
                        f"per auto={batch[0].id_auto}"
                    )

            except Exception as e:
                db.rollback()
                for rec in batch:
                    rec.retry_count = (rec.retry_count or 0) + 1
                    if rec.retry_count >= MAX_RETRY:
                        rec.status = "failed"
                    rec.error_message = str(e)
                db.commit()
                logging.error(f"❌ Errore batch {len(batch)} recs per auto={batch[0].id_auto}: {e}")

    except Exception as e:
        db.rollback()
        logging.critical(f"🔥 Errore fatale cron immagini: {e}")
    finally:
        db.close()
        logging.info("✅ Fine cronjob immagini Gemini\n")



from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Usa un solo scheduler asincrono
scheduler = AsyncIOScheduler(job_defaults={'coalesce': True, 'max_instances': 1}, timezone=TZ)

# === Catena NUOVO (lunedì) ===
scheduler.add_job(sync_marche_nuovo,       'cron', id='nuovo_marche',       name='NUOVO: marche',       day_of_week='mon', hour=1,  minute=0, timezone=TZ)
scheduler.add_job(sync_modelli_nuovo,      'cron', id='nuovo_modelli',      name='NUOVO: modelli',      day_of_week='mon', hour=2,  minute=0, timezone=TZ)
scheduler.add_job(sync_allestimenti_nuovo, 'cron', id='nuovo_allestimenti', name='NUOVO: allestimenti', day_of_week='mon', hour=3,  minute=0, timezone=TZ)
scheduler.add_job(sync_dettagli_nuovo,     'cron', id='nuovo_dettagli',     name='NUOVO: dettagli',     day_of_week='mon', hour=4,  minute=0, timezone=TZ)

# === Catena USATO (martedì) ===
scheduler.add_job(sync_marche_usato,       'cron', id='usato_marche',       name='USATO: marche',       day_of_week='tue', hour=1,  minute=0, timezone=TZ)
scheduler.add_job(sync_modelli_usato,      'cron', id='usato_modelli',      name='USATO: modelli',      day_of_week='tue', hour=2,  minute=0, timezone=TZ)
scheduler.add_job(sync_all_marche,         'cron', id='usato_anni',         name='USATO: anni',         day_of_week='tue', hour=2, minute=30, timezone=TZ)
scheduler.add_job(sync_allestimenti_usato, 'cron', id='usato_allestimenti', name='USATO: allestimenti', day_of_week='tue', hour=3,  minute=0, timezone=TZ)
scheduler.add_job(sync_dettagli_usato,     'cron', id='usato_dettagli',     name='USATO: dettagli',     day_of_week='tue', hour=4,  minute=0, timezone=TZ)

# === Altri job già presenti ===
scheduler.add_job(check_and_charge_services, 'cron', hour=5, minute=0)
scheduler.add_job(pulisci_modelli_settimanale, 'cron', day_of_week='fri', hour=3, minute=0)
scheduler.add_job(aggiorna_rating_convenienza_job, 'cron', hour=3, minute=30)
scheduler.add_job(aggiorna_usato_settimanale, 'cron', day_of_week='tue', hour=1, minute=0)
scheduler.add_job(invia_reminder_pipeline, 'interval', minutes=30)

# Video jobs
scheduler.add_job(video_revalidate_existing, 'cron', hour=2, minute=45)
scheduler.add_job(video_daily_batch,       'cron', hour=5, minute=20)
scheduler.add_job(video_weekly_sweep,      'cron', day_of_week='sun', hour=5, minute=40)

# ⬇️ schedulazione: venerdì 16:00 full scan, 18:00 retry mancanti
scheduler.add_job(sync_foto_mnet,         'cron', day_of_week='sat', hour=1, minute=0,  misfire_grace_time=3600, coalesce=True)
scheduler.add_job(sync_foto_mnet_missing, 'cron', day_of_week='sat', hour=4, minute=0,  misfire_grace_time=3600, coalesce=True)

# Polling Gemini video ogni 60 secondi
scheduler.add_job(polla_video_gemini, IntervalTrigger(seconds=60))

# Polling Gemini immagini ogni 30 secondi
scheduler.add_job(processa_immagini_gemini, IntervalTrigger(seconds=15))

# Polling Gigi Gorilla immagini ogni 30 secondi
scheduler.add_job(processa_gigi_gorilla_jobs, 'interval', seconds=15)




for job in scheduler.get_jobs():
    print("JOB:", job.id, "→", job.func)


