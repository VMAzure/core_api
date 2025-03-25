from fastapi import APIRouter, HTTPException
import httpx
import os


router = APIRouter()

@router.get("/openapi/azienda/{piva}", tags=["OpenAPI"])
async def get_dati_azienda(piva: str):
    try:
        # 🔐 1. Richiesta token (produzione)
        token_url = "https://oauth.openapi.it/token"
        headers_token = {
            "Content-Type": "application/json",
            "x-api-key": os.getenv("OPENAPI_API_KEY")
        }
        body_token = {
            "scopes": ["GET:company.openapi.com/IT-start/*"],
            "ttl": 900
        }

        async with httpx.AsyncClient() as client:
            token_resp = await client.post(token_url, headers=headers_token, json=body_token)
            token_data = token_resp.json()

            if not token_resp.status_code == 200 or not token_data.get("token"):
                raise HTTPException(status_code=500, detail="Errore nel recupero token")

            token = token_data["token"]

            # 🔍 2. Richiesta dati azienda
            azienda_url = f"https://company.openapi.com/IT-start/{piva}"
            headers_azienda = {
                "Content-Type": "application/json",
                "x-api-key": os.getenv("OPENAPI_API_KEY"),
                "Authorization": f"Bearer {token}"
            }

            azienda_resp = await client.get(azienda_url, headers=headers_azienda)

            if azienda_resp.status_code != 200:
                raise HTTPException(status_code=azienda_resp.status_code, detail="Errore dati aziendali")

            return azienda_resp.json()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
