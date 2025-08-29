from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import List, Dict, Any
import os, re, math, httpx

from app.database import get_db
from app.models import (
    User,
    AZLeaseUsatoAuto,
    AZLeaseUsatoIn,
    MnetDettaglioUsato,
    MnetAllestimentoUsato,
    MnetModelloUsato,
    MnetMarcaUsato,
    AutousatoVideo,
)
from fastapi_jwt_auth import AuthJWT

router = APIRouter()

YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "")
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# --- Helpers -----------------------------------------------------------------

_BLOCK_RE = re.compile(r"(assetto corsa|forza horizon|gran turismo|gt7|gameplay|simulator)", re.I)
_SOUND_RE = re.compile(r"(sound|exhaust|scarico|pov)", re.I)
_WHITELIST = {
    "Automoto.it", "Motor1 Italia", "Quattroruote", "HDmotori", "AlVolante", "OmniAuto.it"
}

def _lang_bonus(lang: str | None) -> float:
    if not lang:
        return 0.0
    L = lang.lower()
    return 0.6 if L.startswith("it") else -0.6

def _to_utc_z(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _iso8601_to_seconds(dur: str) -> int:
    if not dur:
        return 0
    h = m = s = 0
    m1 = re.search(r"(\d+)H", dur); h = int(m1.group(1)) if m1 else 0
    m2 = re.search(r"(\d+)M", dur); m = int(m2.group(1)) if m2 else 0
    m3 = re.search(r"(\d+)S", dur); s = int(m3.group(1)) if m3 else 0
    return h*3600 + m*60 + s

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)

def _title_score(title: str, needles: List[str]) -> float:
    t = (title or "").lower()
    score = 0.0
    for n in needles:
        for tok in re.split(r"[^\w]+", n.lower()):
            if tok and tok in t:
                score += 1.0
    return score

def _duration_bonus(sec: int, title: str) -> float:
    if sec > 45*60:     # escluso a monte, qui non dovrebbe arrivare
        return -9.0
    if 3*60 <= sec <= 20*60:
        return 1.0
    if 20*60 < sec <= 30*60:
        return 0.5
    if 30*60 < sec <= 45*60:
        return 0.2
    if sec < 3*60 and _SOUND_RE.search(title or ""):
        return 0.2
    return 0.0

def _recency_bonus(published_at: str) -> float:
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except Exception:
        return 0.0
    days = (_now_utc() - dt).days
    # max 1.5 nei primi 90 giorni, poi decresce verso 0
    return max(0.0, 1.5 - (days/90.0)*1.5)

def _views_bonus(view_count: int) -> float:
    # log10 attenuato
    return min(1.5, math.log10(max(1, view_count + 1)) / 2.0)

def _whitelist_bonus(channel: str) -> float:
    return 0.7 if channel in _WHITELIST else 0.0

def _has_year_in_model(model: str) -> bool:
    return bool(re.search(r"\b(19[89]\d|20\d{2})\b", model or ""))

def _build_queries(marca: str, modello: str, allest: str, anno: int) -> List[str]:
    base = f"{marca} {modello}".strip()
    qs = {
        f"{base} {allest}".strip(),
        base,
        f"{base} prova su strada",
        f"{base} review",
        f"{base} test drive",
        f"{base} sound exhaust",
    }
    # Aggiungi anno solo se il modello non ne contiene già uno
    if anno and not _has_year_in_model(modello):
        qs |= {
            f"{base} {anno}",
            f"{base} {allest} {anno}".strip(),
            f"{base} review {anno}",
            f"{base} prova su strada {anno}",
        }
    # normalizza spazi
    return [re.sub(r"\s+", " ", q).strip() for q in qs if q.strip()]

