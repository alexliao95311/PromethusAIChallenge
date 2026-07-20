"""Shared Firebase Admin / Firestore client initialization for services.

Mirrors the lazy-init pattern main.py uses for its own `get_firestore_db()`,
but lives in its own module so lesson-mode services can obtain a Firestore
client without importing from main.py (which would risk a circular import
once main.py starts wiring up lesson routes). Both initializers defensively
check `firebase_admin.get_app()` first, so whichever runs first initializes
the app and the other just reuses it.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning(
        "firebase-admin not installed. Lesson data will not be persisted to Firestore."
    )

_CREDENTIALS_PATH = (
    Path(__file__).resolve().parent.parent
    / "credentials"
    / "debatesim-6f403-55fd99aa753a-google-cloud.json"
)

_firestore_db = None


def get_firestore_db():
    """Initialize (once) and return the shared Firestore client, or None if unavailable."""
    global _firestore_db
    if _firestore_db is not None:
        return _firestore_db

    if not FIREBASE_AVAILABLE:
        return None

    if not _CREDENTIALS_PATH.exists():
        logger.error(f"Firebase credentials not found at {_CREDENTIALS_PATH}")
        return None

    try:
        firebase_admin.get_app()
        logger.info("Firebase app already initialized, reusing it for Firestore client")
    except ValueError:
        cred = credentials.Certificate(str(_CREDENTIALS_PATH))
        firebase_admin.initialize_app(cred)
        logger.info("Firebase app initialized by services.firebase_client")

    _firestore_db = firestore.client()
    return _firestore_db
