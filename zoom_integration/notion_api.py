# notion_api.py
import os
import httpx

NOTION_BASE = "https://api.notion.com/v1"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


async def send_meeting_to_notion(
    notion_token: str,
    notion_db_id: str,
    *,  # force keyword args
    topic: str,
    meeting_id: str | int,
    host_email: str | None,
    start_time: str | None,
    duration: int | None,
    join_url: str | None,
) -> None:
    payload = {
        "parent": {"database_id": notion_db_id},
        "properties": {
            "Name": {"title": [{"text": {"content": topic or "(no title)"}}]},
            "Meeting ID": {"rich_text": [{"text": {"content": str(meeting_id)}}]},
            "Host": {"rich_text": [{"text": {"content": host_email or ""}}]},
            "Start": {"date": {"start": start_time}} if start_time else {"date": None},
            "Duration (min)": {"number": duration},
            "Join URL": {"url": join_url},
            "Status": {"select": {"name": "Scheduled"}},
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{NOTION_BASE}/pages", headers=_headers(notion_token), json=payload)
        r.raise_for_status()
