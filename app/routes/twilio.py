from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from datetime import datetime
from utils.twilio_client import send_whatsapp_message


router = APIRouter(prefix="/twilio", tags=["Twilio"])


@router.post("/inbound")
async def twilio_inbound(request: Request):
    """
    ✅ Webhook che riceve messaggi WhatsApp in ingresso dal cliente (sandbox o produzione).
    """
    form = await request.form()
    sender = form.get("From")           # es. whatsapp:+39349xxxxxxx
    message = form.get("Body")          # testo ricevuto
    msg_sid = form.get("MessageSid")
    timestamp = datetime.utcnow().isoformat()

    print(f"📥 [{timestamp}] Messaggio da {sender}: {message} (SID: {msg_sid})")

    # TODO:
    # - cerca il cliente via numero
    # - trova eventuale pipeline attiva
    # - aggiorna stato pipeline / crea log
    # - eventualmente rispondi via WhatsApp

    return JSONResponse(status_code=200, content={"message": "Ricevuto"})


@router.post("/callback")
async def twilio_callback(request: Request):
    """
    ✅ Callback opzionale per tracciare lo stato dei messaggi inviati (es. delivered, failed).
    """
    form = await request.form()
    sid = form.get("MessageSid")
    status_msg = form.get("MessageStatus")   # queued, sent, delivered, failed...

    timestamp = datetime.utcnow().isoformat()
    print(f"🔁 [{timestamp}] Callback Twilio: {sid} — Stato: {status_msg}")

    # TODO:
    # - salva stato in tabella messaggi (opzionale)
    # - gestisci errori (es. numero non valido)

    return JSONResponse(status_code=200, content={"status": "ok"})


router = APIRouter()

@router.get("/test-twilio")
def test_whatsapp():
    sid = send_whatsapp_message(
        to="whatsapp:+39XXXXXXXXXX",  # tuo numero attivato
        body="✅ Test WhatsApp AZCORE — tutto funziona!"
    )
    return {"status": "ok" if sid else "errore", "sid": sid}

