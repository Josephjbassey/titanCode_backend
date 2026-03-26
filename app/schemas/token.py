"""
TitanCode Technologies — Pydantic Schemas: Token
==================================================
Schemas for JWT authentication token responses.
"""

from pydantic import BaseModel


class Token(BaseModel):
    """
    Schema returned by the /auth/login and /auth/refresh endpoints.

    Attributes:
        access_token:  Short-lived JWT (15 min) sent with every API request.
        refresh_token: Long-lived JWT (7 days) used to renew access tokens.
        token_type:    Always "bearer" — tells the client how to send it.
    """
    access_token: str
    refresh_token: str
    token_type: str


class TokenPayload(BaseModel):
    """
    Schema representing the decoded contents (payload) of a JWT.

    Used internally to validate the token structure after decoding.

    Attributes:
        sub:  Subject — the user's ID (stored as a string in the JWT).
        exp:  Expiration — Unix timestamp when the token expires.
        type: Token type — "refresh" for refresh tokens, absent for access tokens.
    """
    sub: str | None = None
    exp: int | None = None
    type: str | None = None
