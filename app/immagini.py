# immagini.py
import os
import uuid
import httpx
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from app.models import NltOfferte, ImmaginiNlt
from supabase import create_client

load_dotenv()

# Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Connessione al DB remoto tramite DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

backend_base_url = "https://coreapi-production-ca29.up.railway.app/api/image"

def upload_to_supabase(file_bytes, filename, content_type="image/webp"):
    result = client.storage.from_("nlt-images").upload(
        filename, file_bytes, {"content-type": content_type}
    )
    public_url = client.storage.from_("nlt-images").get_public_url(filename)
    return public_url

def recupera_e_carica_immagine(codice_modello, solo_privati, angle):
    params = {
        "angle": angle,
        "width": 800,
        "return_url": False,
        "random_paint": "true"
    }

    if solo_privati:
        if angle == 203:
            params["surrounding"] = "sur5"
            params["viewPoint"] = "1"
        else:  # angle == 213
            params["surrounding"] = "sur5"
            params["viewPoint"] = "2"
    else:
        if angle == 203:
            params["surrounding"] = "sur2"
            params["viewPoint"] = "1"
        else:  # angle == 213
            params["surrounding"] = "sur2"
            params["viewPoint"] = "4"

    response = httpx.get(
        f"{backend_base_url}/{codice_modello}",
        params=params,
        timeout=30.0
    )

    response.raise_for_status()

    image = Image.open(BytesIO(response.content)).convert("RGB")
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='WEBP', quality=90)
    img_byte_arr.seek(0)

    unique_filename = f"{codice_modello}_{angle}_{uuid.uuid4().hex}.webp"
    supabase_url = upload_to_supabase(
        file_bytes=img_byte_arr.getvalue(),
        filename=unique_filename,
        content_type="image/webp"
    )

    return supabase_url

def popola_tabella_immagini():
    db = SessionLocal()

    offerte = db.query(NltOfferte).all()

    for offerta in offerte:
        # Verifica se l'offerta è già stata elaborata
        if db.query(ImmaginiNlt).filter(ImmaginiNlt.id_offerta == offerta.id_offerta).first():
            print(f"✅ Offerta {offerta.id_offerta} già elaborata, salto.")
            continue

        try:
            front_url = recupera_e_carica_immagine(offerta.codice_modello, offerta.solo_privati, 203)
            back_url = recupera_e_carica_immagine(offerta.codice_modello, offerta.solo_privati, 213)

            nuova_immagine = ImmaginiNlt(
                id_offerta=offerta.id_offerta,
                url_immagine_front=front_url,
                url_immagine_back=back_url
            )

            db.add(nuova_immagine)
            db.commit()
            print(f"🚀 Offerta {offerta.id_offerta} completata con successo.")

        except Exception as e:
            db.rollback()
            print(f"❌ Errore offerta {offerta.id_offerta}: {e}")

    db.close()

if __name__ == "__main__":
    popola_tabella_immagini()
