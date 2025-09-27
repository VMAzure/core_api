from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import SiteAdminSettings, User, NltOfferte, NltQuotazioni, SmtpSettings

from pydantic import BaseModel
from app.auth_helpers import get_admin_id, get_dealer_id, is_admin_user, is_dealer_user, get_settings_owner_id
import re, unidecode
from supabase import create_client, Client
import uuid, os
from dotenv import load_dotenv
from datetime import datetime
from fastapi_jwt_auth import AuthJWT

import httpx
import os

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

async def resolve_place_id(query: str) -> str | None:
    if not GOOGLE_API_KEY or not query:
        return None

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.id"
    }
    payload = { "textQuery": query }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(url, headers=headers, json=payload)
            res.raise_for_status()
            data = res.json()
            places = data.get("places", [])
            if places:
                return places[0]["id"]  # ✅ il nuovo place_id
    except Exception as e:
        logger.warning(f"⚠️ Errore resolve_place_id (v1): {e}")

    return None


router = APIRouter()



class SMTPSettingsSchema(BaseModel):
    smtp_host: str
    smtp_port: int
    use_ssl: bool
    smtp_user: str
    smtp_password: str

@router.post("/smtp-settings")
async def set_smtp_settings(
    settings: SMTPSettingsSchema,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user or not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Accesso consentito solo agli Admin")

    admin_id = user.id  # Solo admin.id

    existing_settings = db.query(SmtpSettings).filter(SmtpSettings.admin_id == admin_id).first()

    if existing_settings:
        existing_settings.smtp_host = settings.smtp_host
        existing_settings.smtp_port = settings.smtp_port
        existing_settings.use_ssl = settings.use_ssl
        existing_settings.smtp_user = settings.smtp_user
        existing_settings.smtp_password = settings.smtp_password
    else:
        new_settings = SmtpSettings(
            admin_id=admin_id,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            use_ssl=settings.use_ssl,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password
        )
        db.add(new_settings)

    db.commit()

    return {"success": True, "message": "Impostazioni SMTP salvate con successo."}

@router.get("/smtp-settings", response_model=SMTPSettingsSchema)
async def get_smtp_settings(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user or not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    admin_id = get_admin_id(user)

    settings = db.query(SmtpSettings).filter(SmtpSettings.admin_id == admin_id).first()
    if not settings:
        raise HTTPException(status_code=404, detail="Impostazioni SMTP non trovate")

    return settings



# Schema Pydantic per la validazione del payload
class SiteSettingsPayload(BaseModel):
    primary_color: str = None
    secondary_color: str = None
    tertiary_color: str = None
    font_family: str = None
    favicon_url: str = None
    custom_css: str = None
    custom_js: str = None
    dark_mode_enabled: bool = False
    menu_style: str = None
    footer_text: str = None
    meta_title: str = None
    meta_description: str = None
    logo_web: str = None
    contact_email: str = None
    contact_phone: str = None
    contact_address: str = None
    slug: str = None
    prov_vetrina: int = None
    site_url: str = None  # 👈 aggiunto
    facebook_url: str = None
    instagram_url: str = None
    tiktok_url: str = None
    linkedin_url: str = None
    whatsapp_url: str = None
    x_url: str = None
    youtube_url: str = None
    telegram_url: str = None

    chi_siamo: str = None

    hero_image_url: str = None
    hero_title: str = None
    hero_subtitle: str = None
    hero_video_url: str = None
    hero_video_poster: str = None
    servizi_dettaglio: dict = None
    claim_hero: str = None
    subclaim_hero: str = None

    servizi_visibili: dict = {
        "NLT": False,
        "REWIND": False,
        "NOS": False,
        "NBT": False
    }

# Funzione helper per generare slug
def generate_slug(text: str):
    slug = unidecode.unidecode(text).lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    return slug

@router.post("/site-settings")
async def create_or_update_site_settings(
    payload: SiteSettingsPayload,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == user_email).first()

    if not current_user or not (is_admin_user(current_user) or is_dealer_user(current_user)):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    # Determina se Admin o Dealer
    if is_admin_user(current_user):
        settings = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == current_user.id,
            SiteAdminSettings.dealer_id == None
        ).first()
    else:  # dealer
        admin_id = get_admin_id(current_user)
        settings = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == admin_id,
            SiteAdminSettings.dealer_id == current_user.id
        ).first()

    # gestione slug
    if settings:  # record esistente
        if payload.slug and payload.slug != settings.slug:
            # utente vuole cambiare slug -> controlla unicità
            existing_slug = db.query(SiteAdminSettings).filter(
                SiteAdminSettings.slug == payload.slug,
                SiteAdminSettings.id != settings.id
            ).first()
            if existing_slug:
                raise HTTPException(status_code=409, detail="Slug già in uso")
            settings.slug = payload.slug  # assegna nuovo slug
        # se payload.slug è vuoto o uguale, non toccare lo slug esistente
    else:  # nuovo record
        if not payload.slug:
            # genera slug da ragione sociale
            payload.slug = generate_slug(current_user.ragione_sociale)
            existing_slug = db.query(SiteAdminSettings).filter(
                SiteAdminSettings.slug == payload.slug
            ).first()
            counter = 1
            base_slug = payload.slug
            while existing_slug:
                payload.slug = f"{base_slug}-{counter}"
                existing_slug = db.query(SiteAdminSettings).filter(
                    SiteAdminSettings.slug == payload.slug
                ).first()
                counter += 1
        else:
            # payload.slug già presente -> verifica unicità
            existing_slug = db.query(SiteAdminSettings).filter(
                SiteAdminSettings.slug == payload.slug
            ).first()
            if existing_slug:
                raise HTTPException(status_code=409, detail="Slug già in uso")

    data = payload.dict(exclude_unset=True)
    if data.get("prov_vetrina") is None:
        data["prov_vetrina"] = 4

        # Aggiungi/ricalcola Google Place ID solo se non presente
    if not settings or not settings.google_place_id:
        query = payload.ragione_sociale or payload.contact_address
        place_id = await resolve_place_id(query)
        if place_id:
            data["google_place_id"] = place_id

    if settings:
        for key, value in data.items():
            setattr(settings, key, value)
    else:
        if is_admin_user(current_user):
            settings = SiteAdminSettings(
                admin_id=current_user.id,
                dealer_id=None,
                **data
            )
        else:
            settings = SiteAdminSettings(
                admin_id=get_admin_id(current_user),
                dealer_id=current_user.id,
                **data
            )
        db.add(settings)

    db.commit()
    db.refresh(settings)

    return {"status": "success", "slug": settings.slug, "id": settings.id}



