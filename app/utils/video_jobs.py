# app/utils/video_jobs.py
"""
Jobs YouTube per usato:
- video_daily_batch(): cerca nuovi video per un sottoinsieme di auto (priorità smart, cap quota)
- video_revalidate_existing(): aggiorna metadati per gli ID già salvati (light quota)
- video_weekly_sweep(): refresh completo per auto "stale"

Dipendenze:
- env: YOUTUBE_API_KEY
- modelli: AutousatoVideo, AZLeaseUsatoAuto, Mnet* (schema="public")
- DB: SessionLocal

Non richiede async. Usa httpx.Client (sincrono).
"""

from __future__ import annotations

import os
import re
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional

import httpx
from sqlalchemy import func
from sqlalchemy import case

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AZLeaseUsatoAuto,
    AutousatoVideo,
    MnetDettaglioUsato,
    MnetAllestimentoUsato,
    MnetModelloUsato,
    MnetMarcaUsato,
)

# --------------------------- Config -----------------------------------------

YOUTUBE_KEY: str = os.getenv("YOUTUBE_API_KEY", "")

# Budget di default e parametri job
VIDEO_BATCH_SIZE: int = int(os.getenv("VIDEO_BATCH_SIZE", "8"))             # auto/giorno
YOUTUBE_DAILY_CAP: int = int(os.getenv("YOUTUBE_DAILY_CAP", "3500"))        # unità/giorno
VIDEO_KEEP_PER_AUTO: int = int(os.getenv("VIDEO_KEEP_PER_AUTO", "20"))      # record max/auto
REVALIDATE_MAX_AGE_H: int = int(os.getenv("VIDEO_REVALIDATE_H", "72"))      # età max ore
STALE_DAYS_SWEEP: int = int(os.getenv("VIDEO_STALE_DAYS", "30"))            # giorni per weekly sweep

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

_BLOCK_RE = re.compile(r"(assetto corsa|forza horizon|gran turismo|gt7|gameplay|simulator)", re.I)
_SOUND_RE = re.compile(r"(sound|exhaust|scarico|pov)", re.I)
_WHITELIST = {"Automoto.it", "Motor1 Italia", "Quattroruote", "HDmotori", "AlVolante", "OmniAuto.it"}


# --------------------------- Helpers ----------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso8601_to_seconds(dur: Optional[str]) -> int:
    if not dur:
        return 0
    h = m = s = 0
    m_h = re.search(r"(\d+)H", dur)
    m_m = re.search(r"(\d+)M", dur)
    m_s = re.search(r"(\d+)S", dur)
    if m_h:
        h = int(m_h.group(1))
    if m_m:
        m = int(m_m.group(1))
    if m_s:
        s = int(m_s.group(1))
    return h * 3600 + m * 60 + s


def _title_score(title: str, needles: List[str]) -> float:
    t = (title or "").lower()
    score = 0.0
    for n in needles:
        for tok in re.split(r"[^\w]+", (n or "").lower()):
            if tok and tok in t:
                score += 1.0
    return score


def _duration_bonus(sec: int, title: str) -> float:
    if sec > 45 * 60:
        return -9.0
    if 3 * 60 <= sec <= 20 * 60:
        return 1.0
    if 20 * 60 < sec <= 30 * 60:
        return 0.5
    if 30 * 60 < sec <= 45 * 60:
        return 0.2
    if sec < 3 * 60 and _SOUND_RE.search(title or ""):
        return 0.2
    return 0.0


def _recency_bonus(published_at: Optional[str]) -> float:
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00")) if published_at else None
    except Exception:
        dt = None
    if not dt:
        return 0.0
    days = (_now_utc() - dt.replace(tzinfo=timezone.utc)).days
    return max(0.0, 1.5 - (days / 90.0) * 1.5)


def _views_bonus(view_count: int) -> float:
    return min(1.5, math.log10(max(1, view_count + 1)) / 2.0)


def _whitelist_bonus(channel: str) -> float:
    return 0.8 if (channel or "") in _WHITELIST else 0.0


