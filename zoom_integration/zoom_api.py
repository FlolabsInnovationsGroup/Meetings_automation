# zoom_api.py
import base64
import time
import httpx

ZOOM_OAUTH_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_API_BASE = "https://api.zoom.us/v2"


class ZoomAuthError(RuntimeError):
    pass


async def exchange_refresh_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """
    Exchange a Zoom OAuth refresh token for a fresh access token (and new refresh token).
    Returns dict with: access_token, refresh_token, expires_at (epoch seconds), scope, token_type.
    """
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(ZOOM_OAUTH_TOKEN_URL, data=data, headers=headers)
        if r.status_code != 200:
            raise ZoomAuthError(f"Refresh failed ({r.status_code}): {r.text}")
        tok = r.json()

    return {
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "expires_at": time.time() + float(tok.get("expires_in", 3600)),
        "scope": tok.get("scope"),
        "token_type": tok.get("token_type"),
    }


async def zoom_get(access_token: str, path: str, params: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{ZOOM_API_BASE}{path}", params=params, headers=headers)
        r.raise_for_status()
        return r.json()


async def list_all_users(access_token: str) -> list[dict]:
    users: list[dict] = []
    next_token = None
    while True:
        params = {"page_size": 300}
        if next_token:
            params["next_page_token"] = next_token
        data = await zoom_get(access_token, "/users", params)
        users.extend(data.get("users", []))
        next_token = data.get("next_page_token")
        if not next_token:
            break
    return users


async def list_scheduled_meetings(access_token: str, user_id: str) -> list[dict]:
    params = {"type": "scheduled", "page_size": 300}
    data = await zoom_get(access_token, f"/users/{user_id}/meetings", params)
    return data.get("meetings", [])
