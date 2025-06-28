import os
import json

from twilio.rest import Client

# ✅ Variabili lette da Railway (già configurate)
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # default sandbox
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")


# ⚙️ Inizializzazione client Twilio
client = Client(TWILIO_SID, TWILIO_TOKEN)


def send_whatsapp_message(to: str, body: str) -> str | None:
    """
    Invia un messaggio WhatsApp testuale (compatibile con sandbox Twilio).
    
    :param to: Numero destinatario nel formato 'whatsapp:+39...'
    :param body: Testo del messaggio
    :return: SID del messaggio inviato, oppure None in caso di errore
    """
    try:
        message = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to,
            body=body
        )
        print(f"✅ WhatsApp inviato a {to} — SID: {message.sid}")
        return message.sid
    except Exception as e:
        print(f"❌ Errore invio WhatsApp a {to}: {e}")
        return None

def send_whatsapp_template(to: str, content_sid: str, content_variables: dict) -> str | None:
    try:
        print("📤 Invio template con:", {
            "to": to,
            "messaging_service_sid": TWILIO_MESSAGING_SERVICE_SID,
            "content_sid": content_sid,
            "variables": content_variables
        })

        message = client.messages.create(
            to=to,
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            content_sid=content_sid,
            content_variables=json.dumps(content_variables)
        )
        print(f"✅ Template WhatsApp inviato a {to} — SID: {message.sid}")
        return message.sid

    except Exception as e:
        print(f"❌ Errore invio template WhatsApp a {to}: {e}")
        return None