def _lang_bonus(lang: Optional[str]) -> float:
    if not lang:
        return 0.0
    L = lang.lower()
    return 0.6 if L.startswith("it") else -0.6


def _has_year_in_model(model: str) -> bool:
    return bool(re.search(r"\b(19[89]\d|20\d{2})\b", model or ""))


def _resolve_car_labels(db: Session, auto: AZLeaseUsatoAuto) -> Dict[str, str]:
    """Ricava marca e modello esteso da Mnet*, senza usare allestimento o immatricolazione."""
    marca = modello = ""

    md = db.query(MnetDettaglioUsato).filter(MnetDettaglioUsato.codice_motornet_uni == auto.codice_motornet).first()
    mau = db.query(MnetAllestimentoUsato).filter(MnetAllestimentoUsato.codice_motornet_uni == auto.codice_motornet).first() if not md else None
    mmu = db.query(MnetModelloUsato).filter(MnetModelloUsato.codice_desc_modello == (mau.codice_desc_modello if mau else None)).first() if mau else None

    if md and md.marca_nome:
        marca = md.marca_nome.strip()
    elif md and md.marca_acronimo:
        marca = md.marca_acronimo.strip()
    elif mau and mau.acronimo_marca:
        marca = mau.acronimo_marca.strip()
    elif mmu and mmu.marca_acronimo:
        marca = mmu.marca_acronimo.strip()

    if mmu:
        modello = (mmu.gamma_descrizione or mmu.descrizione or "").strip()

    return {
        "marca": marca or "",
        "modello": modello or "",
        "allest": ""  # <-- disattivato completamente
    }



def _build_queries(marca: str, modello: str, allest: str, anno: int) -> List[str]:
    base = f"{marca} {modello}".strip()
    qs = {
        base,
        f"{base} review",
        f"{base} test drive",
        f"{base} prova su strada",
        f"{base} sound exhaust",
    }
    if anno and not _has_year_in_model(modello):
        qs |= {
            f"{base} {anno}",
            f"{base} review {anno}",
            f"{base} test drive {anno}",
        }
    return [re.sub(r"\s+", " ", q).strip() for q in qs if q.strip()]



def _quota_cost(search_calls: int, video_count: int) -> int:
    # search.list = 100u; videos.list = 1u/video
    return search_calls * 100 + video_count


def _keep_top_n_for_auto(db: Session, id_auto: str, keep: int = VIDEO_KEEP_PER_AUTO) -> None:
    """Mantieni solo i migliori N record per auto. Non rimuove pinned/blacklist se rientrano nel top N."""
    rows = (
        db.query(AutousatoVideo.id)
        .filter(AutousatoVideo.id_auto == id_auto)
        .order_by(
            AutousatoVideo.is_pinned.desc(),
            AutousatoVideo.is_blacklisted.asc(),
            AutousatoVideo.rank_score.desc(),
            AutousatoVideo.published_at.desc().nullslast(),
        )
        .offset(keep)
        .all()
    )
    if rows:
        to_del = [r.id for r in rows]
        db.query(AutousatoVideo).filter(AutousatoVideo.id.in_(to_del)).delete(synchronize_session=False)


# --------------------------- Core ops ----------------------------------------