def _resolve_car_labels(db: Session, auto: AZLeaseUsatoAuto) -> Dict[str, Any]:
    md = db.query(MnetDettaglioUsato).filter(MnetDettaglioUsato.codice_motornet_uni == auto.codice_motornet).first()
    mau = db.query(MnetAllestimentoUsato).filter(MnetAllestimentoUsato.codice_motornet_uni == auto.codice_motornet).first() if not md else None
    mmu = db.query(MnetModelloUsato).filter(MnetModelloUsato.codice_desc_modello == (mau.codice_desc_modello if mau else None)).first() if mau else None

    # marca
    marca = md.marca_nome if md and md.marca_nome else None
    if not marca:
        acr = md.marca_acronimo if md else (mau.acronimo_marca if mau else (mmu.marca_acronimo if mmu else None))
        if acr:
            mmar = db.query(MnetMarcaUsato).filter(MnetMarcaUsato.acronimo == acr).first()
            marca = mmar.nome if mmar and mmar.nome else acr

    modello = md.modello if md and md.modello else (mmu.descrizione if mmu and mmu.descrizione else None)
    allest = md.allestimento if md and md.allestimento else (mau.versione if mau and mau.versione else "")

    return {
        "marca": marca or "",
        "modello": modello or "",
        "allest": allest or "",
    }

# --- Rotte -------------------------------------------------------------------

@router.get("/public/usato/{id_auto}/videos")
def get_public_videos(id_auto: str, db: Session = Depends(get_db), limit: int = Query(6, ge=1, le=12)):
    auto = db.query(AZLeaseUsatoAuto).filter(AZLeaseUsatoAuto.id == id_auto).first()
    if not auto:
        raise HTTPException(status_code=404, detail="Auto non trovata")

    # prendi una rosa ampia per applicare cap per canale
    rows = (
        db.query(AutousatoVideo)
        .filter(
            AutousatoVideo.id_auto == id_auto,
            AutousatoVideo.is_blacklisted.is_(False),
            AutousatoVideo.embeddable.is_(True),
        )
        .order_by(
            AutousatoVideo.is_pinned.desc(),
            AutousatoVideo.rank_score.desc(),
            AutousatoVideo.published_at.desc().nullslast(),
        )
        .limit(30)
        .all()
    )

    picked, seen = [], set()
    for v in rows:
        ch = (v.channel_title or "").strip()
        if v.is_pinned or ch not in seen:
            picked.append(v)
            seen.add(ch)
        if len(picked) >= limit:
            break
    if len(picked) < limit:
        for v in rows:
            if v in picked:
                continue
            picked.append(v)
            if len(picked) >= limit:
                break

    def to_out(v: AutousatoVideo):
        vid = v.video_id
        return {
            "videoId": vid,
            "title": v.title,
            "channel": v.channel_title,
            "publishedAt": _to_utc_z(v.published_at),
            "durationSec": v.duration_sec,
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "embedUrl": f"https://www.youtube-nocookie.com/embed/{vid}",
            "pinned": v.is_pinned,
        }

    return {"videos": [to_out(v) for v in picked]}


