# install_once.py
import base64
import httpx
import os
from urllib.parse import urlencode

ZOOM_OAUTH_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_API_BASE = "https://api.zoom.us/v2"


def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing ENV: {name}")
    return v


async def do_install():
    client_id = require_env("ZOOM_CLIENT_ID")
    client_secret = require_env("ZOOM_CLIENT_SECRET")
    redirect = require_env("ZOOM_REDIRECT_URI")

    # Step A: Build Zoom authorize URL
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
    }
    url = f"https://zoom.us/oauth/authorize?{urlencode(params)}"
    print("➡️  Open this in your browser:\n")
    print(url)
    print("\nAfter approval, paste the 'code' param below.\n")

    code = input("🔑 Enter the 'code' from URL: ").strip()

    # Step B: Exchange code for refresh_token + access token
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(ZOOM_OAUTH_TOKEN_URL, data=data, headers=headers)
        r.raise_for_status()
        tokens = r.json()

    print("\n✅ NEW REFRESH TOKEN — SAVE THIS IN .env NOW:\n")
    print(tokens["refresh_token"])
    print("\n(Then press CTRL+C to exit)\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(do_install())
