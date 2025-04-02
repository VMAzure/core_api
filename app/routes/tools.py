from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, MotornetImaginAlias
from fastapi_jwt_auth import AuthJWT
import requests
from app.routes.motornet import get_motornet_token

router = APIRouter(prefix="/tools", tags=["Tools"])

MOTORN_MARCHE_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/marche"
MOTORN_MODELLI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/marca/modelli"

@router.get("/sync-motornet-imagin")
async def sync_motornet_imagin(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter_by(email=user_email).first()

    if not user or user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Accesso negato")

    token = get_motornet_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Recupera marche
    res_marche = requests.get(MOTORN_MARCHE_URL, headers=headers)
    if res_marche.status_code != 200:
        raise HTTPException(status_code=502, detail="Errore nel recupero marche da Motornet")

    marche = res_marche.json().get("marche", [])
    inseriti = 0

    for marca in marche:
        acronimo = marca.get("acronimo")
        nome_marca = marca.get("nome")

        # Recupera modelli per la marca
        res_modelli = requests.get(f"{MOTORN_MODELLI_URL}/{acronimo}", headers=headers)
        if res_modelli.status_code != 200:
            continue

        modelli = res_modelli.json().get("modelli", [])

        for modello in modelli:
            gruppo_storico = modello.get("gruppoStorico", {}).get("descrizione")
            model_range = modello.get("serieGamma", {}).get("descrizione")
            model_variant = modello.get("modello")

            if not gruppo_storico:
                continue

            # Verifica se esiste già
            esiste = db.query(MotornetImaginAlias).filter_by(
                make=nome_marca,
                model_family=gruppo_storico
            ).first()

            if esiste:
                continue

            nuovo = MotornetImaginAlias(
                make=nome_marca,
                model_family=gruppo_storico,
                model_range=model_range,
                model_variant=model_variant
            )
            db.add(nuovo)
            inseriti += 1

    db.commit()

    return {"success": True, "nuovi_inseriti": inseriti}
