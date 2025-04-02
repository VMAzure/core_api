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
    marche_saltate = []

    for marca in marche:
        acronimo = marca["acronimo"]

        try:
            modelli_url = f"{MOTORN_MODELLI_URL}/{acronimo}"
            modelli_res = requests.get(modelli_url, headers=headers)

            if modelli_res.status_code != 200:
                print(f"❌ Errore su marca {acronimo}: status {modelli_res.status_code}")
                marche_saltate.append(acronimo)
                continue

            modelli = modelli_res.json().get("modelli", [])

            for modello in modelli:
                alias = MotornetImaginAlias(
                    marca=marca["nome"],
                    acronimo=acronimo,
                    modello=modello.get("modello", ""),
                    gruppo_storico=modello.get("gruppoStorico", {}).get("descrizione", ""),
                    model_range=modello.get("gammaModello", {}).get("descrizione", ""),
                    model_variant=modello.get("serieGamma", {}).get("descrizione", "")
                )
                db.add(alias)
                inseriti += 1

        except Exception as e:
            print(f"⚠️ Errore imprevisto su marca {acronimo}: {e}")
            marche_saltate.append(acronimo)
            continue

    db.commit()
    return {
        "success": True,
        "nuovi_inseriti": inseriti,
        "marche_saltate": marche_saltate
    }
