from fastapi import APIRouter, HTTPException, Depends
import requests
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.routes.auth import get_current_user
from app.database import get_db  # ✅ Import corretto per il DB
from app.models import User, MnetModelli, MnetMarcaUsato, MnetModelloUsato
from datetime import datetime
import httpx
from app.utils.modelli import pulisci_modello

router_generic = APIRouter()
router_usato = APIRouter(prefix="/usato/motornet")
router_nuovo = APIRouter(prefix="/nuovo/motornet")


# Configurazioni API Motornet
MOTORN_AUTH_URL = "https://webservice.motornet.it/auth/realms/webservices/protocol/openid-connect/token"
MOTORN_MARCHE_URL = "https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/marche"
# NUOVO - Endpoint Motornet per veicoli NUOVI
MOTORN_NUOVO_MARCHE_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/marche"
MOTORN_NUOVO_MODELLI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/marca/modelli"
MOTORN_NUOVO_ALLESTIMENTI_URL = "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/modello/versioni"

# Credenziali API Motornet
MOTORN_CLIENT_ID = "azure447"
MOTORN_CLIENT_SECRET = "azwsn557"

import time

cached_token = None
token_expiry = 0

def get_motornet_token():
    """Ottiene e memorizza il token di accesso da Motornet per evitare richieste ripetute"""
    global cached_token, token_expiry

    # Se abbiamo un token valido, lo riutilizziamo
    if cached_token and time.time() < token_expiry:
        print("🔍 DEBUG: Riutilizzo token esistente")
        return cached_token

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    payload = {
        "grant_type": "password",
        "client_id": "webservice",
        "username": MOTORN_CLIENT_ID,
        "password": MOTORN_CLIENT_SECRET
    }

    response = requests.post(MOTORN_AUTH_URL, headers=headers, data=payload)

    print(f"🔍 DEBUG: Status Code Token Motornet = {response.status_code}")

    if response.status_code == 200:
        token_data = response.json()
        cached_token = token_data.get("access_token")
        token_expiry = time.time() + token_data.get("expires_in", 300) - 10  # Riduciamo 10 sec per sicurezza

        print(f"🔍 DEBUG: Nuovo token salvato: {cached_token}")
        return cached_token
    
    print(f"❌ DEBUG: Errore nel recupero del token: {response.text}")
    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero del token")


