from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AzImage, MnetModelli, MnetMarche, User
from app.routes.nlt import get_current_user  # 👈 correggi questa linea
import requests

router = APIRouter(
    prefix="/api/image",
    tags=["image"]
)

IMAGIN_CDN_BASE_URL = "https://cdn.imagin.studio/getImage"

@router.get("/{codice_modello}")
async def get_vehicle_image(
    codice_modello: str,
    angle: int = Query(29),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Cerco prima alias nella tabella az_image
    alias = db.query(AzImage).filter(AzImage.codice_modello == codice_modello).first()

    if alias:
        modello = alias.modello_alias
        model_variant = alias.model_variant

        if alias.marca_alias:
            marca = alias.marca_alias
        else:
            modello_data = db.query(MnetModelli).filter(MnetModelli.codice_modello == codice_modello).first()
            marca_data = db.query(MnetMarche).filter(MnetMarche.acronimo == modello_data.marca_acronimo).first()
            marca = marca_data.nome.lower().replace(" ", "-")
    else:
        # Recupero dati originali
        modello_data = db.query(MnetModelli).filter(MnetModelli.codice_modello == codice_modello).first()

        if not modello_data:
            raise HTTPException(status_code=404, detail="Modello non trovato.")

        marca_data = db.query(MnetMarche).filter(MnetMarche.acronimo == modello_data.marca_acronimo).first()

        if not marca_data:
            raise HTTPException(status_code=404, detail="Marca non trovata.")

        marca = marca_data.nome.lower().replace(" ", "-")
        modello = modello_data.descrizione.lower().replace(" ", "-")
        model_variant = None


    # Preparo parametri per la CDN
    params = {
        "make": marca,
        "modelFamily": modello,
        "angle": angle,
        "customer": "it-azureautomotive",
        "billingtag": "core"
    }

    if model_variant:
        params["modelVariant"] = model_variant

    # Formo l'URL finale
    response = requests.get(IMAGIN_CDN_BASE_URL, params=params)

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Errore CDN Imagin.")

    return {"success": True, "image_url": response.url}
