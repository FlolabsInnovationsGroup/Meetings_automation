import argparse
import json
import time
from datetime import datetime, timedelta, timezone
import requests

# -------------------
# CLI & Config
# -------------------

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# -------------------
# Utilities
# -------------------

REQ = requests.Session()

def utcnow():
    return datetime.now(timezone.utc)

def parse_iso(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def within_window(dt, start, end):
    return dt and start <= dt <= end

def log(*args):
    print("[INFO]", *args)

def warn(*args):
    print("[WARN]", *args)

def err(*args):
    print("[ERROR]", *args)

# -------------------
# Zoom helpers
# -------------------

def zoom_token(client_id, client_secret, account_id, timeout):
    url = "https://zoom.us/oauth/token"
    auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
    params = {"grant_type": "account_credentials", "account_id": account_id}
    r = REQ.post(url, auth=auth, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()["access_token"]

def zget(url, token, timeout, params=None):
    h = {"Authorization": f"Bearer {token}"}
    r = REQ.get(url, headers=h, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def zlist_users(token, timeout):
    url = "https://api.zoom.us/v2/users"
    users = []
    params = {"page_size": 300}
    while True:
        data = zget(url, token, timeout, params)
        users.extend(data.get("users", []))
        nxt = data.get("next_page_token")
        if not nxt:
            break
        params["next_page_token"] = nxt
    return users

def zlist_meetings_for_user(token, user_id, timeout):
    base = f"https://api.zoom.us/v2/users/{user_id}/meetings"
    meetings = []
    for mtype, extra in [
        ("scheduled", {"page_size": 300}),
        ("upcoming", {"show_all_occurrences": "true", "page_size": 300}),
    ]:
        params = {"type": mtype, **extra}
        while True:
            data = zget(base, token, timeout, params)
            meetings.extend(data.get("meetings", []))
            nxt = data.get("next_page_token")
            if not nxt:
                break
            params["next_page_token"] = nxt
    return meetings

def zget_meeting_detail(token, meeting_id, timeout):
    url = f"https://api.zoom.us/v2/meetings/{meeting_id}"
    return zget(url, token, timeout, {"show_previous_occurrences": "false"})

# -------------------
# Notion helpers
# -------------------

def notion_headers(notion_token):
    return {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

def notion_query_all(database_id, notion_token, page_size, timeout):
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload = {"page_size": page_size}
    out = []
    while True:
        r = REQ.post(url, headers=notion_headers(notion_token), data=json.dumps(payload), timeout=timeout)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return out

def notion_create(database_id, props, notion_token, timeout):
    url = "https://api.notion.com/v1/pages"
    payload = {"parent": {"database_id": database_id}, "properties": props}
    r = REQ.post(url, headers=notion_headers(notion_token), data=json.dumps(payload), timeout=timeout)
    r.raise_for_status()
    return r.json()

def notion_update(page_id, props, notion_token, timeout):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": props}
    r = REQ.patch(url, headers=notion_headers(notion_token), data=json.dumps(payload), timeout=timeout)
    r.raise_for_status()
    return r.json()

# -------------------
# Property helpers
# -------------------

def prop_text(v):     return {"rich_text":[{"text":{"content":str(v)}}]} if v else {"rich_text":[]}
def prop_title(v):    return {"title":[{"text":{"content":str(v or '')}}]}
def prop_number(v):   return {"number": (None if v is None else float(v))}
def prop_url(v):      return {"url": (v or None)}
def prop_date(dt):    return {"date":{"start": dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")}} if dt else {"date":None}
def prop_select(v):   return {"select":{"name":str(v)}} if v else {"select":None}

def read_text_prop(p, name):
    blk = p.get(name, {})
    txt = ""
    for rt in blk.get("rich_text", []):
        txt += rt.get("plain_text","") or rt.get("text",{}).get("content","") or ""
    return txt.strip()

def read_title_prop(p, name):
    blk = p.get(name, {})
    txt = ""
    for t in blk.get("title", []):
        txt += t.get("plain_text","") or t.get("text",{}).get("content","") or ""
    return txt.strip()

def read_num_prop(p, name):
    v = p.get(name, {}).get("number")
    return int(v) if isinstance(v, (int, float)) else None

# -------------------
# Normalization & diff
# -------------------

def normalize_occurrence(base, occ, account_key, host_email):
    topic   = base.get("topic", "(no topic)")
    mid     = int(base.get("id"))
    uuid    = base.get("uuid", "")
    tz      = base.get("timezone") or base.get("settings",{}).get("timezone") or ""
    host_id = base.get("host_id") or ""
    join    = base.get("join_url") or ""
    dur     = base.get("duration")
    occ_id  = ""
    start   = base.get("start_time")

    if occ:
        occ_id = occ.get("occurrence_id","") or ""
        start  = occ.get("start_time") or start
        dur    = occ.get("duration", dur)

    start_dt = parse_iso(start) if start else None
    status   = "Active"
    return {
        "topic": topic,
        "id": mid,
        "uuid": uuid,
        "occurrence_id": occ_id,
        "start_dt": start_dt,
        "duration": int(dur) if isinstance(dur, (int, float)) or (isinstance(dur, str) and dur.isdigit()) else None,
        "timezone": tz,
        "join_url": join,
        "host_id": host_id,
        "status": status,
        "account_key": account_key,
        "host_email": host_email or ""
    }

def build_props(item, propnames):
    return {
        propnames["title"]:      prop_title(item["topic"]),
        propnames["id"]:         prop_number(item["id"]),
        propnames["uuid"]:       prop_text(item["uuid"]),
        propnames["occurrence"]: prop_text(item["occurrence_id"]),
        propnames["start"]:      prop_date(item["start_dt"]),
        propnames["duration"]:   prop_number(item["duration"]),
        propnames["timezone"]:   prop_text(item["timezone"]),
        propnames["join_url"]:   prop_url(item["join_url"]),
        propnames["host_id"]:    prop_text(item["host_id"]),
        propnames["status"]:     prop_select(item["status"]),
        propnames["account"]:    prop_text(item["account_key"]),
        propnames["user_email"]: prop_text(item["host_email"]),
    }

def page_key_from_props(p, propnames):
    props = p.get("properties", {})
    meeting_id = read_num_prop(props, propnames["id"])
    occ_id     = read_text_prop(props, propnames["occurrence"]) or ""
    start_iso  = props.get(propnames["start"], {}).get("date", {}).get("start", "") or ""
    return (meeting_id or 0, occ_id or start_iso)

def same_page(existing_props, new_props, propnames):
    fields = [
        propnames["title"], propnames["id"], propnames["uuid"], propnames["occurrence"],
        propnames["start"], propnames["duration"], propnames["timezone"], propnames["join_url"],
        propnames["host_id"], propnames["status"], propnames["account"], propnames["user_email"]
    ]
    return all(existing_props.get(f) == new_props.get(f) for f in fields)

# -------------------
# Main run
# -------------------

def run(config: dict):
    notion_token       = config["notion_token"]
    notion_database_id = config["notion_database_id"]
    accounts           = config["zoom_accounts"]
    lookahead_days     = int(config.get("lookahead_days", 60))
    timeout            = int(config.get("http_timeout_seconds", 20))
    page_size          = int(config.get("notion_page_size", 50))

    # Property names
    prop_map = config.get("property_map") or {}
    propnames = {
        "title":      prop_map.get("title", "Topic"),
        "id":         prop_map.get("id", "Meeting ID"),
        "uuid":       prop_map.get("uuid", "UUID"),
        "occurrence": prop_map.get("occurrence", "Occurrence ID"),
        "start":      prop_map.get("start", "Start"),
        "duration":   prop_map.get("duration", "Duration (min)"),
        "timezone":   prop_map.get("timezone", "Timezone"),
        "join_url":   prop_map.get("join_url", "Join URL"),
        "host_id":    prop_map.get("host_id", "Host ID"),
        "status":     prop_map.get("status", "Status"),
        "account":    prop_map.get("account", "Zoom Account"),
        "user_email": prop_map.get("user_email", "Host Email"),
    }

    now = utcnow()
    window_end = now + timedelta(days=lookahead_days)

    # 1) Harvest Zoom future occurrences
    occurrences = []
    for account_key, cfg in accounts.items():
        log(f"Zoom account: {account_key}")
        try:
            token = zoom_token(cfg["client_id"], cfg["client_secret"], cfg["account_id"], timeout)
        except Exception as e:
            err(f"Zoom token failed for {account_key}: {e}")
            continue

        try:
            users = zlist_users(token, timeout)
        except Exception as e:
            err(f"List users failed for {account_key}: {e}")
            continue

        for u in users:
            uid   = u.get("id")
            email = u.get("email") or ""
            if not uid: 
                continue

            try:
                items = zlist_meetings_for_user(token, uid, timeout)
            except Exception as e:
                warn(f"Meetings failed for {email}: {e}")
                continue

            by_id = {}
            for m in items:
                try:
                    by_id.setdefault(m["id"], m)
                except Exception:
                    continue

            for mid, base in by_id.items():
                is_recurring = (base.get("type") in (8,)) or ("occurrences" in base)
                if is_recurring:
                    try:
                        detail = zget_meeting_detail(token, mid, timeout)
                        occs = detail.get("occurrences", []) or []
                    except Exception:
                        occs = base.get("occurrences", []) or []
                    for occ in occs:
                        n = normalize_occurrence(base, occ, account_key, email)
                        if n["start_dt"] and within_window(n["start_dt"], now, window_end):
                            occurrences.append(n)
                else:
                    n = normalize_occurrence(base, None, account_key, email)
                    if n["start_dt"] and within_window(n["start_dt"], now, window_end):
                        occurrences.append(n)

    log(f"Collected {len(occurrences)} Zoom occurrences in window")

    # 2) Build key map
    zoom_map = {}
    for n in occurrences:
        key = (n["id"], n["occurrence_id"] or n["start_dt"].isoformat())
        zoom_map[key] = n

    # 3) Load Notion DB
    pages = notion_query_all(notion_database_id, notion_token, page_size, timeout)
    notion_index = {}
    for p in pages:
        key = page_key_from_props(p, propnames)
        notion_index[key] = {"page_id": p["id"], "properties": p["properties"]}

    # 4) Upsert
    created = updated = 0
    for key, item in zoom_map.items():
        props = build_props(item, propnames)
        if key in notion_index:
            existing = notion_index[key]
            if not same_page(existing["properties"], props, propnames):
                notion_update(existing["page_id"], props, notion_token, timeout)
                updated += 1
        else:
            notion_create(notion_database_id, props, notion_token, timeout)
            created += 1

    # 5) Cancel missing-in-Zoom within the window
    cancelled = 0
    for key, rec in notion_index.items():
        mid, second = key
        start_iso = rec["properties"].get(propnames["start"], {}).get("date", {}).get("start")
        dt = parse_iso(start_iso) if start_iso else None
        if dt and within_window(dt, now, window_end):
            if key not in zoom_map:
                upd = { propnames["status"]: prop_select("Cancelled") }
                notion_update(rec["page_id"], upd, notion_token, timeout)
                cancelled += 1

    log(f"Created: {created} | Updated: {updated} | Cancelled: {cancelled} | Pages scanned: {len(pages)}")
    return {
        "zoom_occurrences": len(occurrences),
        "created": created,
        "updated": updated,
        "cancelled": cancelled,
        "pages_scanned": len(pages)
    }

# -------------------
# Entry point
# -------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zoom → Notion polling (local)")
    parser.add_argument("--config", "-c", required=True, help="Path to config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    result = run(cfg)
    print(json.dumps(result, indent=2))
