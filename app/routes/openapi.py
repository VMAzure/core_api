from fastapi import APIRouter, HTTPException
import httpx
import os
import traceback

router = APIRouter()

@router.get("/openapi/azienda/{piva}", tags=["OpenAPI"])
async def get_dati_azienda(piva: str):
    try:
        # 🔐 Richiesta token via Basic Auth
        token_url = "https://oauth.openapi.it/token"
        auth = (os.getenv("OPENAPI_USERNAME"), os.getenv("OPENAPI_API_KEY"))

        body_token = {
            "scopes": ["GET:company.openapi.com/IT-start"],
            "ttl": 9900  # ~2h 45min
        }

        async with httpx.AsyncClient() as client:
            token_resp = await client.post(token_url, auth=auth, json=body_token)
            token_data = token_resp.json()

            if token_resp.status_code != 200 or not token_data.get("token"):
                raise HTTPException(status_code=500, detail=f"Errore nel recupero token: {token_data}")

            token = token_data["token"]

            # 📦 Richiesta dati azienda
            azienda_url = f"https://company.openapi.com/IT-start/{piva}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            azienda_resp = await client.get(azienda_url, headers=headers)
            azienda_json = azienda_resp.json()

            if azienda_resp.status_code != 200 or not azienda_json.get("data"):
                raise HTTPException(status_code=azienda_resp.status_code, detail="Errore nei dati aziendali")

            info = azienda_json["data"][0]
            indirizzo = info["address"]["registeredOffice"]

            # ✨ Estraiamo e trasformiamo i dati rilevanti
            payload = {
                "partita_iva": info.get("vatCode"),
                "denominazione": info.get("companyName"),
                "indirizzo": indirizzo.get("streetName"),
                "citta": indirizzo.get("town"),
                "provincia": indirizzo.get("province"),
                "cap": indirizzo.get("zipCode"),
                "regione": indirizzo.get("region", {}).get("description"),
                "stato_attivita": info.get("activityStatus"),
                "data_iscrizione": info.get("registrationDate")
            }

            return {
                "success": True,
                "piva": piva,
                "payload": payload
            }

    except Exception as e:
        print("❌ Errore:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Errore interno durante la richiesta dati aziendali.")
