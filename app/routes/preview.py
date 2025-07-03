from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import SiteAdminSettings, NltOfferte, MnetModelli, User
from random import choice
from PIL import Image, ImageDraw, ImageFont
import requests
import io

router = APIRouter()

@router.get("/vetrina-offerte/{slug}", response_class=HTMLResponse)
async def meta_preview(slug: str, request: Request, db: Session = Depends(get_db)):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer con slug '{slug}' non trovato.")

    # Costruisci nome dealer dinamico
    dealer_name = slug
    if settings.dealer_id:
        dealer = db.query(User).filter(User.id == settings.dealer_id).first()
        if dealer and dealer.ragione_sociale:
            dealer_name = dealer.ragione_sociale

    og_title = f"Offerte Noleggio Lungo Termine | {dealer_name}"
    og_description = settings.meta_description or "Scopri le offerte di noleggio a lungo termine disponibili."

    # Determina admin_id corretto per filtrare offerte
    admin_id = settings.admin_id
    if settings.dealer_id:
        dealer = db.query(User).filter(User.id == settings.dealer_id).first()
        if dealer and dealer.parent_id:
            admin_id = dealer.parent_id
        else:
            admin_id = settings.dealer_id

    offerte = db.query(NltOfferte).filter(
        NltOfferte.id_admin == admin_id,
        NltOfferte.attivo.is_(True),
        NltOfferte.codice_modello.isnot(None)
    ).all()

    offerta_random = None
    if offerte:
        offerta_random = choice(offerte)

    # Og:image: immagine generata con badge
    if offerta_random:
        og_image = f"https://preview.nlt.rent/og-image/{offerta_random.id_offerta}"
    else:
        og_image = settings.logo_web or "https://nlt.rent/assets/logo-default.jpg"

    page_url = f"https://www.nlt.rent/vetrina-offerte/{slug}"

    # Bot detection
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


@router.get("/og-image/{offerta_id}")
def badge_image(offerta_id: int, db: Session = Depends(get_db)):
    offerta = db.query(NltOfferte).filter(NltOfferte.id_offerta == offerta_id).first()
    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata")

    modello = db.query(MnetModelli).filter(MnetModelli.codice_modello == offerta.codice_modello).first()
    if not modello or not modello.default_img:
        raise HTTPException(status_code=404, detail="Modello o immagine non trovati")

    response = requests.get(modello.default_img)
    image = Image.open(io.BytesIO(response.content)).convert("RGBA")

    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", size=40)
    except:
        font = ImageFont.load_default()

    testo = f"{offerta.marca} {offerta.modello} da €{int(offerta.canone_mensile)}"
    x, y = 40, image.height - 90
    draw.rectangle([x, y, image.width - 40, y + 60], fill=(0, 0, 0, 200))
    draw.text((x + 20, y + 15), testo, fill="white", font=font)

    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png")
