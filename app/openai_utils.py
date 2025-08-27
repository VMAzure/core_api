# app/openai_utils.py

from openai import AsyncOpenAI
from fastapi import HTTPException
import os

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def genera_descrizione_gpt(prompt: str, max_tokens: int = 300):
    max_tokens = min(max_tokens, 1000)  # ⬅️ Limite soft lato backend
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ GPT error:", e)
        raise HTTPException(status_code=500, detail="Errore generazione testo GPT.")

