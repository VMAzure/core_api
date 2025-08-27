# app/routes/openai_config.py

from fastapi import APIRouter, HTTPException, Depends
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models import User, PurchasedServices, Services, CreditTransaction
from app.auth_helpers import is_admin_user, is_dealer_user
from app.routes.notifiche import inserisci_notifica
from app.openai_utils import genera_descrizione_gpt

router = APIRouter()

GPT_COSTO_CREDITO = 0.5

class PromptRequest(BaseModel):
    prompt: str
    max_tokens: int = 300

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

    if is_admin_user(user):
        output = await genera_descrizione_gpt(payload.prompt, payload.max_tokens)
        return {"success": True, "output": output}

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
            raise HTTPException(status_code=403, detail="Servizio GPT non attivo")

        if user.credit is None or user.credit < GPT_COSTO_CREDITO:
            raise HTTPException(status_code=402, detail="Credito insufficiente")

        output = await genera_descrizione_gpt(payload.prompt, payload.max_tokens)

        user.credit -= GPT_COSTO_CREDITO

        db.add(CreditTransaction(
            dealer_id=user.id,
            amount=-GPT_COSTO_CREDITO,
            transaction_type="USE",
            note="Generazione GPT"
        ))

        inserisci_notifica(
            db=db,
            utente_id=user.id,
            tipo_codice="CREDITO_USATO",
            messaggio="Hai utilizzato 0.5 crediti per la generazione di un testo GPT."
        )

        db.commit()

        return {"success": True, "output": output}

    raise HTTPException(status_code=403, detail="Ruolo non supportato")
