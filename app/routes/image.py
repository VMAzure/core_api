from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AzImage, MnetModelli, MnetMarche, User
from app.routes.nlt import get_current_user
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
    random_paint: str = Query("true"),
    width: int = Query(400, ge=150, le=2600),
    return_url: bool = Query(False),  # 🔹 nuovo parametro per switch blob/url
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
        modello_data = db.query(MnetModelli).filter(MnetModelli.codice_modello == codice_modello).first()
        if not modello_data:
            raise HTTPException(status_code=404, detail="Modello non trovato.")

        marca_data = db.query(MnetMarche).filter(MnetMarche.acronimo == modello_data.marca_acronimo).first()
        if not marca_data:
            raise HTTPException(status_code=404, detail="Marca non trovata.")

        marca = marca_data.nome.lower().replace(" ", "-")
        modello = modello_data.descrizione.lower().replace(" ", "-")
        model_variant = None

    params = {
        "make": marca,
        "modelFamily": modello,
        "angle": angle,
        "customer": "it-azureautomotive",
        "billingtag": "core",
        "zoomlevel": 1,
        "zoomType": "fullscreen",
        "randomPaint": random_paint,
        "width": width
    }

    if model_variant:
        params["modelVariant"] = model_variant

    # 🔁 Costruzione URL per return_url=true
    cdn_url = f"{IMAGIN_CDN_BASE_URL}?{requests.compat.urlencode(params)}"

    if return_url:
        return {"url": cdn_url}

    # 🔄 Altrimenti, ritorna l’immagine (blob)
    response = requests.get(cdn_url)

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Errore CDN Imagin.")

    return Response(content=response.content, media_type=response.headers['Content-Type'])

@router.get("public/{codice_modello}")
async def get_vehicle_image_public(
    codice_modello: str,
    angle: int = Query(29, ge=0, le=360),  # 🔥 angolo libero personalizzabile
    random_paint: str = Query("true"),
    width: int = Query(600, ge=150, le=2600),
    db: Session = Depends(get_db)
):
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
        modello_data = db.query(MnetModelli).filter(MnetModelli.codice_modello == codice_modello).first()
        if not modello_data:
            raise HTTPException(status_code=404, detail="Modello non trovato.")

        marca_data = db.query(MnetMarche).filter(MnetMarche.acronimo == modello_data.marca_acronimo).first()
        if not marca_data:
            raise HTTPException(status_code=404, detail="Marca non trovata.")

        marca = marca_data.nome.lower().replace(" ", "-")
        modello = modello_data.descrizione.lower().replace(" ", "-")
        model_variant = None

    params = {
        "make": marca,
        "modelFamily": modello,
        "angle": angle,
        "customer": "it-azureautomotive",
        "billingtag": "core",
        "zoomlevel": 1,
        "zoomType": "fullscreen",
        "randomPaint": random_paint,
        "width": width
    }

    if model_variant:
        params["modelVariant"] = model_variant

    cdn_url = f"{IMAGIN_CDN_BASE_URL}?{requests.compat.urlencode(params)}"

    # Ritorna URL diretto alla CDN pubblica
    return {"url": cdn_url}

