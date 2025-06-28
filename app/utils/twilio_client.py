import os
import json
from twilio.rest import Client
import requests
from requests.auth import HTTPBasicAuth

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
        payload = {
            "To": to,
            "MessagingServiceSid": TWILIO_MESSAGING_SERVICE_SID,
            "ContentSid": content_sid,
            "ContentVariables": json.dumps(content_variables)
        }

        print("📤 Request a Twilio:", payload)

        response = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
            auth=HTTPBasicAuth(TWILIO_SID, TWILIO_TOKEN),
            data=payload
        )

        if response.status_code >= 400:
            print("❌ Twilio response:", response.status_code, response.text)
            return None

        data = response.json()
        print(f"✅ Template WhatsApp inviato a {to} — SID: {data.get('sid')}")
        return data.get("sid")

    except Exception as e:
        print(f"❌ Errore invio template WhatsApp via Content API: {e}")
        return None
