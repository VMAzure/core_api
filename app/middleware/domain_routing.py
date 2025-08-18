from __future__ import annotations
from typing import Optional, Dict, Tuple
from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text
from urllib.parse import parse_qs, urlencode
from app.database import engine  # usa il tuo engine sincrono
import time

# Cache in RAM: host -> (slug, is_primary, force_https)
_DOMAIN_CACHE: Dict[str, Tuple[str, bool, bool]] = {}
# Cache primaria: slug -> primary_host
_PRIMARY_CACHE: Dict[str, str] = {}
# TTL semplice (secondi). Se vuoi invalidare manualmente, svuota i dict.
_CACHE_TTL = 300
_LAST_FILL = 0.0

def _normalize_host(request: Request) -> str:
    return (request.headers.get("host") or "").split(":")[0].strip().lower()

def _now() -> float:
    return time.time()

def _refresh_needed() -> bool:
    return (_now() - _LAST_FILL) > _CACHE_TTL

def _build_url(request: Request, host: str, strip_slug: bool, force_https: bool, absolute: bool = True) -> str:
    scheme = "https" if force_https or request.url.scheme == "https" else "http"
    path = request.url.path
    q = parse_qs(request.url.query, keep_blank_values=True)
    if strip_slug and "slug" in q:
        q.pop("slug", None)
    query = urlencode([(k, v) for k, vals in q.items() for v in vals])
    base = f"{scheme}://{host}" if absolute else ""
    return f"{base}{path}{('?' + query) if query else ''}"

def _load_all_mappings():
    """Carica tutta la tabella in cache (full refresh)."""
    global _LAST_FILL
    _DOMAIN_CACHE.clear()
    _PRIMARY_CACHE.clear()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            select domain, slug, is_primary, force_https
            from public.domain_aliases
        """)).mappings().all()
    for r in rows:
        host = r["domain"].lower()
        _DOMAIN_CACHE[host] = (r["slug"], bool(r["is_primary"]), bool(r["force_https"]))
    # build primary map
    for host, (slug, is_primary, _fh) in _DOMAIN_CACHE.items():
        if is_primary:
            _PRIMARY_CACHE[slug] = host
    _LAST_FILL = _now()

def _get_domain_record(host: str) -> Optional[Tuple[str, bool, bool]]:
    """Ritorna (slug, is_primary, force_https) per host."""
    if host in _DOMAIN_CACHE:
        return _DOMAIN_CACHE[host]
    # cache miss: prova refresh e ripeti
    _load_all_mappings()
    return _DOMAIN_CACHE.get(host)

def _get_primary_host(slug: str) -> Optional[str]:
    if slug in _PRIMARY_CACHE:
        return _PRIMARY_CACHE[slug]
    # cache stantia? ricarichiamo tutto
    _load_all_mappings()
    return _PRIMARY_CACHE.get(slug)

class DomainRoutingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            host = _normalize_host(request)
            if not host:
                return Response("Dominio non configurato", status_code=404)

            # refresh periodico (soft); non blocca se non necessario
            if _refresh_needed():
                try:
                    _load_all_mappings()
                except Exception:
                    # in caso di errore in refresh, prosegui con cache vecchia
                    pass

            rec = _get_domain_record(host)
            if not rec:
                # Host sconosciuto: 404 esplicito (oppure puoi fare redirect ad un fallback noto)
                return Response("Dominio non configurato", status_code=404)

            slug, is_primary, force_https = rec
            primary_host = _get_primary_host(slug) or host

            # Regole SEO/canonical
            wants_https = (request.url.scheme != "https") and force_https
            wrong_host = (host != primary_host)

            # slug in query → rimuoverlo
            qs = request.url.query
            strip_slug_needed = False
            if "slug=" in qs:
                q = parse_qs(qs, keep_blank_values=True)
                if "slug" in q:
                    strip_slug_needed = True

            if wants_https or wrong_host or strip_slug_needed:
                url = _build_url(
                    request,
                    primary_host if wrong_host else host,
                    strip_slug=strip_slug_needed,
                    force_https=True  # se redirigiamo, meglio forzare https qui
                )
                return RedirectResponse(url, status_code=301)

            # Passa lo slug al resto dell'app
            request.state.slug = slug

            # Continua il normale processing
            response = await call_next(request)

            # Header canonical assoluto (coerente con host “giusto” e senza ?slug)
            canon = _build_url(request, host, strip_slug=True, force_https=False, absolute=True)
            response.headers["Link"] = f'<{canon}>; rel="canonical"'
            return response

        except Exception:
            # Fail safe: non bloccare l’app in caso di errore imprevisto
            return await call_next(request)
