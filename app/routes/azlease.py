﻿from fastapi import Depends, HTTPException, APIRouter
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT
from app.database import get_db
from app.models import User, AZUsatoInsertRequest
from app.schemas import AutoUsataCreate
import uuid
from datetime import datetime
from sqlalchemy import text
import requests
import httpx



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
        dealer_id = str(user.id)
        admin_id = str(user.parent_id)
    else:  # admin o superadmin
        admin_id = str(user.id)

    # 1️⃣ Inserisci in AZLease_UsatoIN
    usatoin_id = uuid.uuid4()
    db.execute(text("""
        INSERT INTO azlease_usatoin (
            id, dealer_id, admin_id, data_inserimento, data_ultima_modifica, prezzo_costo, prezzo_vendita
        )
        VALUES (
            :id, :dealer_id, :admin_id, :inserimento, :modifica, :costo, :vendita
        )
    """), {
        "id": str(usatoin_id),
        "dealer_id": dealer_id if dealer_id else None,
        "admin_id": admin_id,  # nessuna conversione UUID qui!
        "inserimento": datetime.utcnow(),
        "modifica": datetime.utcnow(),
        "costo": payload.prezzo_costo,
        "vendita": payload.prezzo_vendita
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
    insert_values = {
        "id": str(uuid.uuid4()),
        "auto_id": str(auto_id),
        "codice_motornet": data["modello"].get("codiceMotornetUnivoco"),
        "codice_modello": data["modello"]["codDescModello"].get("codice"),
        "modello": data["modello"].get("modello"),
        "allestimento": data["modello"].get("allestimento"),
        "immagine": data["modello"].get("immagine"),
        "codice_costruttore": data["modello"].get("codiceCostruttore"),
        "codice_motore": data["modello"].get("codiceMotore"),
        "data_listino": data["modello"].get("dataListino"),
        "prezzo_listino": data["modello"].get("prezzoListino"),
        "prezzo_accessori": data["modello"].get("prezzoAccessori"),
        "marca_nome": data["modello"]["marca"].get("nome"),
        "marca_acronimo": data["modello"]["marca"].get("acronimo"),
        "gamma_codice": data["modello"]["gammaModello"].get("codice"),
        "gamma_descrizione": data["modello"]["gammaModello"].get("descrizione"),
        "gruppo_storico": data["modello"]["gruppoStorico"].get("descrizione"),
        "serie_gamma": data["modello"]["serieGamma"].get("descrizione"),
        "categoria": data["modello"]["categoria"].get("descrizione"),
        "segmento": data["modello"]["segmento"].get("descrizione"),
        "tipo": data["modello"]["tipo"].get("descrizione"),
        "tipo_motore": data["modello"].get("tipoMotore"),
        "descrizione_motore": data["modello"].get("descrizioneMotore"),
        "euro": data["modello"].get("euro"),
        "cilindrata": data["modello"].get("cilindrata"),
        "cavalli_fiscali": data["modello"].get("cavalliFiscali"),
        "hp": data["modello"].get("hp"),
        "kw": data["modello"].get("kw"),
        "emissioni_co2": data["modello"].get("emissioniCo2"),
        "consumo_urbano": data["modello"].get("consumoUrbano"),
        "consumo_extraurbano": data["modello"].get("consumoExtraurbano"),
        "consumo_medio": data["modello"].get("consumoMedio"),
        "accelerazione": data["modello"].get("accelerazione"),
        "velocita_max": data["modello"].get("velocita"),
        "descrizione_marce": data["modello"].get("descrizioneMarce"),
        "cambio": data["modello"]["cambio"].get("descrizione"),
        "trazione": data["modello"]["trazione"].get("descrizione"),
        "passo": data["modello"].get("passo"),
        "porte": data["modello"].get("porte"),
        "posti": data["modello"].get("posti"),
        "altezza": data["modello"].get("altezza"),
        "larghezza": data["modello"].get("larghezza"),
        "lunghezza": data["modello"].get("lunghezza"),
        "bagagliaio": data["modello"].get("bagagliaio"),
        "pneumatici_anteriori": data["modello"].get("pneumaticiAnteriori"),
        "pneumatici_posteriori": data["modello"].get("pneumaticiPosteriori"),
        "coppia": data["modello"].get("coppia"),
        "numero_giri": data["modello"].get("numeroGiri"),
        "cilindri": data["modello"].get("cilindri"),
        "valvole": data["modello"].get("valvole"),
        "peso": data["modello"].get("peso"),
        "peso_vuoto": data["modello"].get("pesoVuoto"),
        "massa_p_carico": data["modello"].get("massaPCarico"),
        "portata": data["modello"].get("portata"),
        "tipo_guida": data["modello"].get("tipoGuida"),
        "neo_patentati": data["modello"].get("neoPatentati"),
        "alimentazione": data["modello"]["alimentazione"].get("descrizione"),
        "architettura": data["modello"]["architettura"].get("descrizione"),
        "ricarica_standard": data["modello"].get("ricaricaStandard"),
        "ricarica_veloce": data["modello"].get("ricaricaVeloce"),
        "sospensioni_pneumatiche": bool(data["modello"].get("sospPneum")),
        "emissioni_urbe": data["modello"].get("emissUrbe"),
        "emissioni_extraurb": data["modello"].get("emissExtraurb"),
        "created_at": datetime.utcnow()
    }

    db.execute(insert_query, insert_values)
    db.commit()

    return {
        "message": "Auto inserita correttamente",
        "id_auto": str(auto_id),
        "id_inserimento": str(usatoin_id)
    }