@router.post("/admin/usato/{id_auto}/videos/refresh", status_code=status.HTTP_200_OK)
async def refresh_videos(
    id_auto: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db),
):
    if not YOUTUBE_KEY:
        raise HTTPException(500, "YOUTUBE_API_KEY mancante")

    # Auth basica: admin o dealer proprietario dell’auto
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non valido")

    auto = db.query(AZLeaseUsatoAuto).filter(AZLeaseUsatoAuto.id == id_auto).first()
    if not auto:
        raise HTTPException(404, "Auto non trovata")

    # controllo proprietario
    usatoin = db.query(AZLeaseUsatoIn).filter(AZLeaseUsatoIn.id == auto.id_usatoin).first() if auto.id_usatoin else None
    is_admin = (getattr(user, "role", "") or "").lower() == "admin"
    is_owner = bool(usatoin and (user.id in {usatoin.admin_id, usatoin.dealer_id}))
    if not (is_admin or is_owner):
        raise HTTPException(403, "Non autorizzato")

    labels = _resolve_car_labels(db, auto)
    marca, modello, allest = labels["marca"], labels["modello"], labels["allest"]
    queries = _build_queries(marca, modello, allest, auto.anno_immatricolazione)

    video_ids: List[str] = []
    async with httpx.AsyncClient(timeout=12) as client:
        for q in queries:
            params = dict(
                part="snippet",
                q=q,
                type="video",
                maxResults=10,
                relevanceLanguage="it",
                regionCode="IT",
                videoEmbeddable="true",
                safeSearch="moderate",
                order="relevance",
                key=YOUTUBE_KEY,
            )
            r = await client.get(SEARCH_URL, params=params)
            if r.status_code != 200:
                continue
            items = r.json().get("items", [])
            for it in items:
                vid = it["id"]["videoId"]
                if vid not in video_ids:
                    video_ids.append(vid)

        # Dettagli
        results = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i : i + 50]
            if not chunk:
                continue
            params = dict(
                part="snippet,contentDetails,statistics,status",
                id=",".join(chunk),
                key=YOUTUBE_KEY,
            )
            r = await client.get(VIDEOS_URL, params=params)
            if r.status_code != 200:
                continue
            for v in r.json().get("items", []):
                sn = v.get("snippet", {})
                st = v.get("status", {})
                cd = v.get("contentDetails", {})
                stats = v.get("statistics", {})
                if sn.get("liveBroadcastContent") != "none":
                    continue
                if st.get("madeForKids") is True:
                    continue
                if not st.get("embeddable", False):
                    continue

                title   = sn.get("title", "") or ""
                channel = sn.get("channelTitle", "") or ""
                ch_id   = sn.get("channelId")
                if _BLOCK_RE.search(title):
                    continue

                dur_sec = _iso8601_to_seconds(cd.get("duration", "PT0S"))
                if dur_sec > 45 * 60:
                    continue

                views   = int(stats.get("viewCount", "0") or 0)
                lang    = sn.get("defaultAudioLanguage") or sn.get("defaultLanguage")

                needles = [marca, modello, allest, str(auto.anno_immatricolazione or "")]
                score = (
                    _title_score(title, needles)
                    + _recency_bonus(sn.get("publishedAt"))
                    + _views_bonus(views)
                    + _duration_bonus(dur_sec, title)
                    + _whitelist_bonus(channel)
                    + _lang_bonus(lang)
                )

                results.append({
                    "videoId": v["id"],
                    "title": title,
                    "channel": channel,
                    "channelId": ch_id,
                    "publishedAt": sn.get("publishedAt"),
                    "durationSec": dur_sec,
                    "embeddable": True,
                    "viewCount": views,
                    "rankScore": round(score, 2),
                    "audioLang": lang,
                })


    # Upsert in DB (rispetta pinned/blacklist)
    inserted = updated = 0
    now = _now_utc().replace(tzinfo=None)
    for item in results:
        existing = (
            db.query(AutousatoVideo)
            .filter(AutousatoVideo.id_auto == id_auto, AutousatoVideo.video_id == item["videoId"])
            .first()
        )
        if not existing:
            vrow = AutousatoVideo(
                id_auto=id_auto,
                video_id=item["videoId"],
                title=item["title"],
                channel_title=item["channel"],
                channel_id=item.get("channelId"),
                published_at=datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00")) if item["publishedAt"] else None,
                duration_sec=item["durationSec"],
                embeddable=item["embeddable"],
                view_count=item["viewCount"],
                rank_score=item["rankScore"],
                source_query="; ".join(queries)[:1000],
                audio_lang=item.get("audioLang"),
                checked_at=now,
            )
            db.add(vrow)
            inserted += 1
        else:
            existing.title = item["title"]
            existing.channel_title = item["channel"]
            existing.channel_id = item.get("channelId") or existing.channel_id
            existing.published_at = datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00")) if item["publishedAt"] else existing.published_at
            existing.duration_sec = item["durationSec"]
            existing.embeddable = item["embeddable"]
            existing.view_count = item["viewCount"]
            existing.rank_score = item["rankScore"]
            existing.source_query = "; ".join(queries)[:1000]
            existing.audio_lang = item.get("audioLang") or existing.audio_lang
            existing.checked_at = now
            updated += 1


    db.commit()

    # Limita a 12-20 record per auto per contenere il DB
    keep = (
        db.query(AutousatoVideo)
        .filter(AutousatoVideo.id_auto == id_auto)
        .order_by(
            AutousatoVideo.is_pinned.desc(),
            AutousatoVideo.is_blacklisted.asc(),
            AutousatoVideo.rank_score.desc(),
            AutousatoVideo.published_at.desc().nullslast(),
        )
        .limit(20)
        .all()
    )
    ids_keep = {v.id for v in keep}
    # opzionale: non cancelliamo, lasciamo pulizia manuale se serve

    return {"ok": True, "inserted": inserted, "updated": updated, "candidates": len(results)}
