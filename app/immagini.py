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

# Carico variabili ambiente
load_dotenv()

# Variabili globali
backend_base_url = "https://coreapi-production-ca29.up.railway.app/api/image"

# Token JWT (necessario per chiamare l'endpoint protetto)
JWT_TOKEN = os.getenv("JWT_TOKEN")

# Connessione al DB remoto tramite DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Funzione per upload immagine a Supabase
def upload_to_supabase(file_bytes, filename, content_type="image/webp"):
    from supabase import create_client

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    client.storage.from_("nlt-images").upload(
        filename, file_bytes, {"content-type": content_type}
    )
    public_url = client.storage.from_("nlt-images").get_public_url(filename)
    return public_url

# Funzione per recuperare e caricare un'immagine
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

    headers = {"Authorization": f"Bearer {JWT_TOKEN}"}  # 👈 Header JWT obbligatorio

    try:
        response = httpx.get(
            f"{backend_base_url}/{codice_modello}",
            params=params,
            headers=headers,
            timeout=30.0
        )

        response.raise_for_status()  # 👈 Gestione errore HTTP dettagliato

    except httpx.HTTPStatusError as e:  # 👈 Cattura errore specifico di status HTTP
        print(f"❌ Errore dettagliato FastAPI (status {e.response.status_code}): {e.response.text}")  # 👈 importantissimo
        raise

    # Continua normalmente in caso di successo
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

# Funzione principale che popola la tabella immagini_nlt
def popola_tabella_immagini():
    db = SessionLocal()

    offerte = db.query(NltOfferte).all()

    for offerta in offerte:
        # controllo se immagini già presenti
        immagini_esistenti = db.query(ImmaginiNlt).filter(
            ImmaginiNlt.id_offerta == offerta.id_offerta
        ).first()

        if immagini_esistenti:
            print(f"✅ Offerta {offerta.id_offerta} già elaborata, salto.")
            continue

        try:
            print(f"🚀 Elaboro offerta {offerta.id_offerta}")

            front_url = recupera_e_carica_immagine(offerta.codice_modello, offerta.solo_privati, 203)
            back_url = recupera_e_carica_immagine(offerta.codice_modello, offerta.solo_privati, 213)

            nuova_immagine = ImmaginiNlt(
                id_offerta=offerta.id_offerta,
                url_immagine_front=front_url,
                url_immagine_back=back_url,
                data_creazione=datetime.utcnow()
            )

            db.add(nuova_immagine)
            db.commit()

            print(f"✅ Offerta {offerta.id_offerta} completata con successo.")

        except Exception as e:
            db.rollback()
            print(f"❌ Errore offerta {offerta.id_offerta}: {e}")

    db.close()

if __name__ == "__main__":
    popola_tabella_immagini()
