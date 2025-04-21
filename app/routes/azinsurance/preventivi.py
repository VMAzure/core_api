from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from .schemas_azinsurance import PreventivoCreate, PreventivoResponse
from .models_azinsurance import AssPreventivo

router = APIRouter()

@router.post("/", response_model=PreventivoResponse)
def crea_preventivo(preventivo: PreventivoCreate, db: Session = Depends(get_db)):
    nuovo_preventivo = AssPreventivo(**preventivo.dict())
    db.add(nuovo_preventivo)
    db.commit()
    db.refresh(nuovo_preventivo)
    return nuovo_preventivo
