"""مدیریت Session با کوکی امضا شده"""
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from fastapi import Request, Response
from typing import Optional, Dict
from web.config import WebConfig

serializer = URLSafeTimedSerializer(WebConfig.SECRET_KEY)


def create_session_token(user_id: str, role: str) -> str:
    return serializer.dumps({"user_id": user_id, "role": role})


def verify_session_token(token: str) -> Optional[Dict]:
    try:
        return serializer.loads(token, max_age=WebConfig.SESSION_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None


def set_session_cookie(response: Response, user_id: str, role: str) -> None:
    token = create_session_token(user_id, role)
    response.set_cookie(
        key=WebConfig.SESSION_COOKIE_NAME,
        value=token,
        max_age=WebConfig.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax"
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=WebConfig.SESSION_COOKIE_NAME)


def get_session_from_request(request: Request) -> Optional[Dict]:
    token = request.cookies.get(WebConfig.SESSION_COOKIE_NAME)
    if not token:
        return None
    return verify_session_token(token)