# app/openai_utils.py

from openai import AsyncOpenAI
from fastapi import HTTPException
import os

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def genera_descrizione_gpt(
    prompt: str,
    max_tokens: int = 300,
    model: str = "gpt-4o",
    temperature: float = 0.4,
    web_research: bool = False
):
    max_tokens = min(max_tokens, 1000)  # soft limit

    try:
        kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        if web_research:
            if not model.endswith("-search-preview"):
                raise ValueError("web_research richiede un modello search-preview")
            kwargs["web_search_options"] = {}

        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()

    except Exception as e:
        print("❌ GPT error:", e)
        raise HTTPException(status_code=500, detail="Errore generazione testo GPT.")


