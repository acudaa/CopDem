#!/usr/bin/env python3
"""Fetch an access token from the Copernicus Data Space Ecosystem (CDSE) API.

Credentials are read from environment variables (or a local .env file, which
is gitignored and must never be committed):

    CDSE_USERNAME
    CDSE_PASSWORD

Usage:
    from cdse_auth import get_access_token
    token = get_access_token()

    # or as a script:
    python cdse_auth.py
"""
import os
import sys

import requests
from dotenv import load_dotenv

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/"
    "openid-connect/token"
)
CLIENT_ID = "cdse-public"


def get_access_token() -> str:
    """Request a fresh access token using the resource-owner password grant.

    Raises RuntimeError if credentials are missing or the request fails.
    """
    load_dotenv()  # populates os.environ from a local .env, if present

    username = os.environ.get("CDSE_USERNAME")
    password = os.environ.get("CDSE_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "CDSE_USERNAME / CDSE_PASSWORD not set. Copy .env.example to "
            ".env and fill in your credentials, or export them as "
            "environment variables."
        )

    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "grant_type": "password",
            "username": username,
            "password": password,
        },
        timeout=30,
    )
    if not response.ok:
        # Don't leak the password in the error message.
        raise RuntimeError(
            f"CDSE token request failed ({response.status_code}): "
            f"{response.text[:500]}"
        )

    return response.json()["access_token"]


if __name__ == "__main__":
    try:
        token = get_access_token()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Access token acquired.")
    print(f"token (first 20 chars): {token[:20]}...")
