from fastapi import Depends, HTTPException, APIRouter, UploadFile, File, status, Body, Form, Query
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import get_db, supabase_client, SUPABASE_URL
from app.models import User, AZUsatoInsertRequest, AZLeaseQuotazioni
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

    # Determina admin_id e dealer_id in base al ruolo
    dealer_id = get_dealer_id(user) if is_dealer_user(user) else None
    admin_id = get_admin_id(user)

    usatoin_id = uuid.uuid4()
    db.execute(text("""
        INSERT INTO azlease_usatoin (
            id, dealer_id, admin_id, data_inserimento, data_ultima_modifica, prezzo_costo, prezzo_vendita, visibile,
            opzionato_da, opzionato_il, venduto_da, venduto_il
        )
        VALUES (
            :id, :dealer_id, :admin_id, :inserimento, :modifica, :costo, :vendita, :visibile,
            :opzionato_da, :opzionato_il, :venduto_da, :venduto_il
        )
    """), {
        "id": str(usatoin_id),
        "dealer_id": int(dealer_id) if dealer_id else None,
        "admin_id": int(admin_id),
        "inserimento": datetime.utcnow(),
        "modifica": datetime.utcnow(),
        "costo": payload.prezzo_costo,
        "vendita": payload.prezzo_vendita,
        "opzionato_da": payload.opzionato_da,
        "opzionato_il": payload.opzionato_il,
        "venduto_da": payload.venduto_da,
        "venduto_il": payload.venduto_il,
        "visibile": payload.visibile
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


     # 🌐 Richiesta API esterna per i dettagli auto
    token_jwt = Authorize._token
    headers = {"Authorization": f"Bearer {token_jwt}"}
    url = f"https://coreapi-production-ca29.up.railway.app/api/usato/motornet/dettagli/{payload.codice_motornet}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=30)

    if response.status_code != 200:
        db.rollback()
        raise HTTPException(status_code=404, detail="Errore recupero dettagli auto da Motornet.")

    data = response.json()
    modello = data.get("modello") or {}

    insert_query = text("""
    INSERT INTO azlease_usatoautodetails (
        id, auto_id, codice_motornet, codice_modello, modello, allestimento, immagine,
        codice_costruttore, codice_motore, data_listino, prezzo_listino, prezzo_accessori,
        marca_nome, marca_acronimo, gamma_codice, gamma_descrizione, gruppo_storico,
        serie_gamma, categoria, segmento, tipo, tipo_motore, descrizione_motore, euro,
        cilindrata, cavalli_fiscali, hp, kw, emissioni_co2, consumo_urbano, consumo_extraurbano,
        consumo_medio, accelerazione, velocita_max, descrizione_marce, cambio, trazione, passo,
        porte, posti, altezza, larghezza, lunghezza, bagagliaio, pneumatici_anteriori,
        pneumatici_posteriori, coppia, numero_giri, cilindri, valvole, peso, peso_vuoto,
        massa_p_carico, portata, tipo_guida, neo_patentati, alimentazione, architettura,
        ricarica_standard, ricarica_veloce, sospensioni_pneumatiche, emissioni_urbe,
        emissioni_extraurb, created_at
    ) VALUES (
        :id, :auto_id, :codice_motornet, :codice_modello, :modello, :allestimento, :immagine,
        :codice_costruttore, :codice_motore, :data_listino, :prezzo_listino, :prezzo_accessori,
        :marca_nome, :marca_acronimo, :gamma_codice, :gamma_descrizione, :gruppo_storico,
        :serie_gamma, :categoria, :segmento, :tipo, :tipo_motore, :descrizione_motore, :euro,
        :cilindrata, :cavalli_fiscali, :hp, :kw, :emissioni_co2, :consumo_urbano, :consumo_extraurbano,
        :consumo_medio, :accelerazione, :velocita_max, :descrizione_marce, :cambio, :trazione, :passo,
        :porte, :posti, :altezza, :larghezza, :lunghezza, :bagagliaio, :pneumatici_anteriori,
        :pneumatici_posteriori, :coppia, :numero_giri, :cilindri, :valvole, :peso, :peso_vuoto,
        :massa_p_carico, :portata, :tipo_guida, :neo_patentati, :alimentazione, :architettura,
        :ricarica_standard, :ricarica_veloce, :sospensioni_pneumatiche, :emissioni_urbe,
        :emissioni_extraurb, :created_at
    )
""")



    # Flattening del JSON
        
    modello = data.get("modello") or {}

    insert_values = {
        "id": str(uuid.uuid4()),
        "auto_id": str(auto_id),
        "codice_motornet": modello.get("codiceMotornetUnivoco"),
        "codice_modello": (modello.get("codDescModello") or {}).get("codice"),
        "modello": modello.get("modello"),
        "allestimento": modello.get("allestimento"),
        "immagine": modello.get("immagine"),
        "codice_costruttore": modello.get("codiceCostruttore"),
        "codice_motore": modello.get("codiceMotore"),
        "data_listino": modello.get("dataListino"),
        "prezzo_listino": modello.get("prezzoListino"),
        "prezzo_accessori": modello.get("prezzoAccessori"),
        "marca_nome": (modello.get("marca") or {}).get("nome"),
        "marca_acronimo": (modello.get("marca") or {}).get("acronimo"),
        "gamma_codice": (modello.get("gammaModello") or {}).get("codice"),
        "gamma_descrizione": (modello.get("gammaModello") or {}).get("descrizione"),
        "gruppo_storico": (modello.get("gruppoStorico") or {}).get("descrizione"),
        "serie_gamma": (modello.get("serieGamma") or {}).get("descrizione"),
        "categoria": (modello.get("categoria") or {}).get("descrizione"),
        "segmento": (modello.get("segmento") or {}).get("descrizione"),
        "tipo": (modello.get("tipo") or {}).get("descrizione"),
        "tipo_motore": modello.get("tipoMotore"),
        "descrizione_motore": modello.get("descrizioneMotore"),
        "euro": modello.get("euro"),
        "cilindrata": modello.get("cilindrata"),
        "cavalli_fiscali": modello.get("cavalliFiscali"),
        "hp": modello.get("hp"),
        "kw": modello.get("kw"),
        "emissioni_co2": modello.get("emissioniCo2"),
        "consumo_urbano": modello.get("consumoUrbano"),
        "consumo_extraurbano": modello.get("consumoExtraurbano"),
        "consumo_medio": modello.get("consumoMedio"),
        "accelerazione": modello.get("accelerazione"),
        "velocita_max": modello.get("velocita"),
        "descrizione_marce": modello.get("descrizioneMarce"),
        "cambio": (modello.get("cambio") or {}).get("descrizione"),
        "trazione": (modello.get("trazione") or {}).get("descrizione"),
        "passo": modello.get("passo"),
        "porte": modello.get("porte"),
        "posti": modello.get("posti"),
        "altezza": modello.get("altezza"),
        "larghezza": modello.get("larghezza"),
        "lunghezza": modello.get("lunghezza"),
        "bagagliaio": modello.get("bagagliaio"),
        "pneumatici_anteriori": modello.get("pneumaticiAnteriori"),
        "pneumatici_posteriori": modello.get("pneumaticiPosteriori"),
        "coppia": modello.get("coppia"),
        "numero_giri": modello.get("numeroGiri"),
        "cilindri": modello.get("cilindri"),
        "valvole": modello.get("valvole"),
        "peso": modello.get("peso"),
        "peso_vuoto": modello.get("pesoVuoto"),
        "massa_p_carico": modello.get("massaPCarico"),
        "portata": modello.get("portata"),
        "tipo_guida": modello.get("tipoGuida"),
        "neo_patentati": modello.get("neoPatentati"),
        "alimentazione": (modello.get("alimentazione") or {}).get("descrizione"),
        "architettura": (modello.get("architettura") or {}).get("descrizione"),
        "ricarica_standard": modello.get("ricaricaStandard"),
        "ricarica_veloce": modello.get("ricaricaVeloce"),
        "sospensioni_pneumatiche": bool(modello.get("sospPneum")),
        "emissioni_urbe": modello.get("emissUrbe"),
        "emissioni_extraurb": modello.get("emissExtraurb"),
        "created_at": datetime.utcnow()
    }


    db.execute(insert_query, insert_values)
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
async def get_foto_usato(auto_id: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Restituisce la lista di immagini associate a un'auto."""
    Authorize.jwt_required()

    immagini = db.execute(text("""
        SELECT id, foto FROM azlease_usatoimg WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchall()

    return {"auto_id": auto_id, "immagini": [{"id": img.id, "foto_url": img.foto} for img in immagini]}

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
    dettagli = db.execute(text("""
        SELECT * FROM azlease_usatoautodetails WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchone()

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
    visibilita: Optional[str] = Query(None, description="Opzioni: visibili, non_visibili, tutte"),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    filtro = ""  # Default: nessun filtro

    if user.role == "superadmin":
        filtro = ""  # nessun filtro, vede tutto
    elif is_admin_user(user):
        admin_id = get_admin_id(user)
        dealer_ids = db.execute(text("SELECT id FROM utenti WHERE parent_id = :admin_id"), {
            "admin_id": admin_id
        }).fetchall()
        ids = [str(admin_id)] + [str(d.id) for d in dealer_ids]
        filtro = f"AND i.admin_id IN ({','.join(ids)})"
    elif is_dealer_user(user):
        filtro = "AND i.visibile = TRUE"
    else:
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")

    visibile_filter = ""

    if user.role.lower() in ["superadmin", "admin", "admin_team"]:
        if visibilita == "visibili":
            visibile_filter = "AND i.visibile = TRUE"
        elif visibilita == "non_visibili":
            visibile_filter = "AND i.visibile = FALSE"

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
                    u_opz.ragione_sociale AS opzionato_da_nome,  -- ✅ ragione sociale dell'utente che ha opzionato
                    i.venduto_da
                FROM azlease_usatoauto a
                JOIN azlease_usatoin i ON i.id = a.id_usatoin
                LEFT JOIN azlease_usatoautodetails d ON d.auto_id = a.id
                LEFT JOIN utenti u_admin ON u_admin.id = i.admin_id
                LEFT JOIN utenti u_dealer ON u_dealer.id = i.dealer_id
                LEFT JOIN utenti u_opz ON u_opz.id = i.opzionato_da  -- ✅ join per ottenere la ragione sociale
                LEFT JOIN azlease_usatodanni dn ON dn.auto_id = a.id
                GROUP BY 
                    a.id, d.marca_nome, d.allestimento, a.km_certificati, a.colore, 
                    i.visibile, i.data_inserimento, a.anno_immatricolazione, 
                    u_admin.nome, u_admin.cognome, u_dealer.nome, u_dealer.cognome, 
                    i.prezzo_vendita, i.opzionato_da, i.opzionato_il, u_opz.ragione_sociale, i.venduto_da
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
            SET venduto_da = :user_id, venduto_il = :data
            WHERE id = :id_usatoin
        """), {
            "user_id": str(user.id),
            "data": now,
            "id_usatoin": id_usatoin
        })

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

    # 🔧 AGGIUNGI QUESTO:
    elif azione == "rimuovi_opzione":
        if user.role.lower() in ["admin", "admin_team", "superadmin"]:
            db.execute(text("""
                UPDATE azlease_usatoin
                SET opzionato_da = NULL, opzionato_il = NULL
                WHERE id = :id_usatoin
            """), {"id_usatoin": id_usatoin})
        else:
            raise HTTPException(status_code=403, detail="Non autorizzato")

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

    return risultato



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
