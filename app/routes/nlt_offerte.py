from fastapi import APIRouter, Depends, HTTPException, Request, Query, Body
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func

from typing import Optional, List
from app.database import get_db
from app.models import MnetDettagli,NltPneumatici, NltAutoSostitutiva, NltQuotazioni, NltPlayers, NltImmagini,MnetModelli, NltOfferteTag, NltOffertaTag, User, NltOffertaAccessori,SiteAdminSettings, NltOfferte, SmtpSettings, ImmaginiNlt, NltOfferteClick
from app.auth_helpers import is_admin_user, is_dealer_user, get_admin_id, get_dealer_id
from app.routes.nlt import get_current_user  
from datetime import date, datetime
from .motornet import get_motornet_token
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from app.routes.openai_config import genera_descrizione_gpt
from supabase import create_client
import uuid
from PIL import Image
from io import BytesIO
import os
import logging
import unidecode
import re
import requests
import httpx
from app.routes.image import get_vehicle_image
from sqlalchemy import or_
from app.utils.quotazioni import calcola_quotazione, calcola_quotazione_custom
from app.schemas import CanoneRequest
from urllib.parse import urlencode

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


from sqlalchemy.orm import joinedload
from sqlalchemy import not_
from sqlalchemy import select, desc
from datetime import datetime, timedelta


from app.auth_helpers import (
    get_admin_id,
    get_dealer_id,
    is_admin_user,
    is_dealer_user
)

from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


router = APIRouter(
    prefix="/nlt/offerte",
    tags=["nlt-offerte"]
)


def generate_slug(marca: str, modello: str, versione: str) -> str:
    text = f"{marca}-{modello}-{versione}"
    text = unidecode.unidecode(text.lower())  # elimina accenti
    text = re.sub(r'[^a-z0-9]+', '-', text)   # sostituisce spazi e simboli con "-"
    return text.strip('-')

def generate_unique_slug(marca: str, modello: str, versione: str, db: Session) -> str:
    base_slug = generate_slug(marca, modello, versione)
    slug = base_slug
    counter = 1

    while db.query(NltOfferte).filter(NltOfferte.slug == slug).first() is not None:
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug



# Verifica ruolo admin o superadmin per inserire/modificare
def verify_admin_or_superadmin(user: User):
    if user.role not in ['admin', 'superadmin']:
        raise HTTPException(status_code=403, detail="Permessi insufficienti.")

# ✅ GET Offerte disponibili (dealer vede le offerte del proprio admin, admin le proprie, superadmin tutte)
from sqlalchemy.orm import selectinload

@router.get("/")
async def get_offerte(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    attivo: Optional[bool] = Query(None)
):
    try:
        query = db.query(NltOfferte).options(
            selectinload(NltOfferte.accessori),
            selectinload(NltOfferte.tags),
            selectinload(NltOfferte.quotazioni),
            selectinload(NltOfferte.immagini),
            selectinload(NltOfferte.player),
            selectinload(NltOfferte.immagini_nlt)
        )

        if attivo is None:
            query = query.filter(NltOfferte.attivo.is_(True))
        else:
            query = query.filter(NltOfferte.attivo == attivo)

        if current_user.role == "superadmin":
            pass
        else:
            admin_id = get_admin_id(current_user)
            query = query.filter(NltOfferte.id_admin == admin_id)

        offerte = query.order_by(NltOfferte.prezzo_listino.asc()).all()

        settings_admin = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == admin_id,
            SiteAdminSettings.dealer_id.is_(None)
        ).first()

        prov_admin = float(settings_admin.prov_vetrina or 0)
        slug_admin = settings_admin.slug
        prov_dealer = 0.0
        slug_dealer = slug_admin

        if is_dealer_user(current_user):
            settings_dealer = db.query(SiteAdminSettings).filter(
                SiteAdminSettings.admin_id == admin_id,
                SiteAdminSettings.dealer_id == current_user.id
            ).first()
            if settings_dealer:
                prov_dealer = float(settings_dealer.prov_vetrina or 0)
                slug_dealer = settings_dealer.slug or slug_admin

        risultati = []
        for o in offerte:
            quotazioni_calcolate = {}

            for quotazione in o.quotazioni:
                combinazioni = {
                    "36_10": quotazione.mesi_36_10,
                    "36_15": quotazione.mesi_36_15,
                    "36_20": quotazione.mesi_36_20,
                    "36_25": quotazione.mesi_36_25,
                    "36_30": quotazione.mesi_36_30,
                    "36_40": quotazione.mesi_36_40,
                    "48_10": quotazione.mesi_48_10,
                    "48_15": quotazione.mesi_48_15,
                    "48_20": quotazione.mesi_48_20,
                    "48_25": quotazione.mesi_48_25,
                    "48_30": quotazione.mesi_48_30,
                    "48_40": quotazione.mesi_48_40,
                    "60_10": quotazione.mesi_60_10,
                    "60_15": quotazione.mesi_60_15,
                    "60_20": quotazione.mesi_60_20,
                    "60_25": quotazione.mesi_60_25,
                    "60_30": quotazione.mesi_60_30,
                    "60_40": quotazione.mesi_60_40,
                }

                for durata_km, canone_base in combinazioni.items():
                    if canone_base:
                        quotazioni_calcolate[durata_km] = round(float(canone_base), 2)


            risultati.append({
                "id_offerta": o.id_offerta,
                "slug_offerta": o.slug,
                "marca": o.marca,
                "modello": o.modello,
                "versione": o.versione,
                "codice_motornet": o.codice_motornet,
                "codice_modello": o.codice_modello,
                "id_player": o.id_player,
                "player": {
                    "nome": o.player.nome,
                    "colore": o.player.colore
                } if o.player else None,
                "alimentazione": o.alimentazione,
                "cambio": o.cambio,
                "segmento": o.segmento,
                "descrizione_breve": o.descrizione_breve,
                "valido_da": o.valido_da,
                "valido_fino": o.valido_fino,
                "prezzo_listino": o.prezzo_listino,
                "prezzo_accessori": o.prezzo_accessori,
                "prezzo_mss": o.prezzo_mss,
                "prezzo_totale": o.prezzo_totale,
                "default_img": o.default_img,
                "solo_privati": o.solo_privati,
                "attivo": o.attivo,
                "dealer_slug": slug_dealer,
                "quotazioni": quotazioni_calcolate,
                "accessori": [
                    {"codice": a.codice, "descrizione": a.descrizione, "prezzo": float(a.prezzo)} for a in o.accessori
                ],
                "tags": [
                    {"id_tag": t.id_tag, "nome": t.nome, "fa_icon": t.fa_icon, "colore": t.colore} for t in o.tags
                ],
                "immagine": next((img.url_imagin for img in o.immagini if img.principale), None),
                "immagine_front": o.immagini_nlt.url_immagine_front_alt if o.immagini_nlt else None,
                "immagine_back": o.immagini_nlt.url_immagine_back_alt if o.immagini_nlt else None
            })

        return {"success": True, "offerte": risultati}

    except Exception as e:
        print(f"❌ Errore interno nella GET offerte: {e}")
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")




SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET_NAME = "nlt-images"

supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)


def upload_to_supabase(file_bytes, filename, content_type="image/webp"):
    from supabase import create_client
    import os

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    try:
        result = client.storage.from_("nlt-images").upload(
            filename, file_bytes, {"content-type": content_type}
        )
    except Exception as e:  # 👈 cattura l'errore generale chiaramente qui
        print(f"❌ Errore Supabase: {e}")
        raise HTTPException(status_code=500, detail=f"Errore upload Supabase: {e}")

    public_url = client.storage.from_("nlt-images").get_public_url(filename)
    return public_url




@router.post("/")
async def crea_offerta(
    marca: str = Body(...),
    modello: str = Body(...),
    versione: str = Body(...),
    codice_motornet: str = Body(...),
    codice_modello: Optional[str] = Body(None),  

    id_player: int = Body(...),
    prezzo_listino: Optional[float] = Body(None),
    prezzo_accessori: Optional[float] = Body(None),
    prezzo_mss: Optional[float] = Body(None),
    prezzo_totale: Optional[float] = Body(None),
    accessori: Optional[List[dict]] = Body(None),
    tags: Optional[List[int]] = Body(None),
    descrizione_breve: Optional[str] = Body(None),
    valido_da: Optional[str] = Body(None),
    valido_fino: Optional[str] = Body(None),
    quotazioni: Optional[dict] = Body(None),
    current_user: User = Depends(get_current_user),
    img_url: Optional[str] = Body(None),
    cambio: Optional[str] = Body(None),
    alimentazione: Optional[str] = Body(None),
    segmento: Optional[str] = Body(None),
    solo_privati: bool = Body(False),  # 👈 aggiungi questo, default False

    token: str = Depends(oauth2_scheme),  # 👈 aggiungi questo chiaramente
    db: Session = Depends(get_db)
):
    verify_admin_or_superadmin(current_user)

    if not valido_da:
        valido_da = datetime.utcnow().date()

    default_img_value = None

    if codice_modello:
        modello_data = db.query(MnetModelli).filter(MnetModelli.codice_modello == codice_modello).first()
        if modello_data:
            default_img_value = modello_data.default_img

     # Genera descrizione tramite OpenAI
        prompt_descrizione = (
            f"Descrivi in circa 350 caratteri (minimo 300, massimo 350 spazi inclusi) "
            f"le principali peculiarità e caratteristiche tecniche della {marca} {modello}. "
            f"Utilizza il grassetto (** **) esclusivamente per le parole chiave più importanti. "
            f"Non citare il noleggio, parla solo di estetica, prestazioni, comfort e tecnologia."
        )
        # Gestione errore chiamata OpenAI, descrizione AI diventa None in caso di fallimento
        try:
            descrizione_ai_generata = await genera_descrizione_gpt(prompt_descrizione)
        except Exception as e:
            print(f"Errore generazione descrizione OpenAI: {e}")
            descrizione_ai_generata = None

    # Ora crei sempre nuova_offerta, anche se codice_modello è None
    nuova_offerta = NltOfferte(
        id_admin=current_user.id,
        marca=marca,
        modello=modello,
        versione=versione,
        codice_motornet=codice_motornet,
        codice_modello=codice_modello,
        id_player=id_player,
        descrizione_breve=descrizione_breve,
        valido_da=valido_da,
        valido_fino=valido_fino,
        prezzo_listino=prezzo_listino,
        prezzo_accessori=prezzo_accessori,
        prezzo_mss=prezzo_mss,
        prezzo_totale=prezzo_totale,
        cambio=cambio,
        alimentazione=alimentazione,
        segmento=segmento,
        default_img=default_img_value,
        solo_privati=solo_privati,
        descrizione_ai=descrizione_ai_generata 


    )


    # 🔥 Genera slug subito dopo aver creato nuova_offerta
    # 🔥 Genera slug subito dopo aver creato nuova_offerta
    prefisso_slug = "privati-" if solo_privati else "business-"

    nuova_offerta.slug = generate_unique_slug(
        prefisso_slug + nuova_offerta.marca,
        nuova_offerta.modello,
        nuova_offerta.versione,
        db
    )

    db.add(nuova_offerta)
    db.commit()
    db.refresh(nuova_offerta)

    # Accessori
    if accessori:
        for acc in accessori:
            nuovo = NltOffertaAccessori(
                id_offerta=nuova_offerta.id_offerta,
                codice=acc["codice"],
                descrizione=acc["descrizione"],
                prezzo=acc["prezzo"]
            )
            db.add(nuovo)

    # Tags
    if tags:
        for id_tag in tags:
            db.add(NltOffertaTag(
                id_offerta=nuova_offerta.id_offerta,
                id_tag=id_tag
            ))

    # Quotazioni
    if quotazioni:
        db.add(NltQuotazioni(
            id_offerta=nuova_offerta.id_offerta,
            mesi_36_10=quotazioni.get("36_10"),
            mesi_36_15=quotazioni.get("36_15"),
            mesi_36_20=quotazioni.get("36_20"),
            mesi_36_25=quotazioni.get("36_25"),
            mesi_36_30=quotazioni.get("36_30"),
            mesi_36_40=quotazioni.get("36_40"),
            mesi_48_10=quotazioni.get("48_10"),
            mesi_48_15=quotazioni.get("48_15"),
            mesi_48_20=quotazioni.get("48_20"),
            mesi_48_25=quotazioni.get("48_25"),
            mesi_48_30=quotazioni.get("48_30"),
            mesi_48_40=quotazioni.get("48_40"),
            mesi_60_10=quotazioni.get("60_10"),  # 👈 nuove
            mesi_60_15=quotazioni.get("60_15"),  # 👈 nuove
            mesi_60_20=quotazioni.get("60_20"),  # 👈 nuove
            mesi_60_25=quotazioni.get("60_25"),  # 👈 nuove
            mesi_60_30=quotazioni.get("60_30"),  # 👈 nuove
            mesi_60_40=quotazioni.get("60_40")   # 👈 nuove
        ))

    db.commit()

    if img_url:
        immagine_principale = NltImmagini(
            id_offerta=nuova_offerta.id_offerta,
            url_imagin=img_url,
            principale=True
        )
        db.add(immagine_principale)
        db.commit()

    # Recupero immagini da CDN e salvataggio in Supabase
    backend_base_url = "https://coreapi-production-ca29.up.railway.app/api/image"
    angles = {"front": 203, "back": 213, "front_alt": 23, "back_alt": 9}
    urls_supabase = {}

    for view, angle in angles.items():
        params = {
            "angle": angle,
            "width": 800,
            "return_url": False,
            "random_paint": "true"
        }

        # SOLO per angoli originali (203 e 213)
        if angle in [203, 213]:
            if solo_privati:
                if angle == 203:
                    params["surrounding"] = "sur5"
                    params["viewPoint"] = "1"
                else:  # angle == 213
                    params["surrounding"] = "sur5"
                    params["viewPoint"] = "2"
            else:
                if angle == 203:
                    params["surrounding"] = "sur2"
                    params["viewPoint"] = "1"
                else:  # angle == 213
                    params["surrounding"] = "sur2"
                    params["viewPoint"] = "4"
        # Nuove immagini (23 e 9) NON hanno parametri aggiuntivi

        # Chiamata interna diretta (senza httpx)
        try:
            internal_response = await get_vehicle_image(
                codice_modello=codice_modello,
                angle=params["angle"],
                random_paint=params["random_paint"],
                width=params["width"],
                return_url=params["return_url"],
                db=db,
                current_user=current_user,
                surrounding=params.get("surrounding"),
                viewPoint=params.get("viewPoint")
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Errore interno immagine {view}: {e}")

        # internal_response è un oggetto Response di FastAPI/Starlette
        response_content = internal_response.body

        # Conversione in WEBP
        try:
            img_byte_arr = BytesIO(response_content)
            img_byte_arr.seek(0)

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore conversione immagine {view}: {e}")

        # Upload su Supabase
        unique_filename = f"{nuova_offerta.id_offerta}_{view}.webp"
        try:
            supabase_url = upload_to_supabase(
                file_bytes=img_byte_arr.getvalue(),
                filename=unique_filename,
                content_type="image/webp"
            )
            urls_supabase[view] = supabase_url
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore upload Supabase immagine {view}: {e}")

        # Salvataggio definitivo URL immagini su DB
    nuove_immagini_nlt = ImmaginiNlt(
        id_offerta=nuova_offerta.id_offerta,
        url_immagine_front=urls_supabase["front"],
        url_immagine_back=urls_supabase["back"],
        url_immagine_front_alt=urls_supabase["front_alt"],  # ✅ aggiunto
        url_immagine_back_alt=urls_supabase["back_alt"]     # ✅ aggiunto
    )

    db.add(nuove_immagini_nlt)
    db.commit()

    return {"success": True, "id_offerta": nuova_offerta.id_offerta}



# ✅ PUT Attiva/Disattiva Offerta
@router.put("/{id_offerta}/stato")
async def cambia_stato_offerta(
    id_offerta: int,
    attivo: bool,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_admin_or_superadmin(current_user)

    offerta = db.query(NltOfferte).filter(NltOfferte.id_offerta == id_offerta).first()
    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata.")

    if current_user.role != 'superadmin' and offerta.id_admin != current_user.id:
        raise HTTPException(status_code=403, detail="Non puoi modificare questa offerta.")

    offerta.attivo = attivo
    db.commit()
    db.refresh(offerta)

    return {"success": True, "attivo": offerta.attivo}

# ✅ GET Players disponibili (utile per frontend dropdown)
@router.get("/players")
async def get_players(db: Session = Depends(get_db)):
    players = db.query(NltPlayers).order_by(NltPlayers.nome).all()
    return {"success": True, "players": players}

# ✅ GET Tag disponibili (utile per frontend dropdown)
@router.get("/tags")
async def get_tags(db: Session = Depends(get_db)):
    tags = db.query(NltOfferteTag).order_by(NltOfferteTag.nome).all()
    return {"success": True, "tags": tags}


# Importa modello necessario

@router.get("/offerte-nlt-pubbliche/{slug}")
async def offerte_nlt_pubbliche(
    slug: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db)
):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Slug '{slug}' non trovato.")

    user_id = settings.dealer_id if settings.dealer_id else settings.admin_id
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato per questo slug.")

    admin_id = user.parent_id if user.role == "dealer" and user.parent_id else user.id

    offerte_query = db.query(NltOfferte, NltQuotazioni).join(
        NltQuotazioni, NltOfferte.id_offerta == NltQuotazioni.id_offerta
    ).filter(
        NltOfferte.id_admin == admin_id,
        NltOfferte.attivo.is_(True),
        NltOfferte.prezzo_listino.isnot(None),
        or_(
            NltQuotazioni.mesi_36_10.isnot(None),
            NltQuotazioni.mesi_48_10.isnot(None),
            NltQuotazioni.mesi_48_30.isnot(None)
        )
    ).order_by(NltOfferte.prezzo_listino.asc())

    offerte = offerte_query.offset(offset).limit(limit).all()

    risultato = []

    for offerta, quotazione in offerte:
        dealer_context = settings.dealer_id is not None
        dealer_id_for_context = settings.dealer_id if dealer_context else None

        durata_mesi, km_inclusi, canone, dealer_slug = calcola_quotazione(
            offerta, quotazione, user, db,
            dealer_context=dealer_context, dealer_id=dealer_id_for_context
        )

        if canone is None:
            continue

        dettagli = db.query(MnetDettagli).filter(
            MnetDettagli.codice_motornet_uni == offerta.codice_motornet
        ).first()

        tipo_descrizione = dettagli.tipo_descrizione if dettagli else None
        segmento_descrizione = dettagli.segmento_descrizione if dettagli else None

        modello_db = db.query(MnetModelli).filter(
            MnetModelli.codice_modello == offerta.codice_modello
        ).first()

        immagine_url = modello_db.default_img if modello_db and modello_db.default_img else "/default-placeholder.png"

        risultato.append({
            "id_offerta": offerta.id_offerta,
            "immagine": immagine_url,
            "marca": offerta.marca,
            "modello": offerta.modello,
            "versione": offerta.versione,
            "cambio": offerta.cambio,
            "alimentazione": offerta.alimentazione,
            "segmento": offerta.segmento,
            "segmento_descrizione": segmento_descrizione,
            "tipo_descrizione": tipo_descrizione,
            "canone_mensile": float(canone),
            "prezzo_listino": float(offerta.prezzo_listino),
            "prezzo_totale": float(offerta.prezzo_totale or offerta.prezzo_listino),
            "slug": offerta.slug,
            "solo_privati": offerta.solo_privati,
            "durata_mesi": durata_mesi,
            "km_inclusi": km_inclusi,
            "logo_web": settings.logo_web or "",
            "dealer_slug": dealer_slug
        })

    return risultato



@router.get("/offerte-nlt-pubbliche/tantastrada/{slug}")
async def offerte_nlt_tantastrada(
    slug: str,
    db: Session = Depends(get_db)
):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Slug '{slug}' non trovato.")

    user_id = settings.dealer_id if settings.dealer_id else settings.admin_id
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato per questo slug.")

    if user.role == "dealer":
        if user.parent_id is None:
            raise HTTPException(status_code=400, detail="Dealer senza admin principale associato.")
        admin_id = user.parent_id
    else:
        admin_id = user.id

    ESCLUDI_SEGMENTI = [
        "Superutilitarie",
        "Utilitarie",
        "SUV piccoli",
        "Medio-inferiori"
    ]

    offerte = db.query(NltOfferte, NltQuotazioni, MnetDettagli).join(
        NltQuotazioni, NltOfferte.id_offerta == NltQuotazioni.id_offerta
    ).join(
        MnetDettagli, MnetDettagli.codice_motornet_uni == NltOfferte.codice_motornet
    ).filter(
        NltOfferte.id_admin == admin_id,
        NltOfferte.id_player == 5,  # ✅ solo UnipolRental
        NltOfferte.attivo.is_(True),
        NltOfferte.prezzo_listino.isnot(None),
        NltQuotazioni.mesi_60_40.isnot(None),
        not_(MnetDettagli.segmento_descrizione.in_(ESCLUDI_SEGMENTI))
    ).order_by(NltOfferte.prezzo_listino.asc()).all()

    risultato = []

    for offerta, quotazione, dettagli in offerte:
        canone_base = quotazione.mesi_60_40
        if not canone_base:
            continue

        dealer_context = settings.dealer_id is not None
        dealer_id_for_context = settings.dealer_id if dealer_context else None

        durata_mesi = 60
        km_inclusi = 40000

        durata, km, canone, dealer_slug = calcola_quotazione_custom(
            offerta, durata_mesi, km_inclusi, canone_base, user, db,
            dealer_context=dealer_context, dealer_id=dealer_id_for_context
        )

        if canone is None:
            continue

        modello_db = db.query(MnetModelli).filter(
            MnetModelli.codice_modello == offerta.codice_modello
        ).first()

        immagine_url = modello_db.default_img if modello_db and modello_db.default_img else "/default-placeholder.png"

        risultato.append({
            "id_offerta": offerta.id_offerta,
            "immagine": immagine_url,
            "marca": offerta.marca,
            "modello": offerta.modello,
            "versione": offerta.versione,
            "cambio": offerta.cambio,
            "alimentazione": offerta.alimentazione,
            "segmento": offerta.segmento,
            "segmento_descrizione": dettagli.segmento_descrizione if dettagli else None,
            "tipo_descrizione": dettagli.tipo_descrizione if dettagli else None,
            "canone_mensile": float(canone),
            "prezzo_listino": float(offerta.prezzo_listino),
            "prezzo_totale": float(offerta.prezzo_totale or offerta.prezzo_listino),
            "slug": offerta.slug,
            "solo_privati": offerta.solo_privati,
            "durata_mesi": durata,
            "km_inclusi": km,
            "logo_web": settings.logo_web or "",
            "dealer_slug": dealer_slug
        })

    return risultato

@router.get("/offerte-nlt-pubbliche-filtrate/{slug}")
async def offerte_filtrate_nlt_pubbliche(
    slug: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, le=500),
    marca: Optional[str] = Query(None),
    budget_max: Optional[float] = Query(None),
    tipo: Optional[str] = Query(None),
    segmento: Optional[str] = Query(None),
    alimentazione: Optional[str] = Query(None),
    cambio: Optional[str] = Query(None),
    tanti_km: Optional[bool] = Query(False),
    top: Optional[bool] = Query(False),
    db: Session = Depends(get_db)
):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Slug '{slug}' non trovato.")

    user_id = settings.dealer_id if settings.dealer_id else settings.admin_id
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato per questo slug.")

    admin_id = user.parent_id if user.role == "dealer" and user.parent_id else user.id

    offerte_query = db.query(NltOfferte, NltQuotazioni).join(
        NltQuotazioni, NltOfferte.id_offerta == NltQuotazioni.id_offerta
    ).filter(
        NltOfferte.id_admin == admin_id,
        NltOfferte.attivo.is_(True),
        NltOfferte.prezzo_listino.isnot(None),
        or_(
            NltQuotazioni.mesi_36_10.isnot(None),
            NltQuotazioni.mesi_48_10.isnot(None),
            NltQuotazioni.mesi_48_30.isnot(None)
        )
    )

    # Filtri
    if marca:
        offerte_query = offerte_query.filter(
            func.lower(NltOfferte.marca) == marca.lower().strip()
        )

    if budget_max:
        offerte_query = offerte_query.filter(
            NltOfferte.prezzo_listino <= budget_max * 60
        )

    if tipo:
        tipo_clean = tipo.lower().strip()
        if tipo_clean == "privato":
            offerte_query = offerte_query.filter(NltOfferte.solo_privati.is_(True))
        elif tipo_clean == "business":
            offerte_query = offerte_query.filter(NltOfferte.solo_privati.is_(False))

    if segmento:
        offerte_query = offerte_query.filter(
            NltOfferte.segmento == segmento.upper().strip()
        )

    if alimentazione:
        offerte_query = offerte_query.filter(
            func.lower(NltOfferte.alimentazione) == alimentazione.lower().strip()
        )

    if cambio:
        cambio_clean = cambio.lower().strip()
        if cambio_clean == "manuale":
            offerte_query = offerte_query.filter(
                func.lower(NltOfferte.cambio).like("%manuale%")
            )
        elif cambio_clean == "automatico":
            offerte_query = offerte_query.filter(
                or_(
                    func.lower(NltOfferte.cambio).like("%automatico%"),
                    func.lower(NltOfferte.cambio).like("%cvt%")
                )
            )
    if tanti_km:
        offerte_query = offerte_query.join(
            MnetDettagli, MnetDettagli.codice_motornet_uni == NltOfferte.codice_motornet
        ).filter(
            NltOfferte.id_player == 5,
            NltQuotazioni.mesi_60_40.isnot(None),
            not_(MnetDettagli.segmento_descrizione.in_([
                "Superutilitarie",
                "Utilitarie",
                "SUV piccoli",
                "Medio-inferiori"
            ]))
        )
  
    if top:
        subquery_clicks = (
            db.query(
                NltOfferteClick.id_offerta,
                func.count(NltOfferteClick.id).label("clicks")
            )
            .join(NltOfferte, NltOfferte.id_offerta == NltOfferteClick.id_offerta)
            .filter(
                NltOfferte.id_admin == admin_id,
                NltOfferteClick.clicked_at >= datetime.utcnow() - timedelta(days=30)
            )
            .group_by(NltOfferteClick.id_offerta)
            .order_by(desc("clicks"))
            .limit(10)
            .subquery()
        )

        id_offerte_top = [row.id_offerta for row in db.execute(select(subquery_clicks.c.id_offerta)).fetchall()]
    
        if not id_offerte_top:
            return []

        offerte_query = offerte_query.filter(
            NltOfferte.id_offerta.in_(id_offerte_top)
        )



    offerte_query = offerte_query.order_by(NltOfferte.prezzo_listino.asc())
    offerte = offerte_query.offset(offset).limit(limit).all()

    risultato = []

    for offerta, quotazione in offerte:
        dealer_context = settings.dealer_id is not None
        dealer_id_for_context = settings.dealer_id if dealer_context else None

        if tanti_km:
            durata_mesi = 60
            km_inclusi = 40000
            canone_base = quotazione.mesi_60_40
            if not canone_base:
                continue

            durata_mesi, km_inclusi, canone, dealer_slug = calcola_quotazione_custom(
                offerta, durata_mesi, km_inclusi, canone_base, user, db,
                dealer_context=dealer_context, dealer_id=dealer_id_for_context
            )
        else:
            durata_mesi, km_inclusi, canone, dealer_slug = calcola_quotazione(
                offerta, quotazione, user, db,
                dealer_context=dealer_context, dealer_id=dealer_id_for_context
            )


        if canone is None:
            continue

        dettagli = db.query(MnetDettagli).filter(
            MnetDettagli.codice_motornet_uni == offerta.codice_motornet
        ).first()

        tipo_descrizione = dettagli.tipo_descrizione if dettagli else None
        segmento_descrizione = dettagli.segmento_descrizione if dettagli else None

        modello_db = db.query(MnetModelli).filter(
            MnetModelli.codice_modello == offerta.codice_modello
        ).first()

        immagine_url = modello_db.default_img if modello_db and modello_db.default_img else "/default-placeholder.png"

        risultato.append({
            "id_offerta": offerta.id_offerta,
            "immagine": immagine_url,
            "marca": offerta.marca,
            "modello": offerta.modello,
            "versione": offerta.versione,
            "cambio": offerta.cambio,
            "alimentazione": offerta.alimentazione,
            "segmento": offerta.segmento,
            "segmento_descrizione": segmento_descrizione,
            "tipo_descrizione": tipo_descrizione,
            "canone_mensile": float(canone),
            "prezzo_listino": float(offerta.prezzo_listino),
            "prezzo_totale": float(offerta.prezzo_totale or offerta.prezzo_listino),
            "slug": offerta.slug,
            "solo_privati": offerta.solo_privati,
            "durata_mesi": durata_mesi,
            "km_inclusi": km_inclusi,
            "logo_web": settings.logo_web or "",
            "dealer_slug": dealer_slug
        })

    return risultato




