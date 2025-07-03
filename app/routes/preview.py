from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import SiteAdminSettings  # importa il tuo modello
import urllib.parse

router = APIRouter()

@router.get("/vetrina-offerte/{slug}", response_class=HTMLResponse)
async def meta_preview(slug: str, request: Request, db: Session = Depends(get_db)):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()

    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer con slug '{slug}' non trovato.")

    nome_dealer = settings.nome_visualizzato or settings.nome or "il tuo dealer"
    logo = settings.logo_web or "https://www.nlt.rent/assets/logo-default.jpg"
    url_vetrina = f"https://www.nlt.rent/vetrina-offerte/{slug}"

    user_agent = request.headers.get("user-agent", "").lower()
    bot_keywords = ["facebook", "whatsapp", "twitterbot", "linkedin", "telegram", "slackbot", "discord", "googlebot"]
    is_bot = any(bot in user_agent for bot in bot_keywords)

    if not is_bot:
        return RedirectResponse(url=url_vetrina)

    html = f"""
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <title>Offerte Noleggio Lungo Termine - {nome_dealer}</title>
        <meta property="og:title" content="Offerte Noleggio Lungo Termine - {nome_dealer}" />
        <meta property="og:description" content="Scopri le offerte di noleggio a lungo termine disponibili con {nome_dealer}." />
        <meta property="og:image" content="{logo}" />
        <meta property="og:url" content="{request.url}" />
        <meta property="og:type" content="website" />
        <meta http-equiv="refresh" content="2; URL={url_vetrina}" />
    </head>
    <body>
        <p>Redirecting to <a href="{url_vetrina}">{url_vetrina}</a>...</p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