def refresh_videos_for_auto(db: Session, id_auto: str) -> Tuple[int, int, int]:
    """
    Esegue ricerca YT e upsert dei risultati per una singola auto.
    Ritorna: (inserted, updated, quota_used)
    """
    if not YOUTUBE_KEY:
        logging.error("YOUTUBE_API_KEY mancante")
        return 0, 0, 0

    auto = db.query(AZLeaseUsatoAuto).filter(AZLeaseUsatoAuto.id == id_auto).first()
    if not auto:
        logging.warning(f"Auto non trovata: {id_auto}")
        return 0, 0, 0

    labels = _resolve_car_labels(db, auto)
    marca, modello, allest = labels["marca"], labels["modello"], labels["allest"]
    queries = _build_queries(marca, modello, allest, auto.anno_immatricolazione)

    inserted = updated = 0
    quota_used = 0

    video_ids: List[str] = []
    with httpx.Client(timeout=12) as client:
        # Search
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
            r = client.get(SEARCH_URL, params=params)
            if r.status_code != 200:
                logging.warning(f"search.list failed ({r.status_code}): {r.text[:200]}")
                continue
            items = r.json().get("items", [])
            for it in items:
                vid = it["id"]["videoId"]
                if vid not in video_ids:
                    video_ids.append(vid)
        quota_used += _quota_cost(search_calls=len(queries), video_count=0)

        if not video_ids:
            return 0, 0, quota_used

        # Details
        results: List[Dict] = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i : i + 50]
            params = dict(part="snippet,contentDetails,statistics,status", id=",".join(chunk), key=YOUTUBE_KEY)
            r = client.get(VIDEOS_URL, params=params)
            if r.status_code != 200:
                logging.warning(f"videos.list failed ({r.status_code}): {r.text[:200]}")
                continue
            data_items = r.json().get("items", [])
            quota_used += _quota_cost(search_calls=0, video_count=len(chunk))

            for v in data_items:
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

                title = sn.get("title", "") or ""
                if _BLOCK_RE.search(title):
                    continue

                dur_sec = _iso8601_to_seconds(cd.get("duration"))
                if dur_sec > 45 * 60:
                    continue

                channel = sn.get("channelTitle", "") or ""
                ch_id = sn.get("channelId")
                views = int(stats.get("viewCount", "0") or 0)
                lang = sn.get("defaultAudioLanguage") or sn.get("defaultLanguage")
                published_at = sn.get("publishedAt")

                needles = [marca, modello, allest, str(auto.anno_immatricolazione or "")]
                score = (
                    _title_score(title, needles)
                    + _recency_bonus(published_at)
                    + _views_bonus(views)
                    + _duration_bonus(dur_sec, title)
                    + _whitelist_bonus(channel)
                    + _lang_bonus(lang)
                )

                results.append(
                    dict(
                        videoId=v["id"],
                        title=title,
                        channel=channel,
                        channelId=ch_id,
                        publishedAt=published_at,
                        durationSec=dur_sec,
                        embeddable=True,
                        viewCount=views,
                        rankScore=round(score, 2),
                        audioLang=lang,
                    )
                )

    # Upsert
    now_naive = _now_utc().replace(tzinfo=None)
    for item in results:
        existing: Optional[AutousatoVideo] = (
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
                published_at=datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00"))
                if item["publishedAt"]
                else None,
                duration_sec=item["durationSec"],
                embeddable=item["embeddable"],
                view_count=item["viewCount"],
                rank_score=item["rankScore"],
                source_query="; ".join(queries)[:1000],
                audio_lang=item.get("audioLang"),
                checked_at=now_naive,
            )
            db.add(vrow)
            inserted += 1
        else:
            # non toccare pinned/blacklist
            existing.title = item["title"]
            existing.channel_title = item["channel"]
            existing.channel_id = item.get("channelId") or existing.channel_id
            if item["publishedAt"]:
                existing.published_at = datetime.fromisoformat(item["publishedAt"].replace("Z", "+00:00"))
            existing.duration_sec = item["durationSec"]
            existing.embeddable = item["embeddable"]
            existing.view_count = item["viewCount"]
            existing.rank_score = item["rankScore"]
            existing.source_query = "; ".join(queries)[:1000]
            existing.audio_lang = item.get("audioLang") or existing.audio_lang
            existing.checked_at = now_naive
            updated += 1

    # Cleanup soft
    _keep_top_n_for_auto(db, id_auto, VIDEO_KEEP_PER_AUTO)

    return inserted, updated, quota_used


