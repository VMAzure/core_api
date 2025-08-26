from fastapi import Depends, HTTPException, APIRouter, UploadFile, File, status, Body, Form, Query
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import get_db, supabase_client, SUPABASE_URL
from app.models import User, AZUsatoInsertRequest, AZLeaseQuotazioni, SiteAdminSettings
from app.schemas import AutoUsataCreate
from app.auth_helpers import get_admin_id, get_dealer_id, is_admin_user, is_dealer_user
import uuid
from datetime import datetime
from sqlalchemy import text
import requests
import httpx
import re
from typing import Optional
from pydantic import BaseModel
from app.routes.auth import get_current_user  # la funzione che decodifica JWT
from typing import List

def get_descrizione_safe(val):
    return val.get("descrizione") if isinstance(val, dict) else val


router = APIRouter()

@router.post("/usato", tags=["AZLease"])
async def inserisci_auto_usata(
    payload: AZUsatoInsertRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    if not (is_admin_user(user) or is_dealer_user(user)):
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")

    dealer_id = get_dealer_id(user) if is_dealer_user(user) else None
    admin_id = get_admin_id(user)

    usatoin_id = uuid.uuid4()
    db.execute(text("""
        INSERT INTO azlease_usatoin (
            id, dealer_id, admin_id, data_inserimento, data_ultima_modifica, prezzo_costo,
            prezzo_vendita, visibile, opzionato_da, opzionato_il, venduto_da, venduto_il, iva_esposta
        ) VALUES (
            :id, :dealer_id, :admin_id, :inserimento, :modifica, :costo,
            :vendita, :visibile, :opzionato_da, :opzionato_il, :venduto_da, :venduto_il, :iva_esposta
        )
    """), {
        "id": str(usatoin_id),
        "dealer_id": int(dealer_id) if dealer_id else None,
        "admin_id": int(admin_id),
        "inserimento": datetime.utcnow(),
        "modifica": datetime.utcnow(),
        "costo": payload.prezzo_costo,
        "vendita": payload.prezzo_vendita,
        "visibile": payload.visibile,
        "opzionato_da": payload.opzionato_da,
        "opzionato_il": payload.opzionato_il,
        "venduto_da": payload.venduto_da,
        "venduto_il": payload.venduto_il,
        "iva_esposta": payload.iva_esposta if hasattr(payload, "iva_esposta") else False

    })

    auto_id = uuid.uuid4()
    db.execute(text("""
        INSERT INTO azlease_usatoauto (
            id, targa, anno_immatricolazione, data_passaggio_proprieta, km_certificati,
            data_ultimo_intervento, descrizione_ultimo_intervento, cronologia_tagliandi, doppie_chiavi,
            codice_motornet, colore, id_usatoin
        ) VALUES (
            :id, :targa, :anno, :passaggio, :km,
            :intervento_data, :intervento_desc, :tagliandi, :chiavi,
            :codice, :colore, :usatoin_id
        )
    """), {
        "id": str(auto_id),
        "targa": payload.targa,
        "anno": payload.anno_immatricolazione,
        "passaggio": payload.data_passaggio_proprieta,
        "km": payload.km_certificati,
        "intervento_data": payload.data_ultimo_intervento,
        "intervento_desc": payload.descrizione_ultimo_intervento,
        "tagliandi": payload.cronologia_tagliandi,
        "chiavi": payload.doppie_chiavi,
        "codice": payload.codice_motornet,
        "colore": payload.colore,
        "usatoin_id": str(usatoin_id)
    })

    # 🔗 I dettagli sono già presenti nella tabella mnet_dettagli_usato
    db.commit()

    return {
        "message": "Auto inserita correttamente",
        "id_auto": str(auto_id),
        "id_inserimento": str(usatoin_id)
    }



@router.post("/foto-usato", tags=["AZLease"])
async def upload_foto_usato(
    auto_id: str,
    file: UploadFile = File(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    auto = db.execute(text("""
        SELECT id_usatoin FROM azlease_usatoauto WHERE id = :auto_id
    """), {"auto_id": auto_id}).fetchone()

    inserimento = db.execute(text("""
        SELECT admin_id, dealer_id FROM azlease_usatoin WHERE id = :id_usatoin
    """), {"id_usatoin": auto.id_usatoin}).fetchone()

    user_is_owner = (
        user.id == inserimento.admin_id
        or user.id == inserimento.dealer_id
        or get_admin_id(user) == inserimento.admin_id
        or get_dealer_id(user) == inserimento.dealer_id
    )

    if not user_is_owner:
        raise HTTPException(403, detail="Non puoi aggiungere immagini a un'auto che non hai inserito")

    if file.content_type not in ["image/png", "image/jpeg", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Formato immagine non supportato")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    clean_filename = re.sub(r"[^\w\-\.]", "_", file.filename)
    file_name = f"auto-usate/{auto_id}_{timestamp}_{clean_filename}"

    try:
        content = await file.read()
        supabase_client.storage.from_("auto-usate").upload(
            file_name, content, {"content-type": file.content_type}
        )
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/auto-usate/{file_name}"
        img_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO azlease_usatoimg (id, auto_id, foto)
            VALUES (:id, :auto_id, :foto)
        """), {"id": img_id, "auto_id": auto_id, "foto": image_url})
        db.commit()
        return {"message": "Immagine caricata con successo", "image_url": image_url}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")


@router.post("/perizie-usato", tags=["AZLease"])
async def upload_perizia_usato(
    auto_id: str = Form(...),
    valore_perizia: float = Form(...),
    descrizione: str = Form(...),
    file: UploadFile = File(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    auto = db.execute(text("""
        SELECT id_usatoin FROM azlease_usatoauto WHERE id = :auto_id
    """), {"auto_id": auto_id}).fetchone()

    inserimento = db.execute(text("""
        SELECT admin_id, dealer_id FROM azlease_usatoin WHERE id = :id_usatoin
    """), {"id_usatoin": auto.id_usatoin}).fetchone()

    user_is_owner = (
        user.id == inserimento.admin_id
        or user.id == inserimento.dealer_id
        or get_admin_id(user) == inserimento.admin_id
        or get_dealer_id(user) == inserimento.dealer_id
    )

    if not user_is_owner:
        raise HTTPException(403, detail="Non puoi aggiungere perizie a un'auto che non hai inserito")

    if file.content_type not in ["image/png", "image/jpeg", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Formato immagine non supportato")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    file_name = f"auto-usate/danni/{auto_id}_{timestamp}_{file.filename}"

    try:
        content = await file.read()
        supabase_client.storage.from_("auto-usate").upload(
            file_name, content, {"content-type": file.content_type}
        )
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/auto-usate/{file_name}"
        danno_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO azlease_usatodanni (id, auto_id, foto, valore_perizia, descrizione)
            VALUES (:id, :auto_id, :foto, :valore_perizia, :descrizione)
        """), {
            "id": danno_id,
            "auto_id": auto_id,
            "foto": image_url,
            "valore_perizia": valore_perizia,
            "descrizione": descrizione
        })
        db.commit()
        return {"message": "Perizia inserita con successo", "danno_id": danno_id, "foto_url": image_url}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")



@router.get("/foto-usato/{auto_id}", tags=["AZLease"])
def get_foto_usato(auto_id: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()

    immagini = db.execute(text("""
        SELECT id, foto, principale FROM azlease_usatoimg WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchall()

    return {
        "auto_id": auto_id,
        "immagini": [
            {
                "id": img.id,
                "foto_url": img.foto,
                "principale": img.principale
            } for img in immagini
        ]
    }
@router.put("/foto-usato/{id_foto}/principale", tags=["AZLease"])
def imposta_foto_principale(id_foto: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()

    # 1. Recupera auto_id dalla foto selezionata
    foto = db.execute(text("""
        SELECT auto_id FROM azlease_usatoimg WHERE id = :id_foto
    """), {"id_foto": id_foto}).fetchone()

    if not foto:
        raise HTTPException(status_code=404, detail="Foto non trovata")

    auto_id = foto.auto_id

    # 2. Imposta tutte le foto dell'auto come principale = FALSE
    db.execute(text("""
        UPDATE azlease_usatoimg
        SET principale = FALSE
        WHERE auto_id = :auto_id
    """), {"auto_id": auto_id})

    # 3. Imposta la foto selezionata come principale = TRUE
    db.execute(text("""
        UPDATE azlease_usatoimg
        SET principale = TRUE
        WHERE id = :id_foto
    """), {"id_foto": id_foto})

    db.commit()

    return {"message": "Foto impostata come principale", "foto_id": id_foto}


@router.get("/perizie-usato/{auto_id}", tags=["AZLease"])
async def get_perizie_usato(auto_id: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Restituisce la lista di danni associati a un'auto."""
    Authorize.jwt_required()

    danni = db.execute(text("""
        SELECT id, foto, valore_perizia, descrizione FROM azlease_usatodanni WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchall()

    return {
        "auto_id": auto_id,
        "danni": [
            {"id": d.id, "foto_url": d.foto, "valore_perizia": d.valore_perizia, "descrizione": d.descrizione}
            for d in danni
        ]
    }

@router.get("/dettagli-usato/{auto_id}", tags=["AZLease"])
async def get_dettagli_usato(auto_id: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Restituisce tutti i dettagli completi di un'auto usata."""
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    # 🔍 Recupera i dati principali
    auto = db.execute(text("""
        SELECT * FROM azlease_usatoauto WHERE id = :auto_id
    """), {"auto_id": auto_id}).fetchone()
    if not auto:
        raise HTTPException(status_code=404, detail="Auto non trovata")

    # 🔍 Recupera dati di inserimento
    inserimento = db.execute(text("""
        SELECT * FROM azlease_usatoin
        WHERE id = :id_usatoin
    """), {"id_usatoin": auto.id_usatoin}).fetchone()
    if not inserimento:
        raise HTTPException(status_code=404, detail="Inserimento non trovato")

    is_admin_match = is_admin_user(user) and get_admin_id(user) == inserimento.admin_id
    is_dealer_match = is_dealer_user(user) and get_dealer_id(user) == inserimento.dealer_id

    is_creator = user.id in [inserimento.admin_id, inserimento.dealer_id]

    # 🔐 Controllo visibilità
    if not inserimento.visibile and not (is_creator or is_admin_match or is_dealer_match or user.role == "superadmin"):
        raise HTTPException(status_code=403, detail="Non hai accesso a questa auto (non visibile)")

    # 🔎 Recupera dettagli tecnici, immagini e danni
    # 🔎 Recupera dettagli tecnici, immagini e danni
    dettagli = db.execute(text("""
        SELECT * FROM mnet_dettagli_usato WHERE codice_motornet_uni = :codice
    """), {"codice": auto.codice_motornet}).fetchone()


    immagini = db.execute(text("""
        SELECT foto FROM azlease_usatoimg WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchall()

    danni = db.execute(text("""
        SELECT foto, valore_perizia, descrizione FROM azlease_usatodanni WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchall()

    return {
        "inserimento": dict(inserimento._mapping) if inserimento else {},
        "auto": dict(auto._mapping) if auto else {},
        "dettagli": dict(dettagli._mapping) if dettagli else {},
        "immagini": [img.foto for img in immagini],
        "danni": [
            {
                "foto": d.foto,
                "valore_perizia": d.valore_perizia,
                "descrizione": d.descrizione
            }
            for d in danni
        ]
    }

targa: Optional[str] = None

@router.get("/usato", tags=["AZLease"])
async def get_id_auto_usata(targa: Optional[str] = None, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()

    if targa:
        result = db.execute(text("""
            SELECT a.id FROM azlease_usatoauto a
            JOIN azlease_usatoin i ON a.id_usatoin = i.id
            WHERE a.targa = :targa AND i.visibile = true
        """), {"targa": targa}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Auto non trovata o non visibile")

        return {"id_auto": result.id}

    else:
        result = db.execute(text("""
            SELECT a.id FROM azlease_usatoauto a
            JOIN azlease_usatoin i ON a.id_usatoin = i.id
            WHERE i.visibile = true
        """)).fetchall()

        return {"id_auto": [r.id for r in result]}

@router.get("/usato/all", tags=["AZLease"])
async def get_id_auto_anche_non_visibili(targa: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()

    result = db.execute(text("""
        SELECT a.id FROM azlease_usatoauto a
        JOIN azlease_usatoin i ON a.id_usatoin = i.id
        WHERE a.targa = :targa
    """), {"targa": targa}).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Auto non trovata")

    return {"id_auto": result.id}

@router.get("/lista-auto", tags=["AZLease"])
async def lista_auto_usate(
    visibilita: Optional[str] = Query(None, description="visibili | non_visibili | tutte"),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    filtro = ""
    visibile_filter = ""

    if user.role == "superadmin":
        # Nessun filtro, vede tutto
        pass

    elif user.role in ["admin", "admin_team"]:
        admin_id = user.id if user.parent_id is None else user.parent_id

        dealer_ids = db.execute(text("""
            SELECT id FROM utenti WHERE parent_id = :admin_id
        """), {"admin_id": admin_id}).fetchall()

        tutti_id = [admin_id] + [r.id for r in dealer_ids]
        filtro = f"AND i.admin_id IN ({','.join(str(i) for i in tutti_id)})"

    elif user.role in ["dealer", "dealer_team"]:
        filtro = f"AND i.dealer_id = {user.id}"


    else:
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")

    # 🎯 Applica filtro visibilità se specificato
    if visibilita == "visibili":
        visibile_filter = "AND i.visibile = TRUE"
    elif visibilita == "non_visibili":
        visibile_filter = "AND i.visibile = FALSE"
    # se visibilita == "tutte" o None → nessun filtro

    query = f"""
        SELECT 
            a.id AS id_auto,
            a.targa,
            d.marca_nome AS marca,
            d.allestimento,
            a.km_certificati,
            a.colore,
            i.visibile,
            i.data_inserimento,
            a.anno_immatricolazione,
            u_admin.nome || ' ' || u_admin.cognome AS admin,
            u_dealer.nome || ' ' || u_dealer.cognome AS dealer,
            i.prezzo_costo,
            i.iva_esposta,
            i.prezzo_vendita,
            COALESCE(SUM(dn.valore_perizia), 0) AS valore_perizia,
            EXISTS (
                SELECT 1 FROM azlease_usatoimg img WHERE img.auto_id = a.id
            ) AS foto,
            EXISTS (
                SELECT 1 FROM azlease_usatodanni pd WHERE pd.auto_id = a.id
            ) AS perizie,
            i.opzionato_da,
            i.opzionato_il,
            u_opz.ragione_sociale AS opzionato_da_nome,
            i.venduto_da,
            i.dealer_id,
            i.admin_id
        FROM azlease_usatoauto a
        JOIN azlease_usatoin i ON i.id = a.id_usatoin
        LEFT JOIN mnet_dettagli_usato d ON d.codice_motornet_uni = a.codice_motornet
        LEFT JOIN utenti u_admin ON u_admin.id = i.admin_id
        LEFT JOIN utenti u_dealer ON u_dealer.id = i.dealer_id
        LEFT JOIN utenti u_opz ON u_opz.id = i.opzionato_da::int
        LEFT JOIN azlease_usatodanni dn ON dn.auto_id = a.id
        WHERE 1=1
        {filtro}
        {visibile_filter}
        GROUP BY 
            a.id, d.marca_nome, d.allestimento, a.km_certificati, a.colore, 
            i.visibile, i.data_inserimento, a.anno_immatricolazione, 
            u_admin.nome, u_admin.cognome, u_dealer.nome, u_dealer.cognome, 
            i.prezzo_vendita, i.prezzo_costo, i.iva_esposta,
            i.opzionato_da, i.opzionato_il, u_opz.ragione_sociale,
            i.venduto_da, i.dealer_id, i.admin_id
        ORDER BY i.data_inserimento DESC
    """

    risultati = db.execute(text(query)).fetchall()
    return [dict(r._mapping) for r in risultati]




@router.put("/stato-usato/{id_auto}", tags=["AZLease"])
async def aggiorna_stato_auto_usata(
    id_auto: str,
    payload: dict = Body(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    azione = payload.get("azione")

    result = db.execute(text("""
        SELECT id_usatoin FROM azlease_usatoauto WHERE id = :auto_id
    """), {"auto_id": id_auto}).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Auto non trovata")

    id_usatoin = result.id_usatoin
    now = datetime.utcnow()

    if azione == "opzione":
        db.execute(text("""
            UPDATE azlease_usatoin
            SET opzionato_da = :user_id, opzionato_il = :data
            WHERE id = :id_usatoin
        """), {
            "user_id": str(user.id),
            "data": now,
            "id_usatoin": id_usatoin
        })

    elif azione == "vendita":
        db.execute(text("""
            UPDATE azlease_usatoin
            SET venduto_da = :user_id, venduto_il = :data, visibile = false
            WHERE id = :id_usatoin
        """), {
            "user_id": str(user.id),
            "data": now,
            "id_usatoin": id_usatoin
        })

    elif azione == "rimetti_in_vendita":
        db.execute(text("""
            UPDATE azlease_usatoin
            SET venduto_da = NULL, venduto_il = NULL, visibile = true
            WHERE id = :id_usatoin
        """), {"id_usatoin": id_usatoin})



    elif azione == "elimina":
        db.execute(text("""
            UPDATE azlease_usatoin
            SET visibile = false
            WHERE id = :id_usatoin
        """), {"id_usatoin": id_usatoin})

    elif azione == "visibile":
        db.execute(text("""
            UPDATE azlease_usatoin
            SET visibile = true
            WHERE id = :id_usatoin
        """), {"id_usatoin": id_usatoin})
    
    elif azione == "modifica_prezzo":
        nuovo_prezzo = payload.get("nuovo_prezzo")
        try:
            nuovo_prezzo = float(nuovo_prezzo)
            if nuovo_prezzo <= 0:
                raise ValueError()
        except:
            raise HTTPException(status_code=400, detail="Prezzo non valido")

        db.execute(text("""
            UPDATE azlease_usatoin
            SET prezzo_vendita = :prezzo
            WHERE id = :id_usatoin
        """), {"prezzo": nuovo_prezzo, "id_usatoin": id_usatoin})


    elif azione == "rimuovi_opzione":
        db.execute(text("""
            UPDATE azlease_usatoin
            SET opzionato_da = NULL, opzionato_il = NULL
            WHERE id = :id_usatoin
        """), {"id_usatoin": id_usatoin})



    else:
        raise HTTPException(status_code=400, detail="Azione non valida")

    db.commit()

    return {"message": f"Stato aggiornato con successo ({azione})"}



class QuotazioneInput(BaseModel):
    id_auto: uuid.UUID
    mesi: int
    km: int
    anticipo: int
    prv: int  # percentuale intera (es.: 5 per indicare 5%)
    costo: int
    vendita: int
    buyback: int
    canone: int


@router.post("/quotazioni", tags=["AZLease"])
def inserisci_quotazione(
    data: QuotazioneInput, 
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    nuova_quotazione = AZLeaseQuotazioni(
        id_auto=data.id_auto,
        mesi=data.mesi,
        km=data.km,
        anticipo=data.anticipo,
        prv=data.prv,
        costo=data.costo,
        vendita=data.vendita,
        buyback=data.buyback,
        canone=data.canone
    )

    try:
        db.add(nuova_quotazione)
        db.commit()
        db.refresh(nuova_quotazione)
        return {
            "success": True,
            "quotazione": QuotazioneOut.from_orm(nuova_quotazione)
        }
    except Exception as e:
        db.rollback()
        print("⚠️ Errore:", e)
        raise HTTPException(status_code=500, detail=str(e))


    # Modello Pydantic di risposta
class QuotazioneOut(BaseModel):
    id: uuid.UUID
    id_auto: uuid.UUID
    mesi: int
    km: int
    anticipo: int
    prv: Optional[int] = None
    costo: Optional[int] = None
    vendita: Optional[int] = None
    buyback: Optional[int] = None
    canone: int
    data_inserimento: datetime

    class Config:
        orm_mode = True  # ← aggiungi questa riga esatta!


from pprint import pprint

@router.get("/quotazioni/{id_auto}", tags=["AZLease"], response_model=List[QuotazioneOut])
def get_quotazioni(
    id_auto: uuid.UUID,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()

    quotazioni = db.query(AZLeaseQuotazioni).filter(AZLeaseQuotazioni.id_auto == id_auto).all()

    if not quotazioni:
        raise HTTPException(status_code=404, detail="Nessuna quotazione trovata per questa auto.")

    # Aggiungi questo:
    print("Quotazioni SQLAlchemy originali:")
    for q in quotazioni:
        pprint(vars(q))

    try:
        risultato = [QuotazioneOut.from_orm(q).dict() for q in quotazioni]
    except Exception as e:
        print("❌ Errore durante from_orm:", e)
        raise

    print("Output finale da restituire al frontend:")
    pprint(risultato)

    return risultato or []



class QuotazioneUpdate(BaseModel):
    mesi: Optional[int] = None
    km: Optional[int] = None
    anticipo: Optional[int] = None
    prv: Optional[int] = None
    costo: Optional[int] = None
    vendita: Optional[int] = None
    buyback: Optional[int] = None
    canone: Optional[int] = None

@router.patch("/quotazioni/{id}", tags=["AZLease"])
def modifica_quotazione(
    id: uuid.UUID, 
    data: QuotazioneUpdate, 
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    if user.role.lower() not in ["superadmin", "admin", "admin_team"]:
        raise HTTPException(status_code=403, detail="Non autorizzato.")

    quotazione = db.query(AZLeaseQuotazioni).filter(AZLeaseQuotazioni.id == id).first()

    if not quotazione:
        raise HTTPException(status_code=404, detail="Quotazione non trovata.")

    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(quotazione, key, value)

    db.commit()
    db.refresh(quotazione)

    return QuotazioneOut.from_orm(quotazione)

# DELETE FOTO
@router.delete("/foto-usato/{foto_id}", tags=["AZLease"])
def elimina_foto_usato(
    foto_id: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    foto = db.execute(text("""
        SELECT foto, auto_id FROM azlease_usatoimg WHERE id = :foto_id
    """), {"foto_id": foto_id}).fetchone()

    if not foto:
        raise HTTPException(status_code=404, detail="Foto non trovata")

    auto = db.execute(text("""
        SELECT id_usatoin FROM azlease_usatoauto WHERE id = :auto_id
    """), {"auto_id": foto.auto_id}).fetchone()

    inserimento = db.execute(text("""
        SELECT admin_id, dealer_id FROM azlease_usatoin WHERE id = :id_usatoin
    """), {"id_usatoin": auto.id_usatoin}).fetchone()

    user_is_owner = (
        user.role.lower() in ["superadmin", "admin", "admin_team"]
        or (is_dealer_user(user) and get_dealer_id(user) == inserimento.dealer_id)
    )

    if not user_is_owner:
        raise HTTPException(status_code=403, detail="Non autorizzato a eliminare questa foto")

    # Rimuovi da storage
    supabase_client.storage.from_("auto-usate").remove([foto.foto.split("auto-usate/")[-1]])

    # Rimuovi dal database
    db.execute(text("DELETE FROM azlease_usatoimg WHERE id = :foto_id"), {"foto_id": foto_id})
    db.commit()

    return {"message": "Foto eliminata correttamente"}


# DELETE PERIZIA
@router.delete("/perizie-usato/{perizia_id}", tags=["AZLease"])
def elimina_perizia_usato(
    perizia_id: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    perizia = db.execute(text("""
        SELECT foto, auto_id FROM azlease_usatodanni WHERE id = :perizia_id
    """), {"perizia_id": perizia_id}).fetchone()

    if not perizia:
        raise HTTPException(status_code=404, detail="Perizia non trovata")

    auto = db.execute(text("""
        SELECT id_usatoin FROM azlease_usatoauto WHERE id = :auto_id
    """), {"auto_id": perizia.auto_id}).fetchone()

    inserimento = db.execute(text("""
        SELECT admin_id, dealer_id FROM azlease_usatoin WHERE id = :id_usatoin
    """), {"id_usatoin": auto.id_usatoin}).fetchone()

    user_is_owner = (
        user.role.lower() in ["superadmin", "admin", "admin_team"]
        or (is_dealer_user(user) and get_dealer_id(user) == inserimento.dealer_id)
    )

    if not user_is_owner:
        raise HTTPException(status_code=403, detail="Non autorizzato a eliminare questa perizia")

    # Rimuovi da storage
    supabase_client.storage.from_("auto-usate").remove([perizia.foto.split("auto-usate/")[-1]])

    # Rimuovi dal database
    db.execute(text("DELETE FROM azlease_usatodanni WHERE id = :perizia_id"), {"perizia_id": perizia_id})
    db.commit()

    return {"message": "Perizia eliminata correttamente"}

@router.get("/usato-pubblico/{slug}", tags=["Public AZLease"])
async def lista_usato_pubblico(
    slug: str,
    db: Session = Depends(get_db)
):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(404, f"Slug '{slug}' non trovato")

    user_id = settings.dealer_id or settings.admin_id
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utente non trovato per questo slug")

    admin_id = user.parent_id if user.role == "dealer" and user.parent_id else user.id

    query = """
        SELECT 
            a.id AS id_auto,
            d.marca_nome AS marca,
            d.allestimento,
            a.anno_immatricolazione,
            a.km_certificati,
            a.colore,
            i.prezzo_vendita,
            i.iva_esposta,
            img.foto AS foto_principale
        FROM azlease_usatoauto a
        JOIN azlease_usatoin i ON i.id = a.id_usatoin
        LEFT JOIN mnet_dettagli_usato d ON d.codice_motornet_uni = a.codice_motornet
        LEFT JOIN azlease_usatoimg img ON img.auto_id = a.id AND img.principale = TRUE
        WHERE i.admin_id = :admin_id
          AND i.visibile = TRUE
          AND i.venduto_da IS NULL
        ORDER BY i.data_inserimento DESC
    """
    risultati = db.execute(text(query), {"admin_id": admin_id}).fetchall()
    return [dict(r._mapping) for r in risultati]

@router.get("/usato-pubblico/{slug}/{id_auto}", tags=["Public AZLease"])
async def dettaglio_usato_pubblico(
    slug: str,
    id_auto: str,
    db: Session = Depends(get_db)
):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(404, f"Slug '{slug}' non trovato")

    user_id = settings.dealer_id or settings.admin_id
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utente non trovato per questo slug")

    auto = db.execute(text("""
        SELECT a.*, i.prezzo_vendita, i.iva_esposta, i.visibile
        FROM azlease_usatoauto a
        JOIN azlease_usatoin i ON i.id = a.id_usatoin
        WHERE a.id = :id_auto AND i.visibile = TRUE AND i.venduto_da IS NULL
    """), {"id_auto": id_auto}).fetchone()

    if not auto:
        raise HTTPException(404, "Auto non trovata o non visibile")

    immagini = db.execute(text("""
        SELECT foto, principale FROM azlease_usatoimg WHERE auto_id = :id_auto
    """), {"id_auto": id_auto}).fetchall()

    dettagli = db.execute(text("""
        SELECT * FROM mnet_dettagli_usato WHERE codice_motornet_uni = :codice
    """), {"codice": auto.codice_motornet}).fetchone()

    return {
        "auto": dict(auto._mapping),
        "immagini": [dict(i._mapping) for i in immagini],
        "dettagli": dict(dettagli._mapping) if dettagli else {}
    }

@router.get("/usato-pubblico/{slug}/{id_auto}/foto", tags=["Public AZLease"])
async def foto_usato_pubblico(
    slug: str,
    id_auto: str,
    db: Session = Depends(get_db)
):
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(404, f"Slug '{slug}' non trovato.")

    user_id = settings.dealer_id or settings.admin_id
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utente non trovato per questo slug.")

    # ✅ verifica che l'auto appartenga a questo admin e sia visibile
    auto = db.execute(text("""
        SELECT i.id
        FROM azlease_usatoauto a
        JOIN azlease_usatoin i ON i.id = a.id_usatoin
        WHERE a.id = :id_auto
          AND i.admin_id = :admin_id
          AND i.visibile = TRUE
          AND i.venduto_da IS NULL
    """), {"id_auto": id_auto, "admin_id": user.id}).fetchone()

    if not auto:
        raise HTTPException(404, "Auto non trovata o non visibile.")

    immagini = db.execute(text("""
        SELECT id, foto, principale
        FROM azlease_usatoimg
        WHERE auto_id = :id_auto
        ORDER BY principale DESC
    """), {"id_auto": id_auto}).fetchall()

    return {
        "auto_id": id_auto,
        "immagini": [
            {"id": i.id, "foto_url": i.foto, "principale": i.principale}
            for i in immagini
        ]
    }
