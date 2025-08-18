# app/routes/tenant.py
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from app.database import engine  # usa lo stesso engine sincrono che hai in main

router = APIRouter(prefix="/api/tenant", tags=["Tenant"])

class TenantResolveResponse(BaseModel):
    host: str
    slug: str
    is_primary: bool
    force_https: bool
    primary_host: str

def _normalize_host_from_request(request: Request) -> str:
    """
    Prende l'host dalla richiesta in modo robusto dietro proxy:
    - preferisce X-Forwarded-Host se presente
    - altrimenti usa Host
    - rimuove porta e spazi, forza lowercase
    """
    xf_host = request.headers.get("x-forwarded-host", "").strip()
    raw_host = (xf_host or request.headers.get("host", "")).strip()
    # se X-Forwarded-Host contiene più valori separati da virgola, prendi il primo
    if "," in raw_host:
        raw_host = raw_host.split(",", 1)[0].strip()
    # rimuovi eventuale :porta
    host_only = raw_host.split(":", 1)[0].strip().lower()
    return host_only

@router.get("/resolve", response_model=TenantResolveResponse)
def resolve_tenant(request: Request):
    """
    Risolve l'host in (slug, is_primary, force_https, primary_host).
    404 se l'host non è configurato in public.domain_aliases.
    """
    host = _normalize_host_from_request(request)
    if not host:
        raise HTTPException(status_code=400, detail="Host header mancante")

    # 1) lookup host → (slug, is_primary, force_https)
    with engine.connect() as conn:
        rec = conn.execute(
            text("""
                select slug, is_primary, force_https
                from public.domain_aliases
                where lower(domain) = lower(:host)
                limit 1
            """),
            {"host": host},
        ).mappings().first()

        if not rec:
            raise HTTPException(status_code=404, detail="Dominio non configurato")

        slug = rec["slug"]
        is_primary = bool(rec["is_primary"])
        force_https = bool(rec["force_https"])

        # 2) trova primary_host per quello slug
        prim = conn.execute(
            text("""
                select domain
                from public.domain_aliases
                where slug = :slug and is_primary = true
                limit 1
            """),
            {"slug": slug},
        ).mappings().first()

        primary_host = (prim["domain"].lower() if prim else host)

    return TenantResolveResponse(
        host=host,
        slug=slug,
        is_primary=is_primary,
        force_https=force_https,
        primary_host=primary_host,
    )
