from sqlalchemy.orm import Session
from app.models import SiteAdminSettings
from app.auth_helpers import is_dealer_user

def calcola_quotazione(offerta, quotazione, current_user, db: Session, settings_corrente: SiteAdminSettings):
   # print("🟦 [START] calcola_quotazione")
   # print("🔸 Offerta ID:", offerta.id_offerta)
   #print("🔸 Slug offerta:", offerta.slug)
   # print("🔸 Prezzo listino:", offerta.prezzo_listino)
   # print("🔸 Prezzo totale:", offerta.prezzo_totale)
   # print("🔸 solo_privati:", offerta.solo_privati)
   # print("🔸 Player ID:", offerta.id_player)

    if not offerta or not quotazione or not offerta.prezzo_listino:
   #     print("❌ Dati iniziali mancanti")
        return None, None, None, None

    # === Selezione canone base ===
    if offerta.solo_privati and quotazione.mesi_48_30:
        durata, km, canone_base = 48, 30000, quotazione.mesi_48_30
        fonte = "mesi_48_30"
    elif quotazione.mesi_36_10:
        durata, km, canone_base = 36, 10000, quotazione.mesi_36_10
        fonte = "mesi_36_10"
    elif quotazione.mesi_48_10:
        durata, km, canone_base = 48, 10000, quotazione.mesi_48_10
        fonte = "mesi_48_10"
    else:
    #    print("❌ Nessun canone base disponibile")
        return None, None, None, None

    # print(f"✅ Canone base selezionato da: {fonte}")
    # print(f"➡️ Canone base: {canone_base}, durata: {durata} mesi, km: {km}")

    try:
        canone_base = float(canone_base)
    except (TypeError, ValueError):
      # print("❌ Errore cast canone_base")
        return None, None, None, None

    prezzo_grezzo = offerta.prezzo_totale or offerta.prezzo_listino
    if not prezzo_grezzo:
      # print("❌ prezzo_grezzo mancante")
        return None, None, None, None

    try:
        prezzo_netto = float(prezzo_grezzo) / 1.22
    except (TypeError, ValueError):
      # print("❌ Errore cast prezzo_netto")
        return None, None, None, None

    # print("➡️ Prezzo netto calcolato:", prezzo_netto)

    # === Recupero settings admin ===
    settings_admin = (
        db.query(SiteAdminSettings)
        .filter(
            SiteAdminSettings.admin_id == int(offerta.id_admin),
            SiteAdminSettings.dealer_id == None
        )
        .first()
    )

    if settings_admin:
        db.refresh(settings_admin)
      #  print("✅ settings_admin trovato → ID:", settings_admin.id)
      #  print("🔎 settings_admin.prov_vetrina:", settings_admin.prov_vetrina, type(settings_admin.prov_vetrina))
    else:
        print(f"❌ settings_admin NON trovato per admin_id={offerta.id_admin}")
      
    try:
        prov_admin = float(settings_admin.prov_vetrina)
    except (TypeError, ValueError, AttributeError):
        prov_admin = 0.0
      #  print("⚠️ prov_admin fallback a 0.0")

    # === Provvigione dealer (evita doppio conteggio)
    prov_dealer = 0.0
    if settings_corrente and settings_admin and settings_corrente.id != settings_admin.id:
        try:
            prov_dealer = float(settings_corrente.prov_vetrina or 0)
        except (TypeError, ValueError):
            prov_dealer = 0.0
       #     print("⚠️ prov_dealer fallback a 0.0")
   

    slug_finale = settings_corrente.slug if settings_corrente else None

    # === Blocco provvigioni UnipolRental
    if offerta.id_player == 5:
       # print("🛑 Provvigioni azzerate (id_player == 5)")
        prov_admin = 0.0
        prov_dealer = 0.0

    incremento_totale = prezzo_netto * (prov_admin + prov_dealer) / 100.0
    incremento_mensile = incremento_totale / durata
    canone_finale = canone_base + incremento_mensile

  #  print("🧮 DEBUG FINALE")
  #  print("📦 canone_base:", canone_base)
  #  print("📦 prezzo_netto:", prezzo_netto)
  #  print("📦 prov_admin:", prov_admin)
  #  print("📦 prov_dealer:", prov_dealer)
  #  print("📦 incremento_totale:", incremento_totale)
  #  print("📦 incremento_mensile:", incremento_mensile)
  #  print("📦 canone_finale:", canone_finale)
  #  print("📤 slug_finale:", slug_finale)
  #  print("✅ [END] calcola_quotazione")

    return durata, km, round(canone_finale, 2), slug_finale