# Funzione separata con gestione retry (3 tentativi con 2 secondi tra tentativi)

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(HTTPException))
async def fetch_motornet_details(codice_motornet: str, token: str):
    motornet_url = f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/dettaglio?codice_motornet_uni={codice_motornet}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(motornet_url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Errore recupero dettagli Motornet")

    return response.json()

# Funzione di fallback che restituisce dati N.D.
def get_dati_nd():
    return {
        "modello": {
            "marca": {"acronimo": "N.D.", "nome": "N.D.", "logo": None},
            "gammaModello": {"codice": "N.D.", "descrizione": "N.D."},
            "inizioProduzione": "N.D.",
            "fineProduzione": "N.D.",
            "gruppoStorico": {"codice": "N.D.", "descrizione": "N.D."},
            "serieGamma": {"codice": "N.D.", "descrizione": "N.D."},
            "codDescModello": {"codice": "N.D.", "descrizione": "N.D."},
            "inizioCommercializzazione": "N.D.",
            "fineCommercializzazione": "N.D.",
            "modello": "N.D.",
            "foto": None,
            "prezzoMinimo": "N.D.",
            "modelloBreveCarrozzeria": {"id": "N.D.", "descrizione": "N.D."},
            "allestimento": "N.D.",
            "immagine": None,
            "codiceCostruttore": "N.D.",
            "codiceMotornetUnivoco": "N.D.",
            "codiceMotore": "N.D.",
            "prezzoAccessori": "N.D.",
            "prezzoListino": "N.D.",
            "dataListino": "N.D.",
            "tipo": {"codice": "N.D.", "descrizione": "N.D."},
            "segmento": {"codice": "N.D.", "descrizione": "N.D."},
            "alimentazione": {"codice": "N.D.", "descrizione": "N.D."},
            "categoria": {"codice": "N.D.", "descrizione": "N.D."},
            "cilindrata": "N.D.",
            "cavalliFiscali": "N.D.",
            "tipoMotore": "N.D.",
            "descrizioneMotore": "N.D.",
            "hp": "N.D.",
            "kw": "N.D.",
            "euro": "N.D.",
            "emissioniCo2": "N.D.",
            "consumoMedio": "N.D.",
            "cambio": {"codice": "N.D.", "descrizione": "N.D."},
            "nomeCambio": "N.D.",
            "descrizioneMarce": "N.D.",
            "accelerazione": "N.D.",
            "altezza": "N.D.",
            "cilindri": "N.D.",
            "consumoUrbano": "N.D.",
            "consumoExtraurbano": "N.D.",
            "coppia": "N.D.",
            "numeroGiri": "N.D.",
            "larghezza": "N.D.",
            "lunghezza": "N.D.",
            "pneumaticiAnteriori": "N.D.",
            "pneumaticiPosteriori": "N.D.",
            "valvole": "N.D.",
            "velocita": "N.D.",
            "passo": "N.D.",
            "porte": "N.D.",
            "posti": "N.D.",
            "trazione": {"codice": "N.D.", "descrizione": "N.D."},
            "altezzaMinima": "N.D.",
            "autonomiaMedia": "N.D.",
            "autonomiaMassima": "N.D.",
            "bagagliaio": "N.D.",
            "cavalliIbrido": "N.D.",
            "cavalliTotale": "N.D.",
            "potenzaIbrido": "N.D.",
            "potenzaTotale": "N.D.",
            "coppiaIbrido": "N.D.",
            "coppiaTotale": "N.D.",
            "equipaggiamento": "N.D.",
            "garanziaKm": "N.D.",
            "garanziaTempo": "N.D.",
            "hc": "N.D.",
            "neoPatentati": "N.D.",
            "nox": "N.D.",
            "numeroGiriIbrido": "N.D.",
            "numeroGiriTotale": "N.D.",
            "architettura": {"codice": "N.D.", "descrizione": "N.D."},
            "traino": "N.D.",
            "portata": "N.D.",
            "pm10": "N.D.",
            "pesoPotenza": "N.D.",
            "peso": "N.D.",
            "tipoGuida": "N.D.",
            "massaPCarico": "N.D.",
            "capSerbLitri": "N.D.",
            "pesoVuoto": "N.D.",
            "paeseProd": "N.D.",
            "descrizioneBreve": "N.D.",
            "accessoriSerie": [],
            "accessoriOpzionali": [],
            "wltp": "N.D."
        },
        "accessiDisponibili": "N.D."
    }

@router.get("/offerte-nlt-pubbliche/{slug_dealer}/{slug_offerta}")
async def offerta_nlt_pubblica(slug_dealer: str, slug_offerta: str, db: Session = Depends(get_db)):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug_dealer).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer '{slug_dealer}' non trovato.")

    user_id = settings.dealer_id if settings.dealer_id else settings.admin_id
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente admin non trovato per questo dealer.")


    offerta = db.query(NltOfferte).join(User, NltOfferte.id_admin == User.id).filter(
        User.id == settings.admin_id,
        NltOfferte.slug == slug_offerta,
        NltOfferte.attivo == True
    ).first()

    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata.")

    token = get_motornet_token()

    try:
        dettagli_motornet = await fetch_motornet_details(offerta.codice_motornet, token)
        motornet_status = "OK"
    except HTTPException:
        dettagli_motornet = get_dati_nd()
        motornet_status = "KO"
        logger.error(f"Motornet non raggiungibile per {offerta.codice_motornet}")

    # Recupera quotazioni
    quotazione = db.query(NltQuotazioni).filter(NltQuotazioni.id_offerta == offerta.id_offerta).first()

    dealer_context = settings.dealer_id is not None
    dealer_id_for_context = settings.dealer_id if dealer_context else None
    durata_mesi, km_inclusi, canone, dealer_slug = calcola_quotazione(
        offerta, quotazione, user, db, dealer_context=dealer_context, dealer_id=dealer_id_for_context
    )



    return {
        "id_offerta": offerta.id_offerta,
        "immagine": offerta.default_img,
        "marca": offerta.marca,
        "modello": offerta.modello,
        "versione": offerta.versione,
        "cambio": offerta.cambio,
        "alimentazione": offerta.alimentazione,
        "prezzo_listino": float(offerta.prezzo_listino) if offerta.prezzo_listino else None,
        "prezzo_totale": float(offerta.prezzo_totale) if offerta.prezzo_totale else None,
        "descrizione_breve": offerta.descrizione_breve,
        "slug": offerta.slug,
        "solo_privati": offerta.solo_privati,
        "descrizione_ai": offerta.descrizione_ai,
        "motornet_status": motornet_status,
        "canone_mensile": float(canone) if canone else None,
        "durata_mesi": durata_mesi,
        "km_inclusi": km_inclusi,
        "dealer_slug": dealer_slug,  # ✅ aggiunto correttamente

        "dettagli_motornet": dettagli_motornet
    }