@router_usato.get("/marche", tags=["Usato"])
async def get_marche_usato(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    marche = db.query(
        MnetMarcaUsato.acronimo,
        MnetMarcaUsato.nome,
        MnetMarcaUsato.logo
    ).order_by(MnetMarcaUsato.nome).all()

    return [
        {
            "acronimo": row.acronimo,
            "nome": row.nome,
            "logo": row.logo
        } for row in marche
    ]


@router_usato.get("/modelli/{codice_marca}", tags=["Usato"])
async def get_modelli_usato(
    codice_marca: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    modelli = db.query(MnetModelloUsato).filter(
        MnetModelloUsato.marca_acronimo == codice_marca
    ).order_by(MnetModelloUsato.descrizione).all()

    return [
        {
            "codice": m.codice_modello,
            "descrizione": m.descrizione,
            "inizio_produzione": m.inizio_produzione,
            "fine_produzione": m.fine_produzione,
            "inizio_commercializzazione": m.inizio_commercializzazione,
            "fine_commercializzazione": m.fine_commercializzazione,
            "gruppo_storico": m.gruppo_storico,
            "serie_gamma": m.serie_gamma,
            "codice_desc_modello": m.codice_desc_modello,
            "descrizione_dettagliata": m.descrizione_dettagliata,
            "segmento": m.segmento,
            "tipo": m.tipo
        } for m in modelli
    ]



@router_usato.get("/allestimenti/{codice_marca}/{codice_modello}", tags=["Usato"])
async def get_allestimenti_usato(
    codice_marca: str,
    codice_modello: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    # ✅ Verifica autenticazione JWT
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    # ✅ Controllo utente esistente
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    # ✅ Query al database
    query = text("""
        SELECT 
            codice_motornet_uni,
            versione,
            alimentazione,
            cambio,
            trazione,
            cilindrata,
            kw,
            cv
        FROM mnet_allestimenti_usato
        WHERE acronimo_marca = :codice_marca
          AND codice_desc_modello = :codice_modello
        ORDER BY versione
    """)

    result = db.execute(query, {
        "codice_marca": codice_marca,
        "codice_modello": codice_modello
    }).fetchall()

    # ✅ Mappatura risultato
    return [
        {
            "codice_univoco": row.codice_motornet_uni,
            "versione": row.versione,
            "alimentazione": row.alimentazione,
            "cambio": row.cambio,
            "trazione": row.trazione,
            "cilindrata": row.cilindrata,
            "kw": row.kw,
            "cv": row.cv
        }
        for row in result
    ]

@router_usato.get("/dettagli/{codice_motornet}", tags=["Usato"])
async def get_dettagli_usato(
    codice_motornet: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    # ✅ Autenticazione
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    # ✅ Query
    result = db.execute(text("""
        SELECT * FROM mnet_dettagli_usato
        WHERE codice_motornet_uni = :codice
    """), {"codice": codice_motornet}).mappings().fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Dettaglio non trovato")

    m = dict(result)

    # ✅ Wrapping compatibile con frontend
    m["alimentazione"] = {"descrizione": m["alimentazione"]} if m.get("alimentazione") else None
    m["cambio"] = {"descrizione": m["cambio"]} if m.get("cambio") else None
    m["trazione"] = {"descrizione": m["trazione"]} if m.get("trazione") else None
    m["architettura"] = {"descrizione": m["architettura"]} if m.get("architettura") else None

    if m.get("segmento"):
        m["segmento"] = {
            "codice": m["segmento"],
            "descrizione": m["segmento"]
        }

    if m.get("tipo"):
        m["tipo"] = {
            "codice": m["tipo"],
            "descrizione": m["tipo"]
        }

    # ✅ Risposta finale
    return {
        "modello": m
    }



@router_usato.get("/valutazione/{codice_motornet}/{anno_immatricolazione}/{mese_immatricolazione}", tags=["Motornet"])
async def get_valutazione_auto(
    codice_motornet: str,
    anno_immatricolazione: int,
    mese_immatricolazione: int,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """Recupera la quotazione base e il deprezzamento di un veicolo rispetto alla data di immatricolazione"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    # 📌 Impostiamo automaticamente la data di valutazione a OGGI
    oggi = datetime.today()
    anno_valutazione = oggi.year
    mese_valutazione = oggi.month

    motornet_url = (
        f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/valutazione/deprezzamento"
        f"?codice_motornet_uni={codice_motornet}"
        f"&anno_immatricolazione={anno_immatricolazione}"
        f"&mese_immatricolazione={mese_immatricolazione}"
        f"&anno_valutazione={anno_valutazione}"
        f"&mese_valutazione={mese_valutazione}"
    )

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Valutazione: {response.text}")  # 🔹 Stampa la risposta ricevuta

    if response.status_code == 200:
        data = response.json()
        return data  # 🔹 Restituiamo l'intero JSON senza modificarlo

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero della valutazione")

@router_usato.get("/marche/{anno}", tags=["Motornet"])
async def get_marche_per_anno_usato(anno: int, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera la lista delle marche per un anno specifico"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    motornet_url = f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/marche/{anno}"

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Marche per anno: {response.text}")  # 🔹 Stampa la risposta ricevuta

    if response.status_code == 200:
        data = response.json()

        # Estraggo solo i dati utili
        marche_pulite = [
            {
                "acronimo": marca.get("acronimo"),
                "nome": marca.get("nome")
            }
            for marca in data.get("marche", [])
        ]

        return marche_pulite

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero delle marche per l'anno specificato")

@router_usato.get("/accessori/{codice_motornet}/{anno}/{mese}", tags=["Motornet"])
async def get_accessori_auto_usato(
    codice_motornet: str,
    anno: int,
    mese: int,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """Recupera tutti gli accessori di un veicolo usato tramite il codice Motornet univoco"""
    Authorize.jwt_required()  # 🔹 Verifica il token JWT di CoreAPI
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()  # 🔹 Otteniamo il token da Motornet prima della richiesta

    headers = {
        "Authorization": f"Bearer {token}"
    }

    motornet_url = (
        f"https://webservice.motornet.it/api/v3_0/rest/public/usato/auto/accessori"
        f"?codice_motornet_uni={codice_motornet}"
        f"&anno={anno}"
        f"&mese={mese}"
    )

    response = requests.get(motornet_url, headers=headers)

    print(f"🔍 DEBUG: Risposta Motornet Accessori: {response.text}")  # 🔹 Stampa la risposta ricevuta

    if response.status_code == 200:
        data = response.json()
        return data  # 🔹 Restituiamo tutti i dati ricevuti senza modificarli

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero degli accessori del veicolo")

@router_nuovo.get("/marche", tags=["Motornet"])
async def get_marche_nuovo(Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera la lista delle marche per il nuovo dal nostro database locale"""
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    # 📌 Marche filtrate su 'utile = TRUE'
    marche = db.execute(text("""
        SELECT acronimo, nome, logo
        FROM mnet_marche
        WHERE utile IS TRUE
    """)).fetchall()

    return [
        {
            "acronimo": row.acronimo,
            "nome": row.nome,
            "logo": row.logo
        }
        for row in marche
    ]


@router_nuovo.get("/modelli/{codice_marca}", tags=["Motornet"])
async def get_modelli_nuovo(
    codice_marca: str,
    db: Session = Depends(get_db),
    Authorize: AuthJWT = Depends()
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    query = text("""
        SELECT 
            codice_modello,
            descrizione,
            inizio_produzione,
            fine_produzione,
            gruppo_storico_descrizione,
            serie_gamma_descrizione,
            cod_desc_modello_codice,
            cod_desc_modello_descrizione,
            inizio_commercializzazione,
            fine_commercializzazione
        FROM mnet_modelli
        WHERE marca_acronimo = :codice_marca
        AND fine_commercializzazione IS NULL
    """)

    result = db.execute(query, {"codice_marca": codice_marca}).fetchall()

    modelli = []
    for row in result:
        modelli.append({
            "codice": row.codice_modello,
            "descrizione": row.descrizione,
            "inizio_produzione": row.inizio_produzione,
            "fine_produzione": row.fine_produzione,
            "gruppo_storico": row.gruppo_storico_descrizione,
            "serie_gamma": row.serie_gamma_descrizione,
            "codice_desc_modello": row.cod_desc_modello_codice,
            "descrizione_dettagliata": row.cod_desc_modello_descrizione,
            "inizio_commercializzazione": row.inizio_commercializzazione,
            "fine_commercializzazione": row.fine_commercializzazione
        })

    return modelli



@router_nuovo.get("/versioni/{codice_marca}/{codice_modello}", tags=["Motornet"])
async def get_versioni_nuovo(
    codice_marca: str,
    codice_modello: str,
    codice_alimentazione: str = None,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    query = text("""
        SELECT 
            a.codice_motornet_uni,
            a.nome,
            a.data_da,
            a.data_a
        FROM mnet_allestimenti a
        LEFT JOIN mnet_dettagli d ON a.codice_motornet_uni = d.codice_motornet_uni
        WHERE a.codice_modello = :codice_modello
        AND (:alimentazione IS NULL OR d.alimentazione = :alimentazione)
        AND a.data_a IS NULL
    """)

    result = db.execute(query, {
        "codice_modello": codice_modello,
        "alimentazione": codice_alimentazione
    }).fetchall()

    versioni = [
        {
            "codice_univoco": row.codice_motornet_uni,
            "nome": row.nome,
            "da": row.data_da,
            "a": row.data_a,
            "inizio_produzione": row.data_da,
            "fine_produzione": row.data_a
        }
        for row in result
    ]

    return versioni


@router_nuovo.get("/dettagli/{codice_motornet}", tags=["Motornet"])
async def get_dettagli_auto_nuovo(
    codice_motornet: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    query = text("""
        SELECT * FROM mnet_dettagli
        WHERE codice_motornet_uni = :codice
    """)
    result = db.execute(query, {"codice": codice_motornet}).mappings().fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Dettaglio non trovato")

    # Wrappiamo i dati nel formato atteso dal frontend
    m = dict(result)

    return {
        "modello": {
            **m,
            "alimentazione": {"descrizione": m["alimentazione"]} if m.get("alimentazione") else None,
            "cambio": {"descrizione": m["cambio_descrizione"]} if m.get("cambio_descrizione") else None,
            "trazione": {"descrizione": m["trazione"]} if m.get("trazione") else None,
            "architettura": {"descrizione": m["architettura"]} if m.get("architettura") else None,
            "freni": {"descrizione": m["freni"]} if m.get("freni") else None,
            "segmento": {
                "codice": m["segmento"],
                "descrizione": m["segmento_descrizione"]
            } if m.get("segmento") else None,
            "tipo": {
                "codice": m["tipo"],
                "descrizione": m["tipo_descrizione"]
            } if m.get("tipo") else None
        }
    }   


@router_nuovo.get("/alimentazioni/{codice_modello}", tags=["Motornet"])
async def get_alimentazioni_nuovo(
    codice_modello: str,
    anno: int = None,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    query = text("""
        SELECT DISTINCT d.alimentazione
        FROM mnet_allestimenti a
        JOIN mnet_dettagli d ON a.codice_motornet_uni = d.codice_motornet_uni
        WHERE a.codice_modello = :codice_modello
        AND a.data_a IS NULL
        AND d.alimentazione IS NOT NULL
        ORDER BY d.alimentazione
    """)

    result = db.execute(query, {"codice_modello": codice_modello}).fetchall()

    alimentazioni = [
        {
            "codice": row.alimentazione,
            "descrizione": row.alimentazione
        }
        for row in result
    ]

    return alimentazioni




@router_nuovo.get("/accessori/{codice_motornet_uni}", tags=["Motornet"])
async def get_accessori_nuovo(
    codice_motornet_uni: str,
    anno: int = None,
    mese: int = None,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    # Imposto automaticamente anno e mese correnti se non passati
    if anno is None or mese is None:
        oggi = datetime.today()
        anno = anno or oggi.year
        mese = mese or oggi.month

    token = get_motornet_token()

    headers = {"Authorization": f"Bearer {token}"}

    motornet_url = (
        "https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/accessori"
        f"?codice_motornet_uni={codice_motornet_uni}&anno={anno}&mese={mese}"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(motornet_url, headers=headers)

    if response.status_code == 200:
        return response.json()

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero degli accessori del veicolo nuovo")


@router_nuovo.get("/messa-strada/{codice_univoco}", tags=["Motornet"])
async def get_messa_su_strada(codice_univoco: str, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    """Recupera il costo di messa su strada da Motornet per un veicolo NUOVO"""
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    token = get_motornet_token()
    headers = { "Authorization": f"Bearer {token}" }

    url = f"https://webservice.motornet.it/api/v3_0/rest/public/nuovo/auto/messa-strada?codice_motornet_uni={codice_univoco}"
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()

    raise HTTPException(status_code=response.status_code, detail="Errore nel recupero messa su strada")

@router_nuovo.get("/modelli", tags=["Motornet"])
async def get_tutti_modelli(db: Session = Depends(get_db)):
    modelli = db.query(
        MnetModelli.codice_modello,
        MnetModelli.marca_acronimo,
        MnetModelli.gruppo_storico_descrizione
    ).all()

    return [
        {
            "codice_modello": modello.codice_modello,
            "marca_acronimo": modello.marca_acronimo,
            "gruppo_storico": modello.gruppo_storico_descrizione
        }
        for modello in modelli
    ]







