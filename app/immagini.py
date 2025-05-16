import os
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import httpx
import uuid
from PIL import Image
from io import BytesIO
from app.models import NltOfferte, ImmaginiNlt
from datetime import datetime
from supabase import create_client

# Carico variabili ambiente
load_dotenv()

# Variabili globali
backend_base_url = "https://coreapi-production-ca29.up.railway.app/api/image"
JWT_TOKEN = os.getenv("JWT_TOKEN")

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def upload_to_supabase(file_bytes, filename, content_type="image/webp"):
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    client.storage.from_("nlt-images").upload(
        filename, file_bytes, {"content-type": content_type}
    )
    return client.storage.from_("nlt-images").get_public_url(filename)

def recupera_e_carica_immagine(codice_modello, angle, solo_privati=None):
    params = {
        "angle": angle,
        "width": 800,
        "return_url": False,
        "random_paint": "true"
    }

    # Logica esistente solo per le prime due immagini
    if solo_privati is not None:
        if solo_privati:
            if angle == 203:
                params["surrounding"] = "sur5"
                params["viewPoint"] = "1"
            elif angle == 213:
                params["surrounding"] = "sur5"
                params["viewPoint"] = "2"
        else:
            if angle == 203:
                params["surrounding"] = "sur2"
                params["viewPoint"] = "1"
            elif angle == 213:
                params["surrounding"] = "sur2"
                params["viewPoint"] = "4"

    headers = {"Authorization": f"Bearer {JWT_TOKEN}"}

    try:
        response = httpx.get(
            f"{backend_base_url}/{codice_modello}",
            params=params,
            headers=headers,
            timeout=30.0
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"❌ Errore immagine {codice_modello} (status {e.response.status_code}): {e.response.text}")
        raise

    image = Image.open(BytesIO(response.content)).convert("RGB")
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='WEBP', quality=90)
    img_byte_arr.seek(0)

    unique_filename = f"{codice_modello}_{angle}_{uuid.uuid4().hex}.webp"
    return upload_to_supabase(
        file_bytes=img_byte_arr.getvalue(),
        filename=unique_filename,
        content_type="image/webp"
    )

def popola_tabella_immagini():
    db = SessionLocal()

    offerte = db.query(NltOfferte).all()

    for offerta in offerte:
        immagini_esistenti = db.query(ImmaginiNlt).filter(
            ImmaginiNlt.id_offerta == offerta.id_offerta
        ).first()

        # Se non esistono immagini, inserisce tutte e 4
        if not immagini_esistenti:
            try:
                print(f"🚀 Elaboro offerta completa {offerta.id_offerta}")

                front_url = recupera_e_carica_immagine(offerta.codice_modello, 203, offerta.solo_privati)
                back_url = recupera_e_carica_immagine(offerta.codice_modello, 213, offerta.solo_privati)
                front_alt_url = recupera_e_carica_immagine(offerta.codice_modello, 23)
                back_alt_url = recupera_e_carica_immagine(offerta.codice_modello, 9)

                nuova_immagine = ImmaginiNlt(
                    id_offerta=offerta.id_offerta,
                    url_immagine_front=front_url,
                    url_immagine_back=back_url,
                    url_immagine_front_alt=front_alt_url,
                    url_immagine_back_alt=back_alt_url,
                    data_creazione=datetime.utcnow()
                )

                db.add(nuova_immagine)
                db.commit()

                print(f"✅ Offerta {offerta.id_offerta} completata (4 immagini).")

            except Exception as e:
                db.rollback()
                print(f"❌ Errore offerta {offerta.id_offerta}: {e}")
        else:
            # Se già esistono solo prime due, genera e aggiunge le altre due
            if not immagini_esistenti.url_immagine_front_alt or not immagini_esistenti.url_immagine_back_alt:
                try:
                    print(f"🚀 Aggiorno offerta {offerta.id_offerta} con immagini aggiuntive")

                    if not immagini_esistenti.url_immagine_front_alt:
                        immagini_esistenti.url_immagine_front_alt = recupera_e_carica_immagine(offerta.codice_modello, 23)
                    if not immagini_esistenti.url_immagine_back_alt:
                        immagini_esistenti.url_immagine_back_alt = recupera_e_carica_immagine(offerta.codice_modello, 9)

                    db.commit()

                    print(f"✅ Offerta {offerta.id_offerta} aggiornata con successo.")

                except Exception as e:
                    db.rollback()
                    print(f"❌ Errore aggiornamento offerta {offerta.id_offerta}: {e}")
            else:
                print(f"✅ Offerta {offerta.id_offerta} già completa con 4 immagini, salto.")

    db.close()

if __name__ == "__main__":
    popola_tabella_immagini()
