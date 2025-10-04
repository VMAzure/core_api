import os
import secrets
import requests
from datetime import datetime, timedelta
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

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "300"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))


def _require_env():
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI):
        raise HTTPException(status_code=500, detail="Google OAuth env vars mancanti")


@router.get("/login")
def google_login():
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
    google_access = tokens.get("access_token")
    if not google_access:
        raise HTTPException(status_code=400, detail="Token Google mancante")

    # 2. Userinfo
    ui = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {google_access}"},
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

        # 3. JWT access interno (5h o come da config)
        access_token = Authorize.create_access_token(
            subject=user.email,
            expires_time=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            user_claims={
                "id": user.id,
                "role": user.role,
                "nome": user.nome,
                "cognome": user.cognome,
            }
        )

        # 4. Refresh token persistito in DB
        db.query(models.RefreshToken).filter(models.RefreshToken.user_id == user.id).delete()
        refresh_token = secrets.token_urlsafe(64)
        expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        db.add(models.RefreshToken(user_id=user.id, token=refresh_token, expires_at=expires_at))
        db.commit()

        # 5. Redirect al frontend con entrambi i token
        frontend_url = (
            f"https://www.gigigorilla.io/auth.html"
            f"?access_token={access_token}"
            f"&refresh_token={refresh_token}"
        )
        return RedirectResponse(url=frontend_url)


    finally:
        db.close()
