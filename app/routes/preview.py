from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import NltOfferte, MnetModelli, User, SiteAdminSettings


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
        <meta name="description" content="{og_description}" />
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


@router.get("/offerta/{dealer_slug}/{slug_offerta}", response_class=HTMLResponse)
def preview_offerta(dealer_slug: str, slug_offerta: str, db: Session = Depends(get_db)):
    offerta = db.query(NltOfferte).filter_by(slug=slug_offerta).first()
    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata")

    modello = db.query(MnetModelli).filter_by(codice_modello=offerta.codice_modello).first()
    immagine = modello.default_img if modello and modello.default_img else "https://nlt.rent/assets/logo-default.jpg"

    og_title = f"{offerta.marca} {offerta.modello} - {offerta.versione or ''}".strip()
    alimentazione = offerta.alimentazione or "-"
    cambio = offerta.cambio or "-"
    og_description = f"{cambio}, {alimentazione}. Noleggio a lungo termine."


    redirect_url = f"https://www.nlt.rent/AZURELease/dealer/offerta-noleggio-lungo-termine.html?dealer={dealer_slug}&slug={slug_offerta}"

    html = f"""
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="utf-8" />
        <title>{og_title}</title>

        <!-- Standard SEO meta -->
        <meta name="description" content="{og_description}" />

        <!-- Open Graph -->
        <meta property="og:title" content="{og_title}" />
        <meta property="og:description" content="{og_description}" />
        <meta property="og:image" content="{immagine}" />
        <meta property="og:url" content="{redirect_url}" />
        <meta property="og:type" content="website" />

        <!-- Twitter -->
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content="{og_title}" />
        <meta name="twitter:description" content="{og_description}" />
        <meta name="twitter:image" content="{immagine}" />

        <meta http-equiv="refresh" content="2;url={redirect_url}" />
    </head>
    <body>
        <p>Redirecting to <a href="{redirect_url}">{redirect_url}</a>...</p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
