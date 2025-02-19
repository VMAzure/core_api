from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
import os

logs_router = APIRouter(prefix="/logs", tags=["Logs"])

# Funzione per ottenere il database
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Endpoint per recuperare i log
@logs_router.get("/")
def get_logs(
    start_date: str = Query(None, description="Data di inizio (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Data di fine (YYYY-MM-DD)"),
    admin_email: str = Query(None, description="Email dell'admin"),
    event_type: str = Query(None, description="Tipo di evento (rinnovo, sospensione, errore)"),
    db: Session = Depends(get_db)
):
    """Restituisce i log filtrati per data, admin o tipo di evento dal database"""
    
    query = text("SELECT timestamp, admin_email, event_type, message FROM logs WHERE 1=1")
    params = {}

    if start_date:
        query = text(query.text + " AND timestamp >= :start_date")
        params["start_date"] = start_date

    if end_date:
        query = text(query.text + " AND timestamp <= :end_date")
        params["end_date"] = end_date

    if admin_email:
        query = text(query.text + " AND admin_email = :admin_email")
        params["admin_email"] = admin_email

    if event_type:
        query = text(query.text + " AND event_type = :event_type")
        params["event_type"] = event_type

    logs = db.execute(query, params).fetchall()

    if not logs:
        return {"message": "Nessun log trovato con i filtri selezionati."}

    return {"logs": [dict(log) for log in logs]}

