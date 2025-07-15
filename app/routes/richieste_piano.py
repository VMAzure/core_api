from fastapi import APIRouter, Form, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.utils.email import send_email  # Adatta al tuo path reale se diverso

router = APIRouter()

@router.post("/api/invia-richiesta-piano")
async def invia_richiesta_piano(
    nome: str = Form(...),
    email: str = Form(...),
    telefono: str = Form(None),
    messaggio: str = Form(None),
    piano: str = Form(None),
    db: Session = Depends(get_db)
):
    admin_id = 13  # ID admin 

    subject = f"📩 Nuova richiesta piano NLT.rent - {piano or 'non specificato'}"

    body = f"""
    <h2>📌 Richiesta per il piano: <strong>{piano or 'N/D'}</strong></h2>
    <p><strong>Nome azienda:</strong> {nome}</p>
    <p><strong>Email:</strong> {email}</p>
    <p><strong>Telefono:</strong> {telefono or '-'}</p>
    <p><strong>Messaggio:</strong><br>{messaggio or '(nessun messaggio)'}</p>
    <hr>
    <p>Questa richiesta è stata inviata dal sito NLT.rent</p>
    """

    try:
        send_email(admin_id=admin_id, to_email="richieste@nlt.rent", subject=subject, body=body)
        return JSONResponse(content={"success": True, "message": "Richiesta inviata correttamente."})
    
    except Exception as e:
        print("❌ Errore invio email:", e)
        raise HTTPException(status_code=500, detail="Errore invio.")