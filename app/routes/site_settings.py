from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import SmtpSettings, User, SiteAdminSettings
from pydantic import BaseModel
from app.auth_helpers import get_admin_id, get_dealer_id, is_admin_user, is_dealer_user
import re, unidecode
from supabase import create_client
import uuid, os



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

# Inizializza Supabase Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET_LOGO_WEB")

supabase = create_client(SUPABASE_URL, SUPABASE_API_KEY)

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

    # Ottieni il file e definisci il percorso unico
    file_content = await file.read()
    file_extension = file.filename.split(".")[-1].lower()
    filename = f"{uuid.uuid4()}.{file_extension}"

    storage_path = f"{admin_id}/{filename}"  # usa cartelle distinte per ogni admin

    # Carica file in Supabase
    response = supabase.storage.from_(SUPABASE_BUCKET).upload(storage_path, file_content, {"content-type": file.content_type})

    if response.status_code != 200 and response.status_code != 201:
        raise HTTPException(status_code=500, detail="Errore upload file su Supabase")

    # URL pubblico del file
    public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(storage_path)

    # Aggiorna campo logo_web nel DB
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.admin_id == admin_id).first()

    if not settings:
        # Se non ci sono impostazioni, creale
        settings = SiteAdminSettings(admin_id=admin_id, logo_web=public_url)
        db.add(settings)
    else:
        settings.logo_web = public_url

    db.commit()
    db.refresh(settings)

    return {
        "status": "success",
        "logo_web": public_url
    }