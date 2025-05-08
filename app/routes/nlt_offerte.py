from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session, selectinload
from typing import Optional, List
from app.database import get_db
from app.models import NltQuotazioni, NltPlayers, NltImmagini,MnetModelli, NltOfferteTag, NltOffertaTag, User, NltOffertaAccessori,SiteAdminSettings, NltOfferte, SmtpSettings
from app.auth_helpers import is_admin_user, is_dealer_user, get_admin_id, get_dealer_id
from app.routes.nlt import get_current_user  
from datetime import date, datetime
from .motornet import get_motornet_token
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from routes.openai_config import genera_descrizione_gpt

import unidecode
import re

import requests
import httpx

from app.auth_helpers import (
    get_admin_id,
    get_dealer_id,
    is_admin_user,
    is_dealer_user
)



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
    query = db.query(NltOfferte).options(
        selectinload(NltOfferte.accessori),
        selectinload(NltOfferte.tags),
        selectinload(NltOfferte.quotazioni),
        selectinload(NltOfferte.immagini),
        selectinload(NltOfferte.player)
    )

    # 👇 Logica aggiornata con filtro attivo=True di default se non specificato
    if attivo is None:
        query = query.filter(NltOfferte.attivo.is_(True))
    else:
        query = query.filter(NltOfferte.attivo == attivo)

    if current_user.role == "superadmin":
        pass  # nessun filtro, vede tutte le offerte (solo filtro attivo)

    elif is_admin_user(current_user):
        admin_id = get_admin_id(current_user)
        query = query.filter(NltOfferte.id_admin == admin_id)

    elif is_dealer_user(current_user):
        admin_id = get_admin_id(current_user)
        query = query.filter(NltOfferte.id_admin == admin_id)

    # 👇 Ordinamento per prezzo_listino ASC (prezzo più basso prima)
    offerte = query.order_by(NltOfferte.prezzo_listino.asc()).all()

    risultati = []
    for o in offerte:
        risultati.append({
            "id_offerta": o.id_offerta,
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
            "default_img": o.default_img,  # 🔥 Qui aggiunto
            "solo_privati": o.solo_privati,

            "accessori": [
                {
                    "codice": a.codice,
                    "descrizione": a.descrizione,
                    "prezzo": float(a.prezzo)
                } for a in o.accessori
            ],
            "tags": [
                {
                    "id_tag": t.id_tag,
                    "nome": t.nome,
                    "fa_icon": t.fa_icon,
                    "colore": t.colore
                } for t in o.tags
            ],
            "quotazioni": {
                "36_10": o.quotazioni[0].mesi_36_10 if o.quotazioni else None,
                "36_15": o.quotazioni[0].mesi_36_15 if o.quotazioni else None,
                "36_20": o.quotazioni[0].mesi_36_20 if o.quotazioni else None,
                "36_25": o.quotazioni[0].mesi_36_25 if o.quotazioni else None,
                "36_30": o.quotazioni[0].mesi_36_30 if o.quotazioni else None,
                "36_40": o.quotazioni[0].mesi_36_40 if o.quotazioni else None,
                "48_10": o.quotazioni[0].mesi_48_10 if o.quotazioni else None,
                "48_15": o.quotazioni[0].mesi_48_15 if o.quotazioni else None,
                "48_20": o.quotazioni[0].mesi_48_20 if o.quotazioni else None,
                "48_25": o.quotazioni[0].mesi_48_25 if o.quotazioni else None,
                "48_30": o.quotazioni[0].mesi_48_30 if o.quotazioni else None,
                "48_40": o.quotazioni[0].mesi_48_40 if o.quotazioni else None,
                "60_10": o.quotazioni[0].mesi_60_10 if o.quotazioni else None,
                "60_15": o.quotazioni[0].mesi_60_15 if o.quotazioni else None,
                "60_20": o.quotazioni[0].mesi_60_20 if o.quotazioni else None,
                "60_25": o.quotazioni[0].mesi_60_25 if o.quotazioni else None,
                "60_30": o.quotazioni[0].mesi_60_30 if o.quotazioni else None,
                "60_40": o.quotazioni[0].mesi_60_40 if o.quotazioni else None,
            },
                "immagine": next((img.url_imagin for img in o.immagini if img.principale), None)
        })

    return {"success": True, "offerte": risultati}




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
    prompt_descrizione = f"Scrivi una breve descrizione coinvolgente e commerciale per un'offerta di noleggio a lungo termine dell'auto {marca} {modello}, evidenziandone caratteristiche e benefici."
    descrizione_ai_generata = await genera_descrizione_gpt(prompt_descrizione)

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
    nuova_offerta.slug = generate_unique_slug(
        nuova_offerta.marca,
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


@router.get("/offerte-nlt-pubbliche/{slug}")
async def offerte_nlt_pubbliche(
    slug: str,
    db: Session = Depends(get_db)
):
    # 1. Controlla settings da slug
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Slug '{slug}' non trovato.")

    # 2. Carica utente legato a settings
    user = db.query(User).filter(User.id == settings.admin_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato per questo slug.")

    # 3. Determina admin_id corretto
    if user.role == "dealer":
        if user.parent_id is None:
            raise HTTPException(status_code=400, detail="Dealer senza admin principale associato.")
        admin_id = user.parent_id  # admin principale
    else:
        admin_id = user.id  # admin stesso

    # 4. Ottieni offerte pubbliche legate all'admin_id corretto
    offerte = db.query(NltOfferte, NltQuotazioni).join(
        NltQuotazioni, NltOfferte.id_offerta == NltQuotazioni.id_offerta
    ).filter(
        NltOfferte.id_admin == admin_id,
        NltOfferte.attivo == True,
        NltQuotazioni.mesi_36_10.isnot(None),
        NltOfferte.prezzo_listino.isnot(None)
    ).order_by(
        (NltQuotazioni.mesi_36_10 - (NltOfferte.prezzo_listino * 0.25 / 36)).asc()
    ).all()

    risultato = []
    for offerta, quotazione in offerte:
        canone_minimo = float(quotazione.mesi_36_10) - (float(offerta.prezzo_listino) * 0.25 / 36)

        immagine_url = f"https://coreapi-production-ca29.up.railway.app/api/image/{offerta.codice_modello}?angle=29&width=600&return_url=true"

        risultato.append({
            "id_offerta": offerta.id_offerta,
            "immagine": immagine_url,
            "marca": offerta.marca,
            "modello": offerta.modello,
            "versione": offerta.versione,
            "cambio": offerta.cambio,
            "alimentazione": offerta.alimentazione,
            "canone_mensile": round(canone_minimo, 2),
            "prezzo_listino": float(offerta.prezzo_listino),
            "default_img": offerta.default_img,
            "slug": offerta.slug,
            "solo_privati": offerta.solo_privati  # 👈 aggiungi solo questa riga



        })

    return risultato


# Funzione separata con gestione retry (3 tentativi con 2 secondi tra tentativi)
@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(HTTPException))
async def fetch_motornet_details(codice_motornet: str, token: str):
    motornet_url = f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/dettaglio?codice_motornet_uni={codice_motornet}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(motornet_url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Errore recupero dettagli Motornet")

    return response.json()


@router.get("/offerte-nlt-pubbliche/{slug_dealer}/{slug_offerta}")
async def offerta_nlt_pubblica(slug_dealer: str, slug_offerta: str, db: Session = Depends(get_db)):
    # 1. Recupera settings
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug_dealer).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer '{slug_dealer}' non trovato.")

    # 2. Cerca l'offerta
    offerta = db.query(NltOfferte).join(User, NltOfferte.id_admin == User.id).filter(
        User.id == settings.admin_id,
        NltOfferte.slug == slug_offerta,
        NltOfferte.attivo == True
    ).first()

    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata.")

    immagine_url = offerta.default_img

    # 3. Token Motornet
    token = get_motornet_token()

    # 4. Chiama funzione con retry automatico (max 3 tentativi)
    try:
        dettagli_motornet = await fetch_motornet_details(offerta.codice_motornet, token)
    except HTTPException as e:
        # Dopo 3 tentativi falliti, ritorna errore chiaro al frontend
        raise HTTPException(status_code=503, detail="Servizio temporaneamente non disponibile, riprova più tardi.")

    # 5. Risposta finale integrata
    risultato = {
        "id_offerta": offerta.id_offerta,
        "immagine": immagine_url,
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
        "dettagli_motornet": dettagli_motornet,
        "descrizione_ai": offerta.descrizione_ai

    }

    return risultato