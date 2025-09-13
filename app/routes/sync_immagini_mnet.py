import asyncio
import logging
from app.database import SessionLocal
from app.routes.modelli_ai_test import sync_immagini_mnet

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db = SessionLocal()
    asyncio.run(sync_immagini_mnet(db))
