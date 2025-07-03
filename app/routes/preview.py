from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db  # ✅ usa il tuo import corretto
from app.models import SiteAdminSettings  # ✅ path corretto al model

router = APIRouter()

@router.get("/vetrina-offerte/{slug}", response_class=HTMLResponse)
async def meta_preview(slug: str, request: Request, db: Session = Depends(get_db)):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()

    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer con slug '{slug}' non trovato.")

    # Meta content con fallback
    og_title = settings.meta_title or f"Offerte Noleggio Lungo Termine – {slug}"
    og_description = settings.meta_description or "Scopri le offerte di noleggio a lungo termine disponibili."
    og_image = settings.logo_web or "https://www.nlt.rent/assets/logo-default.jpg"
    page_url = f"https://www.nlt.rent/vetrina-offerte/{slug}"

    # Rilevamento bot social
    user_agent = request.headers.get("user-agent", "").lower()
    bot_keywords = ["facebook", "whatsapp", "twitterbot", "linkedin", "telegram", "slackbot", "discord", "googlebot"]
    is_bot = any(bot in user_agent for bot in bot_keywords)

    if not is_bot:
        return RedirectResponse(url=page_url)

    html = f"""
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <title>{og_title}</title>
        <meta property="og:title" content="{og_title}" />
        <meta property="og:description" content="{og_description}" />
        <meta property="og:image" content="{og_image}" />
        <meta property="og:url" content="{request.url}" />
        <meta property="og:type" content="website" />
        <meta http-equiv="refresh" content="2; URL={page_url}" />
    </head>
    <body>
        <p>Redirecting to <a href="{page_url}">{page_url}</a>...</p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