def revalidate_existing_for_auto(db: Session, id_auto: str) -> Tuple[int, int]:
    """
    Aggiorna solo status/metriche per gli ID già salvati.
    Ritorna: (updated, quota_used)
    """
    if not YOUTUBE_KEY:
        logging.error("YOUTUBE_API_KEY mancante")
        return 0, 0

    vids = (
        db.query(AutousatoVideo)
        .filter(AutousatoVideo.id_auto == id_auto)
        .with_entities(AutousatoVideo.video_id)
        .all()
    )
    ids = [v.video_id for v in vids]
    if not ids:
        return 0, 0

    updated = 0
    quota_used = 0
    with httpx.Client(timeout=12) as client:
        for i in range(0, len(ids), 50):
            chunk = ids[i : i + 50]
            params = dict(part="snippet,contentDetails,statistics,status", id=",".join(chunk), key=YOUTUBE_KEY)
            r = client.get(VIDEOS_URL, params=params)
            if r.status_code != 200:
                logging.warning(f"videos.list revalidate failed ({r.status_code}): {r.text[:200]}")
                continue
            data_items = r.json().get("items", [])
            quota_used += _quota_cost(search_calls=0, video_count=len(chunk))

            by_id = {it["id"]: it for it in data_items}
            for vid in chunk:
                it = by_id.get(vid)
                if not it:
                    continue
                sn = it.get("snippet", {})
                st = it.get("status", {})
                cd = it.get("contentDetails", {})
                stats = it.get("statistics", {})

                dur_sec = _iso8601_to_seconds(cd.get("duration"))
                emb = bool(st.get("embeddable", False))
                views = int(stats.get("viewCount", "0") or 0)
                lang = sn.get("defaultAudioLanguage") or sn.get("defaultLanguage")
                ch_id = sn.get("channelId")
                ch_title = sn.get("channelTitle")
                pub = sn.get("publishedAt")

                row = (
                    db.query(AutousatoVideo)
                    .filter(AutousatoVideo.id_auto == id_auto, AutousatoVideo.video_id == vid)
                    .first()
                )
                if not row:
                    continue
                row.duration_sec = dur_sec or row.duration_sec
                row.embeddable = emb
                row.view_count = views
                row.audio_lang = lang or row.audio_lang
                row.channel_id = ch_id or row.channel_id
                row.channel_title = ch_title or row.channel_title
                if pub:
                    row.published_at = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                row.checked_at = _now_utc().replace(tzinfo=None)
                updated += 1

    return updated, quota_used


# --------------------------- Schedulers API ----------------------------------

def _select_auto_for_batch(db: Session, batch_size: int) -> List[str]:
    """
    Seleziona le auto prioritarie:
    1) nessun video
    2) meno di 3 video
    3) checked_at più vecchio
    4) pochi errori
    """
    sub = (
        db.query(
            AZLeaseUsatoAuto.id.label("id_auto"),
            func.count(AutousatoVideo.id).label("video_count"),
            func.coalesce(func.max(AutousatoVideo.checked_at), datetime(1970, 1, 1)).label("last_check"),
    
            func.sum(case((AutousatoVideo.error_count > 0, 1), else_=0)).label("err_rows"),

            )
        .outerjoin(AutousatoVideo, AutousatoVideo.id_auto == AZLeaseUsatoAuto.id)
        .group_by(AZLeaseUsatoAuto.id)
        .subquery()
    )

    rows = (
        db.query(sub.c.id_auto)
        .order_by(
            (sub.c.video_count == 0).desc(),
            (sub.c.video_count < 3).desc(),
            sub.c.last_check.asc(),
            sub.c.err_rows.asc(),
        )
        .limit(batch_size)
        .all()
    )
    return [r.id_auto for r in rows]


def _select_auto_for_revalidate(db: Session, max_age_h: int, batch_size: int) -> List[str]:
    threshold = _now_utc().replace(tzinfo=None) - timedelta(hours=max_age_h)
    rows = (
        db.query(AutousatoVideo.id_auto)
        .group_by(AutousatoVideo.id_auto)
        .having(func.min(AutousatoVideo.checked_at) < threshold)
        .order_by(func.min(AutousatoVideo.checked_at).asc())
        .limit(batch_size)
        .all()
    )
    return [r.id_auto for r in rows]


