# app/routes/tenant.py
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from app.database import engine

router = APIRouter(prefix="/api/tenant", tags=["Tenant"])


class TenantResolveResponse(BaseModel):
    host: str
    slug: str
    is_primary: bool
    force_https: bool
    primary_host: str


def _normalize_host_from_request(request: Request) -> str:
    """
    Normalizza l'host in modo sicuro:
    1) X-Forwarded-Host (se presente)
    2) altrimenti Host
    - elimina porta (:443, :80…)
    - prende solo il primo valore se multipli
    - elimina eventuale slash finale
    - forza lowercase
    """
    xf_host = request.headers.get("x-forwarded-host")
    raw_host = (xf_host or request.headers.get("host") or "").strip()

    # più valori separati da virgola -> prendi il primo
    if "," in raw_host:
        raw_host = raw_host.split(",", 1)[0].strip()

    # togli eventuale porta
    if ":" in raw_host:
        raw_host = raw_host.split(":", 1)[0].strip()

    # togli eventuale slash finale
    if raw_host.endswith("/"):
        raw_host = raw_host[:-1]

    return raw_host.lower()


@router.get("/resolve", response_model=TenantResolveResponse)
def resolve_tenant(request: Request):
    host = _normalize_host_from_request(request)

    if not host:
        raise HTTPException(status_code=400, detail="Host header mancante")

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

        # trova il primary_host di quello slug
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
