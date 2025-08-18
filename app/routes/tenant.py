from __future__ import annotations

import os
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from app.database import engine

router = APIRouter(prefix="/api/tenant", tags=["Tenant"])

DEBUG_TENANT = os.getenv("DEBUG_TENANT", "false").lower() == "true"
ALLOW_QUERY_HOST = os.getenv("ALLOW_QUERY_HOST", "false").lower() == "true"


class TenantResolveResponse(BaseModel):
    host: str
    slug: str
    is_primary: bool
    force_https: bool
    primary_host: str


def _normalize_host(request: Request) -> str:
    """
    Ordine di priorità:
    1) querystring ?host= (se ALLOW_QUERY_HOST=true)
    2) X-Tenant-Host (header custom)
    3) X-Forwarded-Host (standard proxy)
    4) Host
    Poi:
      - prendi solo il primo valore se virgole
      - rimuovi :porta
      - rimuovi eventuale slash finale
      - lowercase
    """

    # 1) query param
    qh = (request.query_params.get("host") or "").strip() if ALLOW_QUERY_HOST else ""

    # 2) header custom
    tenant_hdr = (request.headers.get("x-tenant-host") or "").strip()

    # 3) x-forwarded-host
    xf = (request.headers.get("x-forwarded-host") or "").strip()

    # 4) host
    hv = (request.headers.get("host") or "").strip()

    raw = (qh or tenant_hdr or xf or hv)

    if "," in raw:
        raw = raw.split(",", 1)[0].strip()
    if ":" in raw:
        raw = raw.split(":", 1)[0].strip()
    if raw.endswith("/"):
        raw = raw[:-1]

    return raw.lower()


@router.get("/resolve", response_model=TenantResolveResponse)
def resolve_tenant(request: Request):
    # Debug degli header (solo se DEBUG_TENANT=true)
    if DEBUG_TENANT:
        print(
            f"[tenant.resolve] raw_qh='{request.query_params.get('host')}', "
            f"raw_xth='{request.headers.get('x-tenant-host')}', "
            f"raw_xfh='{request.headers.get('x-forwarded-host')}', "
            f"raw_host='{request.headers.get('host')}'"
        )

    host = _normalize_host(request)

    if DEBUG_TENANT:
        print(f"[tenant.resolve] effective_host='{host}'")

    if not host:
        raise HTTPException(status_code=400, detail="Host header mancante")

    with engine.connect() as conn:
        if DEBUG_TENANT:
            dbinfo = conn.execute(
                text("select current_database() as db, current_user as usr, current_schema as sch")
            ).mappings().first()
            print(
                f"[tenant.resolve] db={dbinfo['db']} user={dbinfo['usr']} schema={dbinfo['sch']}"
            )

        rec = conn.execute(
            text("""
                select slug, is_primary, force_https
                from public.domain_aliases
                where lower(domain) = lower(:host)
                limit 1
            """),
            {"host": host},
        ).mappings().first()

        if DEBUG_TENANT:
            print(f"[tenant.resolve] match_found={bool(rec)} for host='{host}'")

        if not rec:
            raise HTTPException(status_code=404, detail="Dominio non configurato")

        slug = rec["slug"]
        is_primary = bool(rec["is_primary"])
        force_https = bool(rec["force_https"])

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