def video_daily_batch() -> None:
    """
    Batch giornaliero:
    - seleziona fino a VIDEO_BATCH_SIZE auto
    - per ciascuna, esegue refresh (search + details)
    - rispetta YOUTUBE_DAILY_CAP
    """
    logging.info("🎞️ video_daily_batch start")
    if not YOUTUBE_KEY:
        logging.error("YOUTUBE_API_KEY mancante: skip")
        return

    db = SessionLocal()
    try:
        ids = _select_auto_for_batch(db, VIDEO_BATCH_SIZE)
        logging.info(f"video_daily_batch: {len(ids)} auto selezionate")
        quota_budget = YOUTUBE_DAILY_CAP

        for aid in ids:
            try:
                ins, upd, quota = refresh_videos_for_auto(db, aid)
                quota_budget -= quota
                db.commit()
                logging.info(f"[{aid}] inserted={ins} updated={upd} quota={quota} remaining={quota_budget}")
            except Exception as e:
                db.rollback()
                logging.warning(f"⚠️ Commit fallito per auto {aid}: {e}")
                continue

            if quota_budget <= 0:
                logging.warning("Quota budget esaurito")
                break

    except Exception as e:
        db.rollback()
        logging.exception(f"video_daily_batch error: {e}")
    finally:
        db.close()
        logging.info("🎞️ video_daily_batch end")



def video_revalidate_existing() -> None:
    """
    Revalidazione leggera:
    - seleziona auto con checked_at vecchio
    - aggiorna dati video esistenti (no search)
    """
    logging.info("♻️ video_revalidate_existing start")
    if not YOUTUBE_KEY:
        logging.error("YOUTUBE_API_KEY mancante: skip")
        return

    db = SessionLocal()
    try:
        ids = _select_auto_for_revalidate(db, REVALIDATE_MAX_AGE_H, VIDEO_BATCH_SIZE * 2)
        logging.info(f"revalidate: {len(ids)} auto")

        for aid in ids:
            try:
                upd, quota = revalidate_existing_for_auto(db, aid)
                db.commit()
                logging.info(f"[{aid}] revalidated={upd} quota={quota}")
            except Exception as e:
                db.rollback()
                logging.warning(f"⚠️ Revalidate fallita per auto {aid}: {e}")
                continue

    except Exception as e:
        db.rollback()
        logging.exception(f"video_revalidate_existing error: {e}")
    finally:
        db.close()
        logging.info("♻️ video_revalidate_existing end")



def video_weekly_sweep() -> None:
    """
    Sweep settimanale:
    - refresh completo per auto con last_check > STALE_DAYS_SWEEP
    """
    logging.info("🧹 video_weekly_sweep start")
    if not YOUTUBE_KEY:
        logging.error("YOUTUBE_API_KEY mancante: skip")
        return

    db = SessionLocal()
    try:
        threshold = _now_utc().replace(tzinfo=None) - timedelta(days=STALE_DAYS_SWEEP)
        rows = (
            db.query(AZLeaseUsatoAuto.id)
            .outerjoin(AutousatoVideo, AutousatoVideo.id_auto == AZLeaseUsatoAuto.id)
            .group_by(AZLeaseUsatoAuto.id)
            .having(func.coalesce(func.max(AutousatoVideo.checked_at), datetime(1970, 1, 1)) < threshold)
            .limit(50)
            .all()
        )
        ids = [r.id for r in rows]
        logging.info(f"weekly_sweep: {len(ids)} auto")
        quota_budget = YOUTUBE_DAILY_CAP

        for aid in ids:
            try:
                ins, upd, quota = refresh_videos_for_auto(db, aid)
                quota_budget -= quota
                db.commit()
                logging.info(f"[{aid}] inserted={ins} updated={upd} quota={quota} remaining={quota_budget}")
            except Exception as e:
                db.rollback()
                logging.warning(f"⚠️ Commit fallito per auto {aid}: {e}")
                continue

            if quota_budget <= 0:
                logging.warning("Quota budget esaurito")
                break

    except Exception as e:
        db.rollback()
        logging.exception(f"video_weekly_sweep error: {e}")
    finally:
        db.close()
        logging.info("🧹 video_weekly_sweep end")



__all__ = [
    "video_daily_batch",
    "video_revalidate_existing",
    "video_weekly_sweep",
    "refresh_videos_for_auto",
    "revalidate_existing_for_auto",
]
