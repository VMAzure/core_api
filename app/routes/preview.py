from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import SiteAdminSettings, User

router = APIRouter()

@router.get("/vetrina-offerte/{slug}", response_class=HTMLResponse)
async def meta_preview(slug: str, request: Request, db: Session = Depends(get_db)):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer con slug '{slug}' non trovato.")

    # 🔹 Recupera ragione sociale del dealer
    dealer_name = slug
    if settings.dealer_id:
        dealer = db.query(User).filter(User.id == settings.dealer_id).first()
        if dealer and dealer.ragione_sociale:
            dealer_name = dealer.ragione_sociale

    # 🔹 Parametri dalla query string
    query = request.query_params
    marca = query.get("marca", "").capitalize()
    budget = query.get("budget", "")
    segmento = query.get("segmento", "").capitalize()
    tipo = query.get("tipo", "").capitalize()

    # 🔹 Meta tag dinamici
    og_title = f"Offerte Noleggio Lungo Termine | {dealer_name}"

    marca = query.get("marca", "").capitalize()
    segmento = query.get("segmento", "").capitalize()
    budget = query.get("budget", "")
    tipo = query.get("tipo", "").capitalize()

    descrizione_parts = ["Scopri le offerte"]

    if segmento:
        descrizione_parts.append(segmento)
    if marca:
        descrizione_parts.append(marca)
    if tipo:
        descrizione_parts.append(f"per {tipo}")
    if budget:
        descrizione_parts.append(f"da {budget}€/mese")

    descrizione_parts.append(f"su {dealer_name}")

    og_description = " ".join(descrizione_parts)

    og_image = settings.logo_web or "https://nlt.rent/assets/logo-default.jpg"

    # 🔹 Ricostruzione URL di redirect
    query_string = request.url.query
    page_url = f"https://www.nlt.rent/vetrina-offerte/{slug}"
    if query_string:
        page_url += f"?{query_string}"

    # 🔹 Bot detection
    user_agent = request.headers.get("user-agent", "").lower()
    bot_keywords = ["facebook", "whatsapp", "twitterbot", "linkedin", "telegram", "slackbot", "discord", "googlebot"]
    is_bot = any(bot in user_agent for bot in bot_keywords)

    if not is_bot:
        return RedirectResponse(url=page_url)

    # 🔹 HTML con meta tag
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
