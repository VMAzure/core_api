import os
import psycopg2
import httpx
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

assert DATABASE_URL, "DATABASE_URL non trovato nel .env"
assert GOOGLE_API_KEY, "GOOGLE_MAPS_API_KEY non trovato nel .env"

def resolve_place_id(query: str) -> str | None:
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "places.id"
    }
    json_body = { "textQuery": query }

    try:
        r = httpx.post(url, headers=headers, json=json_body, timeout=10)
        r.raise_for_status()
        data = r.json()
        places = data.get("places", [])
        if places:
            return places[0]["id"]
    except Exception as e:
        print(f"❌ Errore Google API per '{query}': {e}")
    return None

def sync_place_ids():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, slug, contact_address, meta_title, meta_description
        FROM public.site_admin_settings
        WHERE google_place_id IS NULL
    """)
    rows = cur.fetchall()

    updated = 0
    for id_, slug, address, title, desc in rows:
        query = title or desc or address
        if not query:
            print(f"⚠️ Nessun dato utile per slug '{slug}' (ID={id_})")
            continue

        place_id = resolve_place_id(query)
        if place_id:
            cur.execute("""
                UPDATE public.site_admin_settings
                SET google_place_id = %s
                WHERE id = %s
            """, (place_id, id_))
            print(f"✅ Aggiornato: {slug} → {place_id}")
            updated += 1
        else:
            print(f"⚠️ Place ID non trovato per: {slug}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n🏁 Completato: {updated} dealer aggiornati.")

if __name__ == "__main__":
    sync_place_ids()
