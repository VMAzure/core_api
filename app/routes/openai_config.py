from fastapi import APIRouter, HTTPException
import openai
import os
import traceback

router = APIRouter()

# Inizializzazione della configurazione OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# funzione riutilizzabile per richiesta GPT-4
async def genera_descrizione_gpt(prompt: str, max_tokens: int = 300):
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=max_tokens
        )

        descrizione_generata = response.choices[0].message.content.strip()
        return descrizione_generata

    except Exception as e:
        print("❌ Errore generazione GPT-4:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Errore generazione testo GPT-4.")

# 📌 Esempio endpoint per testare la chiamata GPT-4
@router.get("/openai/genera-descrizione", tags=["OpenAI"])
async def get_descrizione_auto(marca: str, modello: str):
    prompt = f"Scrivi una breve descrizione coinvolgente e commerciale per un'offerta di noleggio a lungo termine dell'auto {marca} {modello}, evidenziandone caratteristiche, benefici e motivi per sceglierla."
    
    testo_generato = await genera_descrizione_gpt(prompt)

    return {
        "success": True,
        "marca": marca,
        "modello": modello,
        "descrizione_ai": testo_generato
    }
