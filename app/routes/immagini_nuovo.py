from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

from app.database import get_db
from app.models import MnetModelli, MnetModelliAIFoto
from app.routes.modelli_ai_test import SCENARIO_PROMPTS  # riuso i prompt solo per validare scenario

router = APIRouter(
    prefix="/img",
    tags=["Immagini Nuovo"]
)

@router.get("/nuovo/modelli/{marca}/{scenario}")
async def get_immagini_nuovo_modelli(
    marca: str,
    scenario: str,
    db: Session = Depends(get_db)
):
    scenario = scenario.lower().strip()
    if scenario not in SCENARIO_PROMPTS:
        raise HTTPException(422, f"Scenario non valido: {scenario}")

    results = (
        db.query(MnetModelliAIFoto)
        .join(MnetModelli, MnetModelliAIFoto.codice_modello == MnetModelli.codice_modello)
        .filter(
            MnetModelli.marca_acronimo == marca.upper(),
            MnetModelliAIFoto.scenario == scenario,
            MnetModelliAIFoto.ai_foto_url.isnot(None)
        )
        .all()
    )

    return [
        {
            "codice_modello": foto.codice_modello,
            "descrizione": foto.modello.descrizione,
            "scenario": foto.scenario,
            "url": foto.ai_foto_url
        }
        for foto in results
    ]