if os.getenv("ENV") != "production":
    load_dotenv()

# Variabili ambiente Supabase già configurate e funzionanti
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET_LOGO_WEB = "logo-web"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@router.post("/site-settings/logo-web")
async def upload_logo_web(
    file: UploadFile = File(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == user_email).first()

    if not current_user or not (is_admin_user(current_user) or is_dealer_user(current_user)):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    # Verifica formato file
    allowed_extensions = {"png", "jpg", "jpeg", "webp"}
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Formato file non valido!")

    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande! Dimensione massima: 5MB.")

    # Caricamento su Supabase
    owner_id = get_settings_owner_id(current_user)
    file_name = f"{owner_id}/{uuid.uuid4()}_{file.filename}"
    try:
        supabase.storage.from_(SUPABASE_BUCKET_LOGO_WEB).upload(
            file_name, file_content, {"content-type": file.content_type}
        )
        logo_web_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET_LOGO_WEB}/{file_name}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore upload file: {str(e)}")

    # Recupera/imposta settings corretti (admin o dealer)
    if is_admin_user(current_user):
        settings = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == current_user.id,
            SiteAdminSettings.dealer_id == None
        ).first()
    else:
        settings = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == get_admin_id(current_user),
            SiteAdminSettings.dealer_id == current_user.id
        ).first()

    # Se non esiste, crea nuovo record
    if not settings:
        settings = SiteAdminSettings(
            admin_id=current_user.id if is_admin_user(current_user) else get_admin_id(current_user),
            dealer_id=None if is_admin_user(current_user) else current_user.id,
            logo_web=logo_web_url
        )
        db.add(settings)
    else:
        settings.logo_web = logo_web_url

    db.commit()
    db.refresh(settings)

    return {
        "status": "success",
        "logo_web": logo_web_url
    }


import logging

logger = logging.getLogger(__name__)