def calcola_quotazione_custom(offerta, durata, km, canone_base, current_user, db: Session, settings_corrente: SiteAdminSettings):
  #  print("🟦 [START] calcola_quotazione_custom")
  #  print("🔸 Offerta ID:", offerta.id_offerta)
  #  print("🔸 Slug offerta:", offerta.slug)
  #  print("🔸 durata:", durata, "km:", km)
  #  print("🔸 Player ID:", offerta.id_player)

    if not offerta or not durata or durata <= 0 or not canone_base:
  #      print("❌ Dati iniziali mancanti o non validi")
        return None, None, None, None

    try:
        canone_base = float(canone_base)
    except (TypeError, ValueError):
   #     print("❌ Errore cast canone_base")
        return None, None, None, None

    prezzo_grezzo = offerta.prezzo_totale or offerta.prezzo_listino
    if not prezzo_grezzo:
    #    print("❌ prezzo_grezzo mancante")
        return None, None, None, None

    try:
        prezzo_netto = float(prezzo_grezzo) / 1.22
    except (TypeError, ValueError):
    #   print("❌ Errore cast prezzo_netto")
        return None, None, None, None

    # print("➡️ Prezzo netto calcolato:", prezzo_netto)

    settings_admin = (
        db.query(SiteAdminSettings)
        .filter(SiteAdminSettings.admin_id == int(offerta.id_admin), SiteAdminSettings.dealer_id == None)
        .first()
    )

    if settings_admin:
        db.refresh(settings_admin)
    #    print("✅ settings_admin ID:", settings_admin.id)
    #    print("🔎 prov_vetrina (admin):", settings_admin.prov_vetrina, type(settings_admin.prov_vetrina))
    else:
        print(f"❌ settings_admin NON trovato per admin_id={offerta.id_admin}")

    try:
        prov_admin = float(settings_admin.prov_vetrina)
    except (TypeError, ValueError, AttributeError):
        prov_admin = 0.0
    #    print("⚠️ prov_admin fallback a 0.0")

    prov_dealer = 0.0
    if settings_corrente and settings_admin and settings_corrente.id != settings_admin.id:
        try:
            prov_dealer = float(settings_corrente.prov_vetrina or 0)
        except (TypeError, ValueError):
            prov_dealer = 0.0
    #        print("⚠️ prov_dealer fallback a 0.0")
    

    slug_finale = settings_corrente.slug if settings_corrente else None

    if offerta.id_player == 5:
    #    print("🛑 Provvigioni azzerate (id_player == 5)")
        prov_admin = 0.0
        prov_dealer = 0.0

    incremento_totale = prezzo_netto * (prov_admin + prov_dealer) / 100.0
    incremento_mensile = incremento_totale / durata
    canone_finale = canone_base + incremento_mensile

    #print("🧮 DEBUG FINALE (custom)")
    #print("📦 canone_base:", canone_base)
    #print("📦 prezzo_netto:", prezzo_netto)
    #print("📦 prov_admin:", prov_admin)
    ##print("📦 prov_dealer:", prov_dealer)
    #print("📦 incremento_totale:", incremento_totale)
    #print("📦 incremento_mensile:", incremento_mensile)
    #print("📦 canone_finale:", canone_finale)
    #print("📤 slug_finale:", slug_finale)
    #print("✅ [END] calcola_quotazione_custom")

    return durata, km, round(canone_finale, 2), slug_finale


def aggiorna_rating_convenienza(db: Session):
    from app.models import NltOfferte, NltQuotazioni, NltOfferteRating
    from app.utils.quotazioni import calcola_quotazione  # evita import circolari
    from app.auth_helpers import is_dealer_user  # se necessario, ma lo bypassiamo con dealer_context=False

    from datetime import datetime

    offerte_raw = (
        db.query(NltOfferte, NltQuotazioni)
        .join(NltQuotazioni, NltOfferte.id_offerta == NltQuotazioni.id_offerta)
        .filter(
            NltOfferte.attivo.is_(True),
            NltOfferte.prezzo_totale.isnot(None),
            NltQuotazioni.mesi_48_10.isnot(None)
        )
        .all()
    )

    risultati = []

    for offerta, quotazione in offerte_raw:
        from types import SimpleNamespace
        dummy_user = SimpleNamespace(role="admin", id=offerta.id_admin)

        durata, km, canone_finale, _ = calcola_quotazione(
            offerta, quotazione,
            current_user=dummy_user,
            db=db,
            dealer_context=False,
            dealer_id=None
        )


        if not durata or not km or not canone_finale:
            continue

        costo_km = (canone_finale * durata) / km
        valore_km = float(offerta.prezzo_totale) / km
        indice = valore_km / costo_km if costo_km > 0 else 0

        risultati.append({
            "id_offerta": offerta.id_offerta,
            "costo_km": round(costo_km, 4),
            "valore_km": round(valore_km, 4),
            "indice_convenienza": round(indice, 4)
        })

    risultati.sort(key=lambda x: x["indice_convenienza"], reverse=True)
    totale = len(risultati)

    from sqlalchemy.orm.exc import NoResultFound

    for i, r in enumerate(risultati):
        percentile = i / totale
        if percentile <= 0.2:
            rating = 5
        elif percentile <= 0.4:
            rating = 4
        elif percentile <= 0.6:
            rating = 3
        elif percentile <= 0.8:
            rating = 2
        else:
            rating = 1

        try:
            record = db.query(NltOfferteRating).filter_by(id_offerta=r["id_offerta"]).one_or_none()
            if record:
                record.costo_km = r["costo_km"]
                record.valore_km = r["valore_km"]
                record.indice_convenienza = r["indice_convenienza"]
                record.rating_convenienza = rating
                record.updated_at = datetime.utcnow()
            else:
                db.add(NltOfferteRating(
                    id_offerta=r["id_offerta"],
                    costo_km=r["costo_km"],
                    valore_km=r["valore_km"],
                    indice_convenienza=r["indice_convenienza"],
                    rating_convenienza=rating
                ))
        except NoResultFound:
            continue

    db.commit()
