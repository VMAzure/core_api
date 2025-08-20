from app.models import Notifica, NotificaType
from sqlalchemy.orm import Session
from datetime import datetime

def get_tipo_id(codice: str, db: Session) -> int:
    tipo = db.query(NotificaType).filter_by(codice=codice).first()
    if not tipo:
        raise ValueError(f"Tipo notifica '{codice}' non trovato")
    return tipo.id

def inserisci_notifica(
    db: Session,
    utente_id: int,
    tipo_codice: str,
    messaggio: str,
    cliente_id: int | None = None
):
    tipo_id = get_tipo_id(tipo_codice, db)
    notifica = Notifica(
        utente_id=utente_id,
        cliente_id=cliente_id,
        tipo_id=tipo_id,
        messaggio=messaggio,
        data_creazione=datetime.utcnow(),
        letta=False
    )
    db.add(notifica)
    db.commit()
    return notifica.id