@router.get("/offerte-nlt-pubbliche/tantastrada/{slug_dealer}/{slug_offerta}")
async def offerta_nlt_tantastrada(
    slug_dealer: str,
    slug_offerta: str,
    db: Session = Depends(get_db)
):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug_dealer).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer '{slug_dealer}' non trovato.")

    user_id = settings.dealer_id if settings.dealer_id else settings.admin_id
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente admin non trovato per questo dealer.")

    offerta = db.query(NltOfferte).join(User, NltOfferte.id_admin == User.id).filter(
        User.id == settings.admin_id,
        NltOfferte.slug == slug_offerta,
        NltOfferte.attivo == True
    ).first()

    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata.")

    quotazione = db.query(NltQuotazioni).filter(
        NltQuotazioni.id_offerta == offerta.id_offerta
    ).first()

    if not quotazione or not quotazione.mesi_60_40:
        raise HTTPException(status_code=404, detail="Quotazione 60/40 non disponibile per questa offerta.")

    canone_base = quotazione.mesi_60_40
    durata = 60
    km = 40000

    # Calcola canone finale con provvigioni
    dealer_context = settings.dealer_id is not None
    dealer_id_for_context = settings.dealer_id if dealer_context else None

    _, _, canone_finale, dealer_slug = calcola_quotazione_custom(
        offerta, durata, km, canone_base, user, db,
        dealer_context=dealer_context, dealer_id=dealer_id_for_context
    )

    # Recupera dettagli motornet
    token = get_motornet_token()

    try:
        dettagli_motornet = await fetch_motornet_details(offerta.codice_motornet, token)
        motornet_status = "OK"
    except HTTPException:
        dettagli_motornet = get_dati_nd()
        motornet_status = "KO"
        logger.error(f"Motornet non raggiungibile per {offerta.codice_motornet}")

    return {
        "id_offerta": offerta.id_offerta,
        "immagine": offerta.default_img,
        "marca": offerta.marca,
        "modello": offerta.modello,
        "versione": offerta.versione,
        "cambio": offerta.cambio,
        "alimentazione": offerta.alimentazione,
        "prezzo_listino": float(offerta.prezzo_listino) if offerta.prezzo_listino else None,
        "prezzo_totale": float(offerta.prezzo_totale) if offerta.prezzo_totale else None,
        "descrizione_breve": offerta.descrizione_breve,
        "slug": offerta.slug,
        "solo_privati": offerta.solo_privati,
        "descrizione_ai": offerta.descrizione_ai,
        "motornet_status": motornet_status,
        "canone_mensile": float(canone_finale) if canone_finale else None,
        "durata": durata,
        "km": km,
        "dealer_slug": dealer_slug,
        "dettagli_motornet": dettagli_motornet
    }



