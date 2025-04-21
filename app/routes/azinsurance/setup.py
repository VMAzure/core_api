from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.routes.azinsurance.models_azinsurance import (
    AssCompagnia, AssAgenzia, AssRamo,
    AssStatoPolizza, AssFrazionamento, AssGaranzia
)
from app.routes.azinsurance.schemas_azinsurance import (
    CompagniaBase, AgenziaBase, GaranziaBase
)
from typing import List

router = APIRouter(
    prefix="/insurance",
    tags=["insurance"]
)

# ----------------- COMPAGNIE -----------------

@router.post("/compagnie", response_model=CompagniaBase)
def create_compagnia(compagnia: CompagniaBase, db: Session = Depends(get_db)):
    db_compagnia = AssCompagnia(**compagnia.dict())
    db.add(db_compagnia)
    db.commit()
    db.refresh(db_compagnia)
    return db_compagnia

@router.get("/compagnie", response_model=List[CompagniaBase])
def list_compagnie(db: Session = Depends(get_db)):
    return db.query(AssCompagnia).all()

@router.put("/compagnie/{compagnia_id}", response_model=CompagniaBase)
def update_compagnia(compagnia_id: int, compagnia: CompagniaBase, db: Session = Depends(get_db)):
    db_compagnia = db.query(AssCompagnia).filter(AssCompagnia.id == compagnia_id).first()
    if not db_compagnia:
        raise HTTPException(status_code=404, detail="Compagnia non trovata")
    for key, value in compagnia.dict().items():
        setattr(db_compagnia, key, value)
    db.commit()
    db.refresh(db_compagnia)
    return db_compagnia

# ----------------- AGENZIE -----------------

@router.post("/agenzie", response_model=AgenziaBase)
def create_agenzia(agenzia: AgenziaBase, db: Session = Depends(get_db)):
    db_agenzia = AssAgenzia(**agenzia.dict())
    db.add(db_agenzia)
    db.commit()
    db.refresh(db_agenzia)
    return db_agenzia

@router.get("/agenzie", response_model=List[AgenziaBase])
def list_agenzie(db: Session = Depends(get_db)):
    return db.query(AssAgenzia).all()

@router.put("/agenzie/{agenzia_id}", response_model=AgenziaBase)
def update_agenzia(agenzia_id: int, agenzia: AgenziaBase, db: Session = Depends(get_db)):
    db_agenzia = db.query(AssAgenzia).filter(AssAgenzia.id == agenzia_id).first()
    if not db_agenzia:
        raise HTTPException(status_code=404, detail="Agenzia non trovata")
    for key, value in agenzia.dict().items():
        setattr(db_agenzia, key, value)
    db.commit()
    db.refresh(db_agenzia)
    return db_agenzia

# ----------------- GARANZIE -----------------

@router.post("/garanzie", response_model=GaranziaBase)
def create_garanzia(garanzia: GaranziaBase, db: Session = Depends(get_db)):
    db_garanzia = AssGaranzia(**garanzia.dict())
    db.add(db_garanzia)
    db.commit()
    db.refresh(db_garanzia)
    return db_garanzia

@router.get("/garanzie", response_model=List[GaranziaBase])
def list_garanzie(db: Session = Depends(get_db)):
    return db.query(AssGaranzia).all()

@router.put("/garanzie/{garanzia_id}", response_model=GaranziaBase)
def update_garanzia(garanzia_id: int, garanzia: GaranziaBase, db: Session = Depends(get_db)):
    db_garanzia = db.query(AssGaranzia).filter(AssGaranzia.id == garanzia_id).first()
    if not db_garanzia:
        raise HTTPException(status_code=404, detail="Garanzia non trovata")
    for key, value in garanzia.dict().items():
        setattr(db_garanzia, key, value)
    db.commit()
    db.refresh(db_garanzia)
    return db_garanzia
