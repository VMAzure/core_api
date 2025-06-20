from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, raiseload, joinedload
from uuid import UUID
from fastapi_jwt_auth import AuthJWT  
from fastapi import Body
from app.auth_helpers import is_admin_user, is_dealer_user, is_team_user, get_admin_id, get_dealer_id
from app.database import get_db
from app.models import NltPipeline, NltPipelineStati, NltPreventivi, User, CrmAzione, NltPipelineLog
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta

def calcola_scadenza_azione_intelligente(ora_attuale: datetime) -> datetime:
    ora_inizio = ora_attuale.replace(hour=9, minute=0, second=0, microsecond=0)
    ora_fine = ora_attuale.replace(hour=17, minute=0, second=0, microsecond=0)

    if ora_attuale.weekday() >= 5:
        giorni_fino_lunedi = 7 - ora_attuale.weekday()
        return ora_inizio + timedelta(days=giorni_fino_lunedi, hours=1)

    if ora_attuale < ora_inizio:
        return ora_inizio + timedelta(hours=2)

    if ora_attuale >= ora_fine:
        giorno_successivo = ora_attuale + timedelta(days=1)
        while giorno_successivo.weekday() >= 5:
            giorno_successivo += timedelta(days=1)
        return giorno_successivo.replace(hour=10, minute=0, second=0, microsecond=0)

    scadenza = ora_attuale + timedelta(hours=3)
    return min(scadenza, ora_fine)

