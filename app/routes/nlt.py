from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NltService

router = APIRouter(
    prefix="/nlt",
    tags=["nlt"]
)

@router.get("/services")
async def get_nlt_services(db: Session = Depends(get_db)):
    services = db.query(NltService).filter(NltService.is_active == True).all()
    return {"services": services}