@router.put("/quotazioni/{id_offerta}")
def aggiorna_quotazioni(
    id_offerta: int,
    quotazioni: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_admin_or_superadmin(current_user)

    offerta = db.query(NltOfferte).filter(NltOfferte.id_offerta == id_offerta).first()

    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata.")

    quotazione = db.query(NltQuotazioni).filter(NltQuotazioni.id_offerta == id_offerta).first()

    if not quotazione:
        quotazione = NltQuotazioni(id_offerta=id_offerta)
        db.add(quotazione)

    campi_validi = [
        "36_10", "36_15", "36_20", "36_25", "36_30", "36_40",
        "48_10", "48_15", "48_20", "48_25", "48_30", "48_40",
        "60_10", "60_15", "60_20", "60_25", "60_30", "60_40"
    ]
    # Aggiorna solo campi presenti e non nulli
    for campo in campi_validi:
        valore = quotazioni.get(campo)
        if valore is not None:
            setattr(quotazione, f"mesi_{campo}", valore)

    db.commit()
    db.refresh(quotazione)

    return {"success": True, "quotazioni": quotazioni}



async def recupera_diametro_pneumatici(codice_motornet: str, jwt_token: str) -> int:
    url = f"https://coreapi-production-ca29.up.railway.app/api/nuovo/motornet/dettagli/{codice_motornet}"
    headers = {"Authorization": f"Bearer {jwt_token}"}

    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)

    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail="Errore dati motornet")

    data = res.json()
    modello = data.get("modello", {})

    anteriori = modello.get("pneumatici_anteriori", "")
    posteriori = modello.get("pneumatici_posteriori", "")

    diametri = []
    for misura in [anteriori, posteriori]:
        match = re.search(r"R(\d{2})", misura)
        if match:
            diametri.append(int(match.group(1)))

    if not diametri:
        raise HTTPException(status_code=422, detail="Diametro non trovato")

    return max(diametri)


