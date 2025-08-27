# app/routes/openai_config.py

from fastapi import APIRouter, HTTPException, Depends
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from pydantic import BaseModel
from openai import AsyncOpenAI
from app.database import get_db
from app.models import User, PurchasedServices, Services, CreditTransaction
from app.auth_helpers import is_admin_user, is_dealer_user
from app.routes.notifiche import inserisci_notifica
import os

router = APIRouter()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

GPT_COSTO_CREDITO = 0.5  # credito scalato per ogni richiesta

class PromptRequest(BaseModel):
    prompt: str
    max_tokens: int = 300

async def genera_testo_gpt(prompt: str, max_tokens: int = 300):
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ Errore GPT:", e)
        raise HTTPException(status_code=500, detail="Errore generazione testo GPT.")

@router.post("/openai/genera", tags=["OpenAI"])
async def genera_testo(
    payload: PromptRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=403, detail="Utente non trovato")

    # ✅ ADMIN = accesso libero
    if is_admin_user(user):
        output = await genera_testo_gpt(payload.prompt, payload.max_tokens)
        return {"success": True, "output": output}

    # ✅ DEALER = servizio attivo + credito sufficiente
    if is_dealer_user(user):
        servizio_attivo = (
            db.query(PurchasedServices)
            .join(Services, PurchasedServices.service_id == Services.id)
            .filter(
                Services.name == "GPT",
                PurchasedServices.status == "attivo",
                PurchasedServices.dealer_id == user.id
            )
            .first()
        )

        if not servizio_attivo:
            raise HTTPException(status_code=403, detail="Servizio GPT non attivo per questo dealer")

        if user.credit is None or user.credit < GPT_COSTO_CREDITO:
            raise HTTPException(status_code=402, detail="Credito insufficiente")

        # ✅ Generazione + addebito
        output = await genera_testo_gpt(payload.prompt, payload.max_tokens)

        user.credit -= GPT_COSTO_CREDITO

        addebito = CreditTransaction(
            dealer_id=user.id,
            amount=-GPT_COSTO_CREDITO,
            transaction_type="USE",
            note="Generazione GPT"
        )
        db.add(addebito)

        inserisci_notifica(
            db=db,
            utente_id=user.id,
            tipo_codice="CREDITO_USATO",  # deve esistere in notifica_type
            messaggio="Hai utilizzato 0.5 crediti per la generazione di un testo GPT."
        )

        db.commit()

        return {"success": True, "output": output}

    raise HTTPException(status_code=403, detail="Ruolo utente non supportato")
