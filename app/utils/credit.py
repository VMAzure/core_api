from fastapi import HTTPException
from app.models import CreditTransaction, Services, User
from sqlalchemy.orm import Session
from datetime import datetime

def addebita_credito_per_utilizzo(
    db: Session,
    dealer: User,
    service: Services,
    context_message: str = ""
):
    if not service.is_pay_per_use:
        raise Exception("Servizio non configurato per uso a consumo.")

    prezzo = service.pay_per_use_price

    if dealer.credit < prezzo:
        raise HTTPException(status_code=402, detail="Credito insufficiente.")

    dealer.credit -= prezzo

    transazione = CreditTransaction(
        dealer_id=dealer.id,
        amount=prezzo,
        transaction_type="USE",
        created_at=datetime.utcnow(),
        note=context_message
    )

    db.add(transazione)
    db.commit()

    return {
        "success": True,
        "scalato": prezzo,
        "credito_residuo": dealer.credit
    }
