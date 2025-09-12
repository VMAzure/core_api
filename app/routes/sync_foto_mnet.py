import requests
import time
from sqlalchemy import text
from app.database import SessionLocal
from app.models import MnetAllestimenti, MnetImmagini
from datetime import datetime
from sync_dettagli_nuovo import get_motornet_token


FOTO_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/foto"

def sync_foto_mnet():
    db = SessionLocal()

    # prendi tutti gli allestimenti
    allestimenti = db.query(MnetAllestimenti.codice_motornet_uni).all()

    token = get_motornet_token()  # riusa la funzione già scritta
    headers = {"Authorization": f"Bearer {token}"}

    for (codice_uni,) in allestimenti:
        try:
            r = requests.get(
                f"{FOTO_URL}?codice_motornet_uni={codice_uni}&risoluzione=H",
                headers=headers,
                timeout=30
            )
            if r.status_code == 401:
                # rinnovo token una volta
                token = get_motornet_token()
                headers = {"Authorization": f"Bearer {token}"}
                r = requests.get(
                    f"{FOTO_URL}?codice_motornet_uni={codice_uni}&risoluzione=H",
                    headers=headers,
                    timeout=30
                )

            r.raise_for_status()
            data = r.json()

            for img in data.get("immagini", []):
                exists = db.query(MnetImmagini).filter_by(
                    codice_motornet_uni=codice_uni,
                    url=img["url"]
                ).first()
                if exists:
                    continue

                rec = MnetImmagini(
                    codice_motornet_uni=codice_uni,
                    url=img["url"],
                    codice_fotografia=img.get("codiceFotografia"),
                    codice_visuale=img.get("codiceVisuale"),
                    descrizione_visuale=img.get("descrizioneVisuale"),
                    risoluzione=img.get("risoluzione"),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(rec)
            db.commit()

        except Exception as e:
            print(f"❌ Errore per {codice_uni}: {e}")
            db.rollback()
            time.sleep(1)

    db.close()
