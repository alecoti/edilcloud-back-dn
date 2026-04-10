from dataclasses import dataclass

import jwt
from django.contrib.auth import get_user_model
from ninja.errors import HttpError
from ninja.security import APIKeyHeader

from edilcloud.modules.identity.services import decode_access_token
from edilcloud.platform.logging import update_request_context


@dataclass
class AuthenticatedIdentity:
    user: object
    claims: dict


class JWTAuth(APIKeyHeader):
    param_name = "Authorization"

    def authenticate(self, request, key):
        raw_auth = (key or "").strip()
        token = raw_auth

        if raw_auth.startswith("JWT "):
            token = raw_auth[4:].strip()
        elif raw_auth.startswith("Bearer "):
            token = raw_auth[7:].strip()

        if not token:
            raise HttpError(401, "Sessione non valida o scaduta.")

        try:
            claims = decode_access_token(token)
        except jwt.ExpiredSignatureError as exc:
            raise HttpError(401, "Sessione non valida o scaduta.") from exc
        except jwt.InvalidTokenError as exc:
            raise HttpError(401, "Token non valido.") from exc

        user_id = int(claims.get("sub"))
        user = get_user_model().objects.filter(id=user_id, is_active=True).first()
        if user is None:
            raise HttpError(401, "Utente non valido.")

        update_request_context(
            user_id=user.id,
            session_id=claims.get("sid"),
            profile_id=(claims.get("extra") or {}).get("profile", {}).get("id")
            if isinstance((claims.get("extra") or {}).get("profile"), dict)
            else None,
        )
        identity = AuthenticatedIdentity(user=user, claims=claims)
        request.auth = identity
        return identity
