from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    AIAssistente,
    AIChatLog,
    AIChatLogAuto,
    AZLeaseUsatoAuto,
    AZLeaseUsatoIn,
)

import httpx, os
import logging

logger = logging.getLogger("uvicorn.error")  # agganciato ai log di uvicorn


router = APIRouter(prefix="/api/assistente", tags=["Assistente"])


# -------------------- Schemas --------------------
class ChatRequest(BaseModel):
    domanda: str


class ChatResponse(BaseModel):
    risposta: str
    auto_riferite: Optional[List[str]] = None


class AssistantSchema(BaseModel):
    id: str
    slug: str
    nome: str
    modello: str
    temperatura: float
    top_p: float
    max_tokens: int
    lingua: str
    persona: Optional[str]
    istruzioni: Optional[str]
    contesto: Optional[str]
    attivo: bool

    class Config:
        orm_mode = True


# -------------------- Helpers --------------------
async def call_ai(assistente: AIAssistente, domanda: str, auto: List[dict]) -> str:
    context = "\n".join(
        [
            f"- {a['marca']} {a['modello']} {a['anno']} ({a['prezzo']}€): {a['descrizione']}"
            for a in auto
        ]
    )
    system_prompt = (
        f"{assistente.persona or ''}\n"
        f"{assistente.istruzioni or ''}\n\n"
        f"Auto disponibili:\n{context}"
    )

    payload = {
        "model": assistente.modello,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": domanda},
        ],
        "temperature": float(assistente.temperatura or 0.3),
        "top_p": float(assistente.top_p or 0.9),
        "max_tokens": assistente.max_tokens or 500,
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json=payload,
        )
        if r.status_code != 200:
            raise HTTPException(status_code=500, detail=r.text)
        data = r.json()
        return data["choices"][0]["message"]["content"]


def get_auto_for_assistant(db: Session, assistente: AIAssistente, slug: str):

    print("=== DEBUG get_auto_for_assistant ===")
    print("Slug richiesto:", slug)
    print("Assistente:", {
        "id": str(assistente.id),
        "dealer_user_id": assistente.dealer_user_id,
        "slug": assistente.slug,
        "modello": assistente.modello,
        "attivo": assistente.attivo
    })

    try:
        query = (
            db.query(AZLeaseUsatoAuto)
            .join(AZLeaseUsatoIn, AZLeaseUsatoAuto.id_usatoin == AZLeaseUsatoIn.id)
            .filter(AZLeaseUsatoIn.visibile == True)
        )

        if slug != "azure-automotive":  # se non admin → filtro per dealer
            query = query.filter(AZLeaseUsatoIn.dealer_id == assistente.dealer_user_id)

        autos = query.all()
        print(f"Numero auto trovate: {len(autos)}")

        results = []
        for auto in autos:
            try:
                print(">> Auto:", str(auto.id), "targa:", auto.targa)

                accessori = [a.descrizione for a in auto.accessori_optional if a.presente]
                pacchetti = [p.descrizione for p in auto.accessori_pacchetti if p.presente]

                descr = auto.precisazioni or ""
                if accessori:
                    descr += " Accessori: " + ", ".join(accessori)
                if pacchetti:
                    descr += " Pacchetti: " + ", ".join(pacchetti)

                prezzo = None
                if auto.usatoin:
                    prezzo = auto.usatoin.prezzo_vendita
                else:
                    print("⚠️  Attenzione: usatoin mancante per auto", str(auto.id))

                results.append({
                    "id": str(auto.id),
                    "marca": auto.codice_motornet or "n.d.",
                    "modello": "",  # TODO: join su mnet_dettagli_usato
                    "anno": auto.anno_immatricolazione,
                    "prezzo": prezzo,
                    "descrizione": descr
                })
            except Exception as e:
                print("❌ Errore processando auto", str(auto.id), ":", e)

        print("=== Fine DEBUG get_auto_for_assistant ===")
        return results

    except Exception as e:
        print("❌ Errore generale in get_auto_for_assistant:", e)
        raise



# -------------------- Endpoint --------------------
@router.post("/chat/{slug}", response_model=ChatResponse)
async def chat_with_assistant(slug: str, req: ChatRequest, db: Session = Depends(get_db)):
    logger.info("Assistente caricato %s", assistente.id)

    assistente = db.query(AIAssistente).filter_by(slug=slug).first()
    logger.info("DEBUG assistente query (senza filtro attivo): %s", assistente)
    
    if not assistente:
        raise HTTPException(status_code=404, detail="Assistente non trovato")

    auto = get_auto_for_assistant(db, assistente, slug)
    if not auto:
        return ChatResponse(
            risposta="Al momento non ci sono auto disponibili per questo dealer.",
            auto_riferite=[],
        )

    risposta = await call_ai(assistente, req.domanda, auto)

    # log della conversazione
    chat_log = AIChatLog(
        dealer_user_id=assistente.dealer_user_id,
        assistant_id=assistente.id,
        slug=slug,
        sorgente="web",
        utente_ref="session",  # TODO: sostituire con id utente reale
        domanda=req.domanda,
        risposta=risposta,
    )
    db.add(chat_log)
    db.commit()

    return ChatResponse(risposta=risposta, auto_riferite=[a["id"] for a in auto])
