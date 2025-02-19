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
    event_type: str = Query(None, description="Tipo di evento (rinnovo, sospensione, errore)")
):
    """Restituisce i log filtrati per data, admin o tipo di evento"""
    
    log_file_path = "cron_job.log"  # Nome del file log generato dal cron job
    
    if not os.path.exists(log_file_path):
        raise HTTPException(status_code=404, detail="File di log non trovato.")

    filtered_logs = []

    with open(log_file_path, "r") as log_file:
        for line in log_file:
            if start_date and start_date not in line:
                continue
            if end_date and end_date not in line:
                continue
            if admin_email and admin_email not in line:
                continue
            if event_type and event_type.lower() not in line.lower():
                continue
            
            filtered_logs.append(line.strip())

    if not filtered_logs:
        return {"message": "Nessun log trovato con i filtri selezionati."}

    return {"logs": filtered_logs}