from fastapi import Request

@router.post("/nlt/calcola-canone")
async def calcola_canone(
    payload: CanoneRequest, 
    db: Session = Depends(get_db), 
    current_user=Depends(get_current_user),
    request: Request = None
):
    offerta = db.query(NltOfferte).filter(NltOfferte.id_offerta == payload.id_offerta).first()
    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata")

    quotazione = db.query(NltQuotazioni).filter(NltQuotazioni.id_offerta == offerta.id_offerta).first()
    if not quotazione:
        raise HTTPException(status_code=404, detail="Quotazione non trovata")

    campo = f"mesi_{payload.durata}_{payload.km_annui}"
    canone_base = getattr(quotazione, campo, None)
    if not canone_base:
        raise HTTPException(status_code=400, detail=f"Nessuna quotazione trovata per {campo}")

    prov_admin = db.query(SiteAdminSettings.prov_vetrina).filter(
        SiteAdminSettings.admin_id == offerta.id_admin,
        SiteAdminSettings.dealer_id.is_(None)
    ).scalar() or 0.0

    # 🔒 Eccezione per Unipolrental (id_player = 5)
    if offerta.id_player == 5:
        prov_totale = prov_admin  # agency_type ignorata
    else:
        prov_totale = prov_admin + payload.provvigione_extra

    incremento = float(offerta.prezzo_totale) * float(prov_totale) / 100.0
    canone_finale = float(canone_base) + (incremento / payload.durata)

    if payload.anticipo > 0:
        canone_finale -= (payload.anticipo / payload.durata)

    if payload.pneumatici:
        jwt_token = request.headers.get("Authorization").split(" ")[1]
        diametro = await recupera_diametro_pneumatici(offerta.codice_motornet, jwt_token)
        record_pneumatico = db.query(NltPneumatici).filter(
            NltPneumatici.diametro == diametro
        ).first()

        if record_pneumatico:
            costo_treno = float(record_pneumatico.costo_treno)
            canone_finale += (costo_treno * payload.n_treni) / payload.durata
        else:
            raise HTTPException(status_code=404, detail=f"Costo pneumatici R{diametro} non trovato")

    if payload.auto_sostitutiva and payload.categoria_sostitutiva:
        record_sost = db.query(NltAutoSostitutiva).filter(
            NltAutoSostitutiva.segmento == payload.categoria_sostitutiva.upper()
        ).first()

        if record_sost:
            costo_sost = float(record_sost.costo_mensile)
            canone_finale += costo_sost
        else:
            raise HTTPException(status_code=404, detail=f"Segmento auto sostitutiva {payload.categoria_sostitutiva} non trovato")

    if offerta.solo_privati:
        canone_finale *= 1.22

    return {"canone": round(canone_finale, 2)}


@router.post("/click")
async def registra_click_offerta(
    dealer_slug: str = Body(...),
    id_offerta: int = Body(...),
    db: Session = Depends(get_db)
):
    # 1. Recupera settings dealer/admin
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == dealer_slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer '{dealer_slug}' non trovato.")

    id_dealer = settings.dealer_id if settings.dealer_id else settings.admin_id

    # 2. Verifica che l'offerta esista e sia collegata all'admin corretto
    offerta = db.query(NltOfferte).filter(NltOfferte.id_offerta == id_offerta).first()
    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata.")

    # 3. Registra click (sempre dealer o admin)
    nuovo_click = NltOfferteClick(
        id_offerta=id_offerta,
        id_dealer=id_dealer
    )
    db.add(nuovo_click)
    db.commit()

    return {"success": True}


