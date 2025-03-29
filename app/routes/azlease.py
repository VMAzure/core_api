from fastapi import Depends, HTTPException, APIRouter, UploadFile, File, status, Body
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import get_db, supabase_client, SUPABASE_URL
from app.models import User, AZUsatoInsertRequest
from app.schemas import AutoUsataCreate
import uuid
from datetime import datetime
from sqlalchemy import text
import requests
import httpx
from typing import Optional

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

    if user.role not in ["dealer", "admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Ruolo non autorizzato")

    # Determina admin_id e dealer_id in base al ruolo
    dealer_id = None
    admin_id = None

    if user.role == "dealer":
        dealer_id = user.id  # int
        admin_id = user.parent_id
    else:
        admin_id = user.id

    # 1️⃣ Inserisci in AZLease_UsatoIN
    usatoin_id = uuid.uuid4()
    db.execute(text("""
        INSERT INTO azlease_usatoin (
            id, dealer_id, admin_id, data_inserimento, data_ultima_modifica, prezzo_costo, prezzo_vendita, visibile
        )
        VALUES (
            :id, :dealer_id, :admin_id, :inserimento, :modifica, :costo, :vendita, :visibile
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

    # 2️⃣ Inserisci in AZLease_UsatoAuto
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
        "usatoin_id": str(usatoin_id)  # Assicurati che usatoin_id sia passato come stringa, se richiesto dal database
    })

     # 🌐 Richiesta API esterna per i dettagli auto
    token_jwt = Authorize._token  # Ottieni il token JWT corrente

    headers = {
        "Authorization": f"Bearer {token_jwt}"
    }

    url = f"https://coreapi-production-ca29.up.railway.app/api/usato/motornet/dettagli/{payload.codice_motornet}"

    # Usa httpx per chiamata asincrona
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=30)

    if response.status_code != 200:
        db.rollback()
        raise HTTPException(status_code=404, detail="Errore recupero dettagli auto da Motornet.")

    data = response.json()

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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utente non autorizzato")

    if file.content_type not in ["image/png", "image/jpeg", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Formato immagine non supportato")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    file_name = f"auto-usate/{auto_id}_{timestamp}_{file.filename}"

    try:
        content = await file.read()

        # Upload su Supabase bucket "auto-usate"
        supabase_client.storage.from_("auto-usate").upload(
            file_name,
            content,
            {"content-type": file.content_type}
        )

        # URL pubblico
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/{file_name}"

        # Inserisci URL nella tabella AZLease_UsatoIMG
        img_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO azlease_usatoimg (id, auto_id, foto)
            VALUES (:id, :auto_id, :foto)
        """), {
            "id": img_id,
            "auto_id": auto_id,
            "foto": image_url
        })

        db.commit()

        return {"message": "Immagine caricata con successo", "image_url": image_url}

    except Exception as e:
        print(f"❌ Errore durante l'upload su Supabase: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")


@router.post("/perizie-usato", tags=["AZLease"])
async def upload_perizia_usato(
    auto_id: str,
    valore_perizia: float,
    descrizione: str,
    file: UploadFile = File(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utente non autorizzato")

    if file.content_type not in ["image/png", "image/jpeg", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Formato immagine non supportato")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    file_name = f"auto-usate/danni/{auto_id}_{timestamp}_{file.filename}"

    try:
        content = await file.read()

        # Upload foto danno in Supabase bucket "auto-usate"
        supabase_client.storage.from_("auto-usate").upload(
            file_name,
            content,
            {"content-type": file.content_type}
        )

        # URL pubblico dell'immagine
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/{file_name}"

        # Inserimento dati nella tabella AZLease_UsatoDANNI
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
        print(f"❌ Errore durante upload della perizia su Supabase: {e}")
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

    # 1️⃣ Recupera i dati dell'auto
    auto = db.execute(text("""
        SELECT * FROM azlease_usatoauto WHERE id = :auto_id
    """), {"auto_id": auto_id}).fetchone()

    if not auto:
        raise HTTPException(status_code=404, detail="Auto non trovata")

    # 5️⃣ Recupera TUTTI i dati da azlease_usatoin
    inserimento = db.execute(text("""
        SELECT * FROM azlease_usatoin
        WHERE id = (SELECT id_usatoin FROM azlease_usatoauto WHERE id = :auto_id)
    """), {"auto_id": auto_id}).fetchone()


    # 2️⃣ Recupera i dettagli tecnici
    dettagli = db.execute(text("""
        SELECT * FROM azlease_usatoautodetails WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchone()

    # 3️⃣ Recupera le immagini
    immagini = db.execute(text("""
        SELECT foto FROM azlease_usatoimg WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchall()

    # 4️⃣ Recupera i danni
    danni = db.execute(text("""
        SELECT foto, valore_perizia, descrizione FROM azlease_usatodanni WHERE auto_id = :auto_id
    """), {"auto_id": auto_id}).fetchall()

    return {
    "inserimento": dict(inserimento._mapping) if inserimento else {},
    "auto": dict(auto._mapping) if auto else {},
    "dettagli": dict(dettagli._mapping) if dettagli else {},
    "immagini": [img.foto for img in immagini],
    "danni": [{"foto": d.foto, "valore_perizia": d.valore_perizia, "descrizione": d.descrizione} for d in danni]
}

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

    # Recupera ID inserimento (usatoin) collegato a quest'auto
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
            "user_id": str(uuid.UUID(str(user.id))),
            "data": now,
            "id_usatoin": id_usatoin
        })

    elif azione == "elimina":
        db.execute(text("""
            UPDATE azlease_usatoin
            SET visibile = false
            WHERE id = :id_usatoin
        """), {"id_usatoin": id_usatoin})

    # 🔧 AGGIUNGI QUESTO:
    elif azione == "visibile":
        db.execute(text("""
            UPDATE azlease_usatoin
            SET visibile = true
            WHERE id = :id_usatoin
        """), {"id_usatoin": id_usatoin})


    else:
        raise HTTPException(status_code=400, detail="Azione non valida. Usa: opzione, vendita, elimina")


    db.commit()

    return {"message": f"Stato aggiornato con successo ({azione})"}


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

