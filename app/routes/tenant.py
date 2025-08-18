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
    # 1) X-Forwarded-Host (se presente), altrimenti Host
    xf_host = (request.headers.get("x-forwarded-host") or "").strip()
    raw_host = (xf_host or request.headers.get("host") or "").strip()

    # se multipli valori (es. "a,b"), prendi il primo
    raw_host = raw_host.split(",", 1)[0].strip()
    # togli eventuale :porta
    raw_host = raw_host.split(":", 1)[0].strip()
    # togli eventuale slash finale
    if raw_host.endswith("/"):
        raw_host = raw_host[:-1]
    return raw_host.lower()

@router.get("/resolve", response_model=TenantResolveResponse)
def resolve_tenant(request: Request):
    host = _normalize_host_from_request(request)
    print(f"[tenant.resolve] headers-keys={list(request.headers.keys())}")
    print(f"[tenant.resolve] host_normalized='{host}'")

    if not host:
        # 👇 stampa PRIMA di alzare l'errore
        print(f"[tenant.resolve] host mancante: raw headers={dict(request.headers)}")
        raise HTTPException(status_code=400, detail="Host header mancante")

    with engine.connect() as conn:
        # INFO DB (per evitare dubbi sull'origine dati)
        dbinfo = conn.execute(
            text("select current_database() as db, current_user as usr, current_schema as sch")
        ).mappings().first()
        print(f"[tenant.resolve] DBINFO db={dbinfo['db']} user={dbinfo['usr']} schema={dbinfo['sch']}")

        # piccolo sample per capire cosa vede la tabella
        sample = conn.execute(
            text("select domain from public.domain_aliases order by domain asc limit 5")
        ).mappings().all()
        print(f"[tenant.resolve] sample_domains={[r['domain'] for r in sample]}")

        rec = conn.execute(
            text("""
                select slug, is_primary, force_https
                from public.domain_aliases
                where lower(domain) = lower(:host)
                limit 1
            """),
            {"host": host},
        ).mappings().first()

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
