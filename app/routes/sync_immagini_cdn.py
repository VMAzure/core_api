import requests
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.database import engine
from app.database import upload_to_supabase

# Config
API_BASE = "https://coreapi-production-ca29.up.railway.app"
PROMPT = (
    "Genera un immagine stile fotografico realistico professionale da catalogo di questa auto. "
    "L'auto è al centro e occupa il 80% dell'immagine come se fotografata con obbiettivo da 85mm. "
    "L'auto è posizionata su strada in una giornata invernale. "
    "Luci d'ambiente riflettono sulla carrozzeria. "
    "Resta fedele ai dettagli e alla posizione del soggetto senza applicare targa o scritte non presenti nell'immagine."
)

SessionLocal = sessionmaker(bind=engine)

def genera_img_ai(url_origine: str) -> bytes:
    """Chiama la rotta /veo3/image-webp e restituisce i bytes webp generati."""
    resp = requests.post(
        f"{API_BASE}/veo3/image-webp",
        json={"prompt": PROMPT, "start_image_url": url_origine},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.content

def sync_modelli_ai():
    session = SessionLocal()
    rows = session.execute(text("""
        SELECT codice_modello, default_img
        FROM mnet_modelli
        WHERE default_img IS NOT NULL
          AND default_img_ai IS NULL
    """)).mappings().all()

    print(f"Trovati {len(rows)} modelli da processare")

    for r in rows:
        codice = r["codice_modello"]
        orig_url = r["default_img"]

        try:
            print(f"🔄 Processing {codice}...")
            img_bytes = genera_img_ai(orig_url)

            filename = f"{codice}_ai.webp"
            supa_url = upload_to_supabase(
                file_bytes=img_bytes,
                filename=filename,
                bucket="immagini-nuovo",
                content_type="image/webp",
            )

            session.execute(
                text("UPDATE mnet_modelli SET default_img_ai = :url WHERE codice_modello = :cm"),
                {"url": supa_url, "cm": codice},
            )
            session.commit()

            print(f"✔️ {codice} -> {supa_url}")

        except Exception as e:
            print(f"❌ Errore {codice}: {e}")

if __name__ == "__main__":
    sync_modelli_ai()
