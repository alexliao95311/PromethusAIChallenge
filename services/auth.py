"""Server-side Firebase ID token verification (Increment 4).

Before this, DebateSim had no server-side auth at all: per-user Firestore
writes went straight from the browser via the Firebase client SDK
(protected only by Firestore security rules), and no FastAPI route ever
verified who was calling it. Per-user flashcard review progress is the
first feature where the *backend* must know -- and trust -- who the caller
is, since one user must never be able to read or overwrite another user's
Leitner progress. This module is the first `Depends(...)` auth dependency
in the codebase; there was no existing pattern to reuse.

The frontend must attach `Authorization: Bearer <Firebase ID token>`
(`auth.currentUser.getIdToken()`) to review endpoints for this to work.
"""

import logging

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import auth as firebase_auth
    FIREBASE_AUTH_AVAILABLE = True
except ImportError:
    FIREBASE_AUTH_AVAILABLE = False
    logger.warning("firebase-admin not installed. Authenticated endpoints will be unavailable.")


async def get_current_user_id(authorization: str = Header(default=None)) -> str:
    """FastAPI dependency: verify the Firebase ID token and return its uid.

    The uid always comes from the verified token -- never from a request
    body or query param -- so a client can never claim to be another user.
    """
    if not FIREBASE_AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Authentication is not configured on this server")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    id_token = authorization[len("Bearer "):].strip()
    if not id_token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception as e:
        logger.warning("Rejected invalid Firebase ID token: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")

    return decoded["uid"]