@router.post("/site-settings/hero-video")
async def upload_hero_video(
    file: UploadFile = File(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == user_email).first()

    if not current_user or not (is_admin_user(current_user) or is_dealer_user(current_user)):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    # ✅ Verifica tipo file
    allowed_extensions = {"mp4"}
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Sono accettati solo file .mp4")

    file_content = await file.read()
    if len(file_content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande (max 50MB)")

    BUCKET_NAME = "hero-video"
    owner_id = get_settings_owner_id(current_user)
    file_name = f"{owner_id}/{uuid.uuid4()}_{file.filename}"

    try:
        supabase.storage.from_(BUCKET_NAME).upload(
            file_name, file_content, { "content-type": file.content_type }
        )
        video_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{file_name}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore upload: {str(e)}")

    return {
        "status": "success",
        "hero_video_url": video_url
    }


@router.get("/calcola_canone/{id_offerta}")
def calcola_canone(id_offerta: int, db: Session = Depends(get_db)):
    offerta = db.query(NltOfferte).filter(NltOfferte.id_offerta == id_offerta).first()

    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata")

    quotazioni = db.query(NltQuotazioni).filter(
        NltQuotazioni.id_offerta == offerta.id_offerta
    ).all()

    risultati = []

    for quotazione in quotazioni:
        if quotazione.mesi_36_10 is not None and offerta.prezzo_listino is not None:
            anticipo = float(offerta.prezzo_listino) * 0.25
            canone_calcolato = float(quotazione.mesi_36_10) - (anticipo / 36)
            risultati.append({
                "id_quotazione": quotazione.id_quotazione,
                "canone_calcolato": round(canone_calcolato, 2)
            })
        else:
            logger.info(
                f"Quotazione saltata (id={quotazione.id_quotazione}, mesi_36_10={quotazione.mesi_36_10}, prezzo_listino={offerta.prezzo_listino})"
            )

    return {"id_offerta": id_offerta, "quotazioni_calcolate": risultati}

@router.get("/site-settings")
async def get_site_settings(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == user_email).first()

    if not current_user or not (is_admin_user(current_user) or is_dealer_user(current_user)):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    if is_admin_user(current_user):
        admin_id = current_user.id
        dealer_id = None
    else:
        admin_id = get_admin_id(current_user)
        dealer_id = current_user.id

    settings = db.query(SiteAdminSettings).filter(
        SiteAdminSettings.admin_id == admin_id,
        SiteAdminSettings.dealer_id == dealer_id
    ).first()

    # Se mancano, crea impostazioni di default
    if not settings:
        mese_corrente = datetime.now().strftime('%B %Y').capitalize()
        new_slug = generate_slug(current_user.ragione_sociale)
        settings = SiteAdminSettings(
            admin_id=current_user.id if is_admin_user(current_user) else admin_id,
            dealer_id=None if is_admin_user(current_user) else current_user.id,
            slug=new_slug,
            meta_title=f"Offerte Noleggio Lungo Termine {mese_corrente} | {current_user.ragione_sociale}",
            meta_description=f"Scopri le migliori offerte di noleggio lungo termine da {current_user.ragione_sociale}.",
            primary_color="#ffffff",
            secondary_color="#000000",
            tertiary_color="#dddddd",
            font_family="Roboto, sans-serif",
            favicon_url="https://example.com/favicon.ico",
            contact_email=current_user.email,
            contact_phone=current_user.cellulare,

            site_url="https://www.azureautomotive.it",
            contact_address=f"{current_user.indirizzo}, {current_user.cap} {current_user.citta}",
            servizi_visibili={
                "NLT": False, "REWIND": False, "NOS": False, "NBT": False
            },
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(settings)
        db.commit()
        db.refresh(settings)

    # Dati anagrafici dell’utente per uniformità con /me
    nome = current_user.nome
    cognome = current_user.cognome
    ragione_sociale = current_user.ragione_sociale or f"{nome} {cognome}"
    email = current_user.email

    return {
        "primary_color": settings.primary_color or "",
        "secondary_color": settings.secondary_color or "",
        "tertiary_color": settings.tertiary_color or "",
        "font_family": settings.font_family or "",
        "favicon_url": settings.favicon_url or "",
        "meta_title": settings.meta_title or "",
        "meta_description": settings.meta_description or "",
        "logo_web": settings.logo_web or "",
        "footer_text": settings.footer_text or "",
        "dark_mode_enabled": settings.dark_mode_enabled if settings.dark_mode_enabled is not None else False,
        "custom_css": settings.custom_css or "",
        "custom_js": settings.custom_js or "",
        "contact_email": settings.contact_email or "",
        "contact_phone": settings.contact_phone or "",
        "contact_address": settings.contact_address or "",
        "slug": settings.slug or "",
        "menu_style": settings.menu_style or "",
        "created_at": settings.created_at,
        "updated_at": settings.updated_at,
        "prov_vetrina": settings.prov_vetrina,
        "site_url": settings.site_url or "",
        "servizi_visibili": settings.servizi_visibili or {
            "NLT": False, "REWIND": False, "NOS": False, "NBT": False
        },
        "nome": nome,
        "cognome": cognome,
        "ragione_sociale": ragione_sociale,
        "email": email,
        "facebook_url": settings.facebook_url or "",
        "instagram_url": settings.instagram_url or "",
        "tiktok_url": settings.tiktok_url or "",
        "linkedin_url": settings.linkedin_url or "",
        "whatsapp_url": settings.whatsapp_url or "",
        "x_url": settings.x_url or "",
        "youtube_url": settings.youtube_url or "",
        "telegram_url": settings.telegram_url or "",
        "chi_siamo": settings.chi_siamo or "",
        "hero_image_url": settings.hero_image_url or "",
        "hero_title": settings.hero_title or "",
        "hero_subtitle": settings.hero_subtitle or "",
        "hero_video_url": settings.hero_video_url or "",
        "hero_video_poster": settings.hero_video_poster or "",
        "servizi_dettaglio": settings.servizi_dettaglio or {},
        "claim_hero": settings.claim_hero or "",
        "subclaim_hero": settings.subclaim_hero or "",





    }



@router.get("/site-settings-public/{slug}")
async def get_site_settings_public(slug: str, db: Session = Depends(get_db)):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Slug '{slug}' non trovato.")

    admin_user = db.query(User).filter(User.id == settings.admin_id).first()
    dealer_user = db.query(User).filter(User.id == settings.dealer_id).first() if settings.dealer_id else None
    visible_user = dealer_user or admin_user

    contact_email = settings.contact_email or (admin_user.email if admin_user else "")
    contact_phone = settings.contact_phone or (admin_user.cellulare if admin_user else "")
    contact_address = settings.contact_address or (
        f"{admin_user.indirizzo}, {admin_user.cap} {admin_user.citta}" if admin_user else ""
    )

    return {
        "primary_color": settings.primary_color or "",
        "secondary_color": settings.secondary_color or "",
        "tertiary_color": settings.tertiary_color or "",
        "font_family": settings.font_family or "",
        "favicon_url": settings.favicon_url or "",
        "meta_title": settings.meta_title or "",
        "meta_description": settings.meta_description or "",
        "logo_web": settings.logo_web or "",
        "footer_text": settings.footer_text or "",
        "dark_mode_enabled": settings.dark_mode_enabled if settings.dark_mode_enabled is not None else False,
        "custom_css": settings.custom_css or "",
        "custom_js": settings.custom_js or "",
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "contact_address": contact_address,
        "site_url": settings.site_url or "",
        "servizi_visibili": settings.servizi_visibili or {
            "NLT": False, "REWIND": False, "NOS": False, "NBT": False
        },
        "facebook_url": settings.facebook_url or "",
        "instagram_url": settings.instagram_url or "",
        "tiktok_url": settings.tiktok_url or "",
        "linkedin_url": settings.linkedin_url or "",
        "whatsapp_url": settings.whatsapp_url or "",
        "x_url": settings.x_url or "",
        "youtube_url": settings.youtube_url or "",
        "telegram_url": settings.telegram_url or "",
        "chi_siamo": settings.chi_siamo or "",
        "hero_image_url": settings.hero_image_url or "",
        "hero_title": settings.hero_title or "",
        "hero_subtitle": settings.hero_subtitle or "",
        "hero_video_url": settings.hero_video_url or "",
        "hero_video_poster": settings.hero_video_poster or "",
        "servizi_dettaglio": settings.servizi_dettaglio or {},
        "claim_hero": settings.claim_hero or "",
        "subclaim_hero": settings.subclaim_hero or "",
        "avatar_url": (visible_user.avatar_url if visible_user else "") or "", 
        "google_place_id": settings.google_place_id or "",
        "agency_type": settings.prov_vetrina or 0  

    }

@router.post("/site-settings/hero-image")
async def upload_hero_image(
    file: UploadFile = File(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == user_email).first()

    if not current_user or not (is_admin_user(current_user) or is_dealer_user(current_user)):
        raise HTTPException(status_code=403, detail="Non autorizzato")

    # Estensione valida
    allowed_extensions = {"png", "jpg", "jpeg", "webp"}
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Formato file non valido!")

    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande! Massimo 5MB.")

    # Supabase Upload
    HERO_BUCKET = "hero-banner"
    owner_id = get_settings_owner_id(current_user)
    file_name = f"{owner_id}/{uuid.uuid4()}_{file.filename}"

    try:
        supabase.storage.from_(HERO_BUCKET).upload(
            file_name, file_content, {"content-type": file.content_type}
        )
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/{HERO_BUCKET}/{file_name}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore upload: {str(e)}")

    # Recupera settings
    settings = db.query(SiteAdminSettings).filter(
        SiteAdminSettings.admin_id == get_admin_id(current_user),
        SiteAdminSettings.dealer_id == (None if is_admin_user(current_user) else current_user.id)
    ).first()

    if not settings:
        settings = SiteAdminSettings(
            admin_id=get_admin_id(current_user),
            dealer_id=None if is_admin_user(current_user) else current_user.id,
            hero_image_url=image_url
        )
        db.add(settings)
    else:
        settings.hero_image_url = image_url

    db.commit()
    db.refresh(settings)

    return {
        "status": "success",
        "hero_image_url": image_url
    }

@router.post("/site-settings/servizi-image")
async def upload_servizio_image(
    servizio: str,
    file: UploadFile = File(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    current_user = db.query(User).filter(User.email == user_email).first()

    if not current_user:
        raise HTTPException(status_code=403, detail="Non autorizzato")

    allowed_extensions = {"jpg", "jpeg", "png", "webp"}
    file_ext = file.filename.split(".")[-1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Formato immagine non valido!")

    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande! Max 5MB.")

    BUCKET = "servizi"
    owner_id = get_settings_owner_id(current_user)
    file_name = f"{owner_id}/{servizio}_{uuid.uuid4()}.{file_ext}"

    try:
        supabase.storage.from_(BUCKET).upload(
            file_name, file_content, {"content-type": file.content_type}
        )
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{file_name}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore upload immagine: {str(e)}")

    return {
        "status": "success",
        "image_url": image_url
    }

@router.get("/site-settings-public/{slug}/recensioni")
async def get_google_reviews(slug: str, db: Session = Depends(get_db)):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings or not settings.google_place_id:
        raise HTTPException(status_code=404, detail="Dealer o place_id non trovato")

    place_id = settings.google_place_id
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": (
            "rating,userRatingCount,"
            "reviews.rating,"
            "reviews.relativePublishTimeDescription,"
            "reviews.authorAttribution.displayName,"
            "reviews.authorAttribution.photoUri,"
            "reviews.authorAttribution.uri,"
            "reviews.text"
        )
    }
    params = {
        "languageCode": "it",
        "reviewsSort": "NEWEST"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json()
    except Exception as e:
        logger.warning(f"⚠️ Google Reviews error: {e}")
        raise HTTPException(status_code=502, detail="Errore nel recupero recensioni da Google")

    avg = data.get("rating", 0)
    tot = data.get("userRatingCount", 0)
    raw = (data.get("reviews") or [])[:5]

    reviews = []
    for r in raw:
        # text può essere dict (v1) oppure stringa (fallback future-proof)
        text_raw = r.get("text")
        if isinstance(text_raw, dict):
            txt = (text_raw.get("text") or "").strip()
        elif isinstance(text_raw, str):
            txt = text_raw.strip()
        else:
            txt = ""

        if not txt:
            continue

        author = r.get("authorAttribution") or {}
        reviews.append({
            "author": author.get("displayName") or "Utente",
            "photo": author.get("photoUri"),
            "profile_url": author.get("uri"),
            "rating": r.get("rating"),
            "text": txt,
            "published": r.get("relativePublishTimeDescription") or ""
        })

    return {
        "place_id": place_id,
        "rating": avg,
        "total_reviews": tot,
        "total_textual": len(reviews),
        "reviews": reviews
    }
