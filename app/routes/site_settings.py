from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import SiteAdminSettings, User, NltOfferte, NltQuotazioni, SmtpSettings

from pydantic import BaseModel
from app.auth_helpers import get_admin_id, get_dealer_id, is_admin_user, is_dealer_user
import re, unidecode
from supabase import create_client, Client
import uuid, os
from dotenv import load_dotenv
from datetime import datetime
from fastapi_jwt_auth import AuthJWT



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
        raise HTTPException(status_code=403, detail="Non autorizzato")

    admin_id = get_admin_id(user)  # ✅ sempre riferito all'admin principale

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

    # Usa get_admin_id per assicurare sempre riferimento all'admin principale
    admin_id = get_admin_id(current_user)

    # Verifica se esistono già settings per admin_id
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.admin_id == admin_id).first()

    # Se non fornisce slug, lo genero automaticamente
    if not payload.slug:
        payload.slug = generate_slug(current_user.ragione_sociale)
        # Controllo unicità slug
        existing_slug = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == payload.slug).first()
        counter = 1
        base_slug = payload.slug
        while existing_slug:
            payload.slug = f"{base_slug}-{counter}"
            existing_slug = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == payload.slug).first()
            counter += 1
    else:
        # Controlla manualmente unicità dello slug fornito
        existing_slug = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.slug == payload.slug, 
            SiteAdminSettings.admin_id != admin_id
        ).first()
        if existing_slug:
            raise HTTPException(status_code=409, detail="Slug già in uso")

    if settings:
        # Aggiorna impostazioni esistenti
        for key, value in payload.dict(exclude_unset=True).items():
            setattr(settings, key, value)
    else:
        # Crea nuove impostazioni
        settings = SiteAdminSettings(admin_id=admin_id, **payload.dict())

    db.add(settings)
    db.commit()
    db.refresh(settings)

    return {
        "status": "success",
        "slug": settings.slug,
        "id": settings.id
    }

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

    admin_id = get_admin_id(current_user)

    allowed_extensions = {"png", "jpg", "jpeg", "webp"}
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Formato file non valido!")

    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande! Dimensione massima: 5MB.")

    # Caricamento file su Supabase
    try:
        file_name = f"{admin_id}/{uuid.uuid4()}_{file.filename}"
        response = supabase.storage.from_(SUPABASE_BUCKET_LOGO_WEB).upload(
            file_name, file_content, {"content-type": file.content_type}
        )
        logo_web_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET_LOGO_WEB}/{file_name}"

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore upload file: {str(e)}")

    # Aggiornamento automatico della tabella
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.admin_id == admin_id).first()

    if not settings:
        settings = SiteAdminSettings(admin_id=admin_id, logo_web=logo_web_url)
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

    admin_id = get_admin_id(current_user)

    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.admin_id == admin_id).first()

    # ✅ Creazione automatica impostazioni default se non presenti
    if not settings:
        mese_corrente = datetime.now().strftime('%B %Y').capitalize()

        # Genera titolo predefinito
        meta_title = f"Offerte Noleggio Lungo Termine {mese_corrente} | {current_user.ragione_sociale}"

        # Calcola meta description automatica con due offerte più economiche
        offerte_minime = db.query(NltOfferte, NltQuotazioni).join(
            NltQuotazioni, NltOfferte.id_offerta == NltQuotazioni.id_offerta
        ).filter(
            NltOfferte.id_admin == admin_id,
            NltOfferte.attivo == True,  # ✅ filtro per offerte attive
            NltQuotazioni.mesi_36_10.isnot(None),
            NltOfferte.prezzo_listino.isnot(None)
        ).order_by(NltQuotazioni.mesi_36_10.asc()).limit(2).all()

        descrizioni_auto = []
        for offerta, quotazione in offerte_minime:
            canone_calcolato = float(quotazione.mesi_36_10) - (float(offerta.prezzo_listino) * 0.25 / 36)
            canone_calcolato = round(canone_calcolato, 2)
            descrizioni_auto.append(f"{offerta.marca} {offerta.modello} da {canone_calcolato}€/mese")


        if descrizioni_auto:
            esempi_auto = ", ".join(descrizioni_auto)
            meta_description = (
                f"Scopri tutte le offerte di noleggio lungo termine da {current_user.ragione_sociale}. "
                f"Es. {esempi_auto}. Preventivi immediati online."
            )
        else:
            meta_description = f"Scopri le migliori offerte di noleggio lungo termine da {current_user.ragione_sociale}. Preventivi immediati online."

        # ✅ Crea record di default
        settings = SiteAdminSettings(
            admin_id=admin_id,
            slug=f"{current_user.ragione_sociale.lower().replace(' ', '-')}",
            meta_title=meta_title,
            meta_description=meta_description,
            primary_color="#ffffff",
            secondary_color="#000000",
            tertiary_color="#dddddd",
            font_family="Roboto, sans-serif",
            favicon_url="https://example.com/favicon.ico",
            contact_email=current_user.email,
            contact_phone=current_user.cellulare,
            contact_address=f"{current_user.indirizzo}, {current_user.cap} {current_user.citta}",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(settings)
        db.commit()
        db.refresh(settings)

    # Restituisci sempre il record (appena creato o già presente)
    
    return {
        "primary_color": settings.primary_color,
        "secondary_color": settings.secondary_color,
        "tertiary_color": settings.tertiary_color,
        "font_family": settings.font_family,
        "favicon_url": settings.favicon_url,
        "meta_title": settings.meta_title,
        "meta_description": settings.meta_description,
        "logo_web": settings.logo_web,
        "contact_email": settings.contact_email,
        "contact_phone": settings.contact_phone,
        "contact_address": settings.contact_address,
        "slug": settings.slug,
        "custom_css": settings.custom_css,
        "custom_js": settings.custom_js,
        "dark_mode_enabled": settings.dark_mode_enabled,
        "menu_style": settings.menu_style,
        "footer_text": settings.footer_text,
        "created_at": settings.created_at,
        "updated_at": settings.updated_at
    }

@router.get("/site-settings-public/{slug}")
async def get_site_settings_public(
    slug: str, 
    db: Session = Depends(get_db)
):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()

    if not settings:
        raise HTTPException(status_code=404, detail="Impostazioni non trovate.")

     return {
        "primary_color": settings.primary_color or "#ffffff",
        "secondary_color": settings.secondary_color or "#000000",
        "tertiary_color": settings.tertiary_color or "#dddddd",
        "font_family": settings.font_family or "Roboto, sans-serif",
        "favicon_url": settings.favicon_url or "",
        "meta_title": settings.meta_title or "",
        "meta_description": settings.meta_description or "",
        "logo_web": settings.logo_web or "/images/logo-default.png",
        "footer_text": settings.footer_text or "",
        "contact_email": settings.contact_email or "info@tuodominio.it",
        "contact_phone": settings.contact_phone or "+39 000 0000000",
        "contact_address": settings.contact_address or "Indirizzo non configurato",
        "dark_mode_enabled": settings.dark_mode_enabled or False,
        "custom_css": settings.custom_css or "",
        "custom_js": settings.custom_js or ""
    }

