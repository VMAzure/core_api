from fastapi import APIRouter, Request, status, Depends
from fastapi.responses import JSONResponse
from datetime import datetime
from app.utils.twilio_client import send_whatsapp_message
from app.models import NltMessaggiWhatsapp
from sqlalchemy.orm import Session
from app.routes.whatsapp import log_messaggio_inbound  # usa la logica esistente
from app.database import get_db


router = APIRouter(prefix="/twilio", tags=["Twilio"])


@router.post("/inbound")
async def twilio_inbound(request: Request, db=Depends(get_db)):
    return await log_messaggio_inbound(request=request, db=db)


@router.post("/callback")
async def twilio_callback(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sid = form.get("MessageSid")
    status_msg = form.get("MessageStatus")   # queued, sent, delivered, failed, ...

    timestamp = datetime.utcnow().isoformat()
    print(f"🔁 [{timestamp}] Callback Twilio: {sid} — Stato: {status_msg}")

    if not sid or not status_msg:
        return JSONResponse(status_code=400, content={"detail": "Dati mancanti nel callback"})

    msg = db.query(NltMessaggiWhatsapp).filter_by(twilio_sid=sid).first()
    if msg:
        msg.stato_messaggio = status_msg
        db.commit()
        print(f"✅ Stato aggiornato in DB: {status_msg}")
    else:
        print(f"⚠️ Nessun messaggio trovato con SID: {sid}")

    return JSONResponse(status_code=200, content={"status": "ok"})

@router.get("/test-twilio")
def test_whatsapp():
    sid = send_whatsapp_message(
        to="whatsapp:+393505048119",  # tuo numero attivato
        body="✅ Test WhatsApp AZCORE — tutto funziona!"
    )
    return {"status": "ok" if sid else "errore", "sid": sid}

