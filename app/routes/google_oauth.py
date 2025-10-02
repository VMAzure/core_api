# app/routes/google_oauth.py
import os
import secrets
import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app import models

router = APIRouter(prefix="/auth/google", tags=["Google OAuth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _require_env():
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI):
        raise HTTPException(status_code=500, detail="Google OAuth env vars mancanti")


def _db() -> Session:
    return SessionLocal()


@router.get("/login")
def google_login():
    """
    Redirect immediato a Google. Usa direttamente un <a href="/auth/google/login">.
    """
    _require_env()
    url = (
        f"{OAUTH_AUTHORIZE_URL}"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=online"
        f"&include_granted_scopes=true"
        f"&prompt=select_account"
    )
    return RedirectResponse(url)


@router.get("/callback")
def google_callback(code: str, Authorize: AuthJWT = Depends()):
    _require_env()

    # 1. Scambio code → token Google
    token_res = requests.post(
        OAUTH_TOKEN_URL,
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if not token_res.ok:
        raise HTTPException(status_code=400, detail="Scambio code→token fallito")
    tokens = token_res.json()
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Token Google mancante")

    # 2. Userinfo
    ui = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if not ui.ok:
        raise HTTPException(status_code=400, detail="Lettura userinfo fallita")
    info = ui.json()

    email = info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email Google non disponibile")

    given = info.get("given_name", "") or ""
    family = info.get("family_name", "") or ""
    picture = info.get("picture", "") or ""

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).first()
        if not user:
            user = models.User(
                email=email,
                role="utente",
                nome=given,
                cognome=family,
                cellulare="to-complete",   # placeholder
                indirizzo="to-complete",   # placeholder
                cap="00000",               # placeholder
                citta="to-complete",       # placeholder
                avatar_url=picture or None,
            )
            user.set_password(secrets.token_urlsafe(32))
            db.add(user)
            db.commit()
            db.refresh(user)

        # 3. JWT interno
        jwt = Authorize.create_access_token(subject=user.email)

        # 4. Redirect al frontend con token in querystring
        frontend_url = f"https://www.gigigorilla.io/html/auth.html?token={jwt}"
        return RedirectResponse(url=frontend_url)
    finally:
        db.close()
