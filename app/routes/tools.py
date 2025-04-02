from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.models import User, MotornetImaginAlias
from app.database import get_db
from app.utils.motornet import get_motornet_token
import requests

router = APIRouter(prefix="/tools", tags=["Motornet Tools"])

@router.get("/sync-motornet-imagin")
def sync_modelli_motornet_imagin(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Accesso negato")

    token = get_motornet_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/modelli"
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Errore nel recupero modelli da Motornet")

    modelli = response.json().get("modelli", [])

    nuovi = 0
    for m in modelli:
        esiste = db.query(MotornetImaginAlias).filter_by(
            make=m.get("make"),
            model_family=m.get("modelFamily"),
            model_range=m.get("modelRange"),
            model_variant=m.get("modelVariant")
        ).first()

        if not esiste:
            alias = MotornetImaginAlias(
                make=m.get("make"),
                model_family=m.get("modelFamily"),
                model_range=m.get("modelRange"),
                model_variant=m.get("modelVariant")
            )
            db.add(alias)
            nuovi += 1

    db.commit()

    return {"success": True, "nuovi_inseriti": nuovi, "totale": len(modelli)}
