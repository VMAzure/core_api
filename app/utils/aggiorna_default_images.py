import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))


from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import MnetModelli, MnetMarche

from urllib.parse import urlencode

IMAGIN_CDN_BASE_URL = "https://cdn.imagin.studio/getImage"

def aggiorna_default_images():
    db: Session = SessionLocal()
    modelli = db.query(MnetModelli).all()

    for modello in modelli:
        marca_data = db.query(MnetMarche).filter(MnetMarche.acronimo == modello.marca_acronimo).first()

        if not marca_data:
            continue

        marca = marca_data.nome.lower().replace(" ", "-")
        modello_nome = modello.descrizione.lower().replace(" ", "-")

        params = {
            "make": marca,
            "modelFamily": modello_nome,
            "angle": 23,
            "customer": "it-azureautomotive",
            "billingtag": "core",
            "zoomlevel": 1,
            "zoomType": "fullscreen",
            "randomPaint": "true",
            "width": 400
        }

        cdn_url = f"{IMAGIN_CDN_BASE_URL}?{urlencode(params)}"
        modello.default_img = cdn_url

        db.add(modello)  # 🔥 QUESTA RIGA DEVE ESSERCI!



    db.commit()
    db.close()

if __name__ == "__main__":
    aggiorna_default_images()
