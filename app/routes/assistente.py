from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from app.database import get_db
from models import AIAssistente, AIChatLog, AIChatLogAuto, AzLeaseUsatoAuto
import httpx, os
from sqlalchemy.orm import joinedload

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
    context = "\n".join([
        f"- {a['marca']} {a['modello']} {a['anno']} ({a['prezzo']}€): {a['descrizione']}"
        for a in auto
    ])
    system_prompt = f"{assistente.persona or ''}\n{assistente.istruzioni or ''}\n\nAuto disponibili:\n{context}"

    payload = {
        "model": assistente.modello,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": domanda}
        ],
        "temperature": float(assistente.temperatura or 0.3),
        "top_p": float(assistente.top_p or 0.9),
        "max_tokens": assistente.max_tokens or 500
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            json=payload
        )
        if r.status_code != 200:
            raise HTTPException(status_code=500, detail=r.text)
        data = r.json()
        return data["choices"][0]["message"]["content"]


def get_auto_for_assistant(db: Session, assistente: AIAssistente, slug: str):
    query = db.query(AzLeaseUsatoAuto).filter(AzLeaseUsatoAuto.status == "attivo")

    if slug != "azure-automotive":  # se NON è admin → filtro sullo slug
        query = query.filter(AzLeaseUsatoAuto.slug == slug)

    query = query.options(
        joinedload(AzLeaseUsatoAuto.accessori_optional),
        joinedload(AzLeaseUsatoAuto.pacchetti)
    )

    results = []
    for auto in query.all():
        accessori = [a.descrizione for a in auto.accessori_optional if a.presente]
        pacchetti = [p.descrizione for p in auto.pacchetti if p.presente]
        descr = auto.descrizione or ""
        if accessori:
            descr += " Accessori: " + ", ".join(accessori)
        if pacchetti:
            descr += " Pacchetti: " + ", ".join(pacchetti)

        results.append({
            "id": str(auto.id),
            "marca": auto.marca,
            "modello": auto.modello,
            "anno": auto.anno_immatricolazione,
            "prezzo": auto.prezzo,
            "descrizione": descr,
            "dealer_slug": auto.slug
        })
    return results



# -------------------- Endpoint --------------------
@router.post("/chat/{slug}", response_model=ChatResponse)
async def chat_with_assistant(slug: str, req: ChatRequest, db: Session = Depends(get_db)):
    assistente = db.query(AIAssistente).filter_by(slug=slug, attivo=True).first()
    if not assistente:
        raise HTTPException(status_code=404, detail="Assistente non trovato")

    # fetch auto reali
    auto = get_auto_for_assistant(db, assistente, slug)

    if not auto:
        return ChatResponse(risposta="Al momento non ci sono auto disponibili per questo dealer.", auto_riferite=[])

    risposta = await call_ai(assistente, req.domanda, auto)

    # log della conversazione
    chat_log = AIChatLog(
        dealer_user_id=assistente.dealer_user_id,
        assistant_id=assistente.id,
        slug=slug,
        sorgente="web",
        utente_ref="session",  # TODO: qui puoi mettere l’ID utente o sessione
        domanda=req.domanda,
        risposta=risposta
    )
    db.add(chat_log)
    db.commit()

    return ChatResponse(
        risposta=risposta,
        auto_riferite=[a["id"] for a in auto]
    )
