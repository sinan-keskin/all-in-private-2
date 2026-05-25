# zendesk_reports/utils.py
from __future__ import annotations
# utils.py (üst import satırlarına ekleyin)
import random, threading, os
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

import base64, time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Tuple, Optional

import requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed

# ======= Global HTTP Session (keep-alive + pool) =======
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=0)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)
_DEFAULT_TIMEOUT = 30  # sn

# =================
# Auth & mini utils
# =================
def auth_headers(email_token: str, api_token: str) -> Dict[str, str]:
    auth = base64.b64encode(f"{email_token}:{api_token}".encode()).decode()
    return {
        "Authorization": f"Basic {auth}",
        "User-Agent": "zendesk-reports/fast-robust-2.0",
        "Accept": "application/json",
    }

def _utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _chunks(lst: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(lst), size):
        yield lst[i:i+size]

def _req(method: str, url: str, headers: Dict[str, str], params=None, json=None, max_retry: int = 5):
    """429/5xx için hafif backoff; Retry-After'a saygı."""
    last = None
    for attempt in range(max_retry):
        r = _session.request(method, url, headers=headers, params=params, json=json, timeout=_DEFAULT_TIMEOUT)
        last = r
        if r.status_code in (429, 500, 502, 503, 504):
            ra = r.headers.get("Retry-After")
            if ra:
                try: wait = float(ra)
                except Exception: wait = 1.0
            else:
                wait = min(0.5 * (2**attempt), 6.0)
            time.sleep(wait); continue
        return r
    return last

# ============================
# Tarih penceresi yardımcıları
# ============================
def tr_yesterday_range(tz_offset_hours: int = 3) -> Tuple[int, int]:
    now_utc = datetime.now(timezone.utc)
    tr_now = now_utc + timedelta(hours=tz_offset_hours)
    y = tr_now.date() - timedelta(days=1)
    tr_start = datetime(y.year, y.month, y.day, 0,0,0, tzinfo=timezone.utc) - timedelta(hours=tz_offset_hours)
    tr_end   = datetime(y.year, y.month, y.day, 23,59,59, tzinfo=timezone.utc) - timedelta(hours=tz_offset_hours)
    return int(tr_start.timestamp()), int(tr_end.timestamp())

def range_by_report_type(report_type: str, tz_offset_hours: int = 3) -> Tuple[int, int]:
    report_type = (report_type or "DAILY").upper()
    now_utc = datetime.now(timezone.utc)
    tr_now = now_utc + timedelta(hours=tz_offset_hours)

    if report_type == "DAILY":
        return tr_yesterday_range(tz_offset_hours)

    if report_type == "WEEKLY":
        end_tr = tr_now.date() - timedelta(days=1)   # dün
        start_tr = end_tr - timedelta(days=6)
        s = datetime(start_tr.year, start_tr.month, start_tr.day, 0,0,0, tzinfo=timezone.utc) - timedelta(hours=tz_offset_hours)
        e = datetime(end_tr.year, end_tr.month, end_tr.day, 23,59,59, tzinfo=timezone.utc) - timedelta(hours=tz_offset_hours)
        return int(s.timestamp()), int(e.timestamp())

    if report_type == "MONTHLY":
        first_this = datetime(tr_now.year, tr_now.month, 1).date()
        last_end = first_this - timedelta(days=1)  # geçen ayın son günü
        s = datetime(last_end.year, last_end.month, 1, 0,0,0, tzinfo=timezone.utc) - timedelta(hours=tz_offset_hours)
        e = datetime(last_end.year, last_end.month, last_end.day, 23,59,59, tzinfo=timezone.utc) - timedelta(hours=tz_offset_hours)
        return int(s.timestamp()), int(e.timestamp())

    return tr_yesterday_range(tz_offset_hours)

# utils.py (yardımcı): Hata aldıkça exponential backoff ile sonsuza kadar dene
def _retry_forever(fn, *, label: str = "", start_wait: float = 0.5, max_wait: float = 60.0):
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            wait = min(max_wait, start_wait * (2 ** attempt)) + random.uniform(0, 0.25)
            if label:
                print(f"[retry] {label} -> {e} (sleep {wait:.2f}s, attempt {attempt+1})")
            time.sleep(wait)
            attempt += 1


# ==========================================
# FAST FETCH: Search API (+ show_many detay)
# ==========================================
def _time_clause(ts1: int, ts2: int, field: str) -> str:
    s, e = _utc_iso(ts1), _utc_iso(ts2)
    return f"{field}>={s} {field}<={e}"

def _search_once(
    subdomain: str,
    headers: Dict[str, str],
    q: str,
    page: int = 1,
    per_page: int = 50
) -> Dict:

    url = f"https://{subdomain}.zendesk.com/api/v2/search.json"

    params = {
        "query": q,
        "page": page,
        "per_page": per_page,
    }

    r = _req("GET", url, headers, params=params)

    if r.status_code != 200:
        raise RuntimeError(
            f"Search API hata: {r.status_code} — {r.text[:200]}"
        )

    return r.json() or {}

def _show_many(subdomain: str, headers: Dict[str, str], ids: List[int]) -> List[dict]:
    if not ids: return []
    out: List[dict] = []
    for batch in _chunks([str(i) for i in ids], 100):
        url = f"https://{subdomain}.zendesk.com/api/v2/tickets/show_many.json"
        r = _req("GET", url, headers, params={"ids": ",".join(batch)})
        if r.status_code != 200:
            raise RuntimeError(f"show_many hata: {r.status_code} — {r.text[:200]}")
        out.extend((r.json() or {}).get("tickets") or [])
    return out

def search_fetch_window(
    subdomain: str,
    headers: Dict[str, str],
    start_ts: int,
    end_ts: int,
    brand_id: Optional[int] = None,
    per_page: int = 50,
    mode: str = "both",
    debug: bool = True
) -> List[dict]:

    base = "type:ticket" + (
        f" brand:{brand_id}" if brand_id else ""
    )

    queries = []

    if mode in ("created", "both"):
        queries.append(
            f"{base} {_time_clause(start_ts, end_ts, 'created')}"
        )

    if mode in ("updated", "both"):
        queries.append(
            f"{base} {_time_clause(start_ts, end_ts, 'updated')}"
        )

    all_ids: set[int] = set()

    for q in queries:
        page = 1

        if debug:
            print(f"[search] q={q}")

        while True:

            data = _search_once(
                subdomain,
                headers,
                q,
                page=page,
                per_page=per_page
            )

            res = data.get("results") or []

            if debug and page == 1:
                print(f"[search] first page hits={len(res)}")

            if not res:
                break

            for r in res:
                _id = r.get("id")

                if _id:
                    all_ids.add(int(_id))

            if not data.get("next_page"):
                break

            page += 1

    ids = sorted(all_ids)

    if debug:
        print(f"[search] total unique ids={len(ids)}")

    if not ids:
        return []

    return _show_many(subdomain, headers, ids)



# --- 422 güvenli sarmalayıcı ---
def _search_is_response_too_large(err_text: str) -> bool:
    t = (err_text or "").lower()
    return "requested response size" in t and "search response limits" in t

def search_fetch_window_safe(
    subdomain: str,
    headers: Dict[str, str],
    start_ts: int,
    end_ts: int,
    brand_id: Optional[int] = None,
    per_page: int = 50,
    mode: str = "both",
    debug: bool = True
) -> List[dict]:

    try:
        return search_fetch_window(
            subdomain,
            headers,
            start_ts,
            end_ts,
            brand_id,
            per_page,
            mode,
            debug
        )

    except RuntimeError as e:

        msg = str(e)

        if _search_is_response_too_large(msg):

            if debug:
                print("[search-safe] response too large -> chunk by day")

            out: Dict[int, dict] = {}

            cur = start_ts
            one_day = 24 * 3600

            while cur <= end_ts:

                day_end = min(
                    end_ts,
                    cur + one_day - 1
                )

                try:
                    items = search_fetch_window(
                        subdomain,
                        headers,
                        cur,
                        day_end,
                        brand_id,
                        per_page,
                        mode,
                        debug
                    )

                    for t in items:
                        out[int(t["id"])] = t

                except RuntimeError as e2:

                    if debug:
                        print(
                            f"[search-safe] skip "
                            f"{_utc_iso(cur)}..{_utc_iso(day_end)}: {e2}"
                        )

                    time.sleep(0.4)

                cur = day_end + 1

            if debug:
                print(
                    f"[search-safe] chunked unique ids={len(out)}"
                )

            return list(out.values())

        if debug:
            print(
                f"[search-safe] giving up search due to: {msg}"
            )

        return []

# ===========================================
# FAST for small/med ranges: Parallel Incremental (list return)
# ===========================================
def incremental_fetch_window(subdomain: str, headers: Dict[str, str],
                             start_ts: int, end_ts: int,
                             brand_id: Optional[int] = None,
                             debug: bool = False) -> List[dict]:
    url = f"https://{subdomain}.zendesk.com/api/v2/incremental/tickets.json?start_time={start_ts}"
    by_id: Dict[int, dict] = {}
    if debug: print(f"[chunk] start {_utc_iso(start_ts)}..{_utc_iso(end_ts)}")

    while url:
        def _do():
            r = _req("GET", url, headers=headers)
            if r.status_code != 200:
                raise RuntimeError(f"Incremental API hata: {r.status_code} — {r.text[:200]}")
            return r.json() or {}

        data = _retry_forever(_do, label="incremental_page")

        stop = False
        for t in data.get("tickets", []):
            try:
                ca = t.get("created_at") or ""
                created = datetime.fromisoformat(ca.replace("Z","+00:00")).timestamp()
            except Exception:
                created = start_ts
            if created < start_ts:  continue
            if created > end_ts:    stop = True; continue
            if brand_id and t.get("brand_id") != brand_id: continue
            by_id[int(t["id"])] = t

        if stop or data.get("end_of_stream"): break
        url = data.get("next_page")
    if debug: print(f"[incremental-window] {len(by_id)} ids ({_utc_iso(start_ts)}..{_utc_iso(end_ts)})")
    return list(by_id.values())


def incremental_fetch_parallel(subdomain: str, headers: Dict[str, str],
                               start_ts: int, end_ts: int,
                               brand_id: Optional[int] = None,
                               chunk_days: int = 7, workers: int = 6,
                               debug: bool = True) -> List[dict]:
    chunks: List[Tuple[int,int]] = []
    cur = start_ts; step = chunk_days * 24 * 3600
    while cur <= end_ts:
        nxt = min(end_ts, cur + step - 1)
        chunks.append((cur, nxt)); cur = nxt + 1

    if debug: print(f"[parallel] launching {len(chunks)} chunks (chunk_days={chunk_days}, workers={workers})")

    all_by_id: Dict[int, dict] = {}
    pending = {c: 0 for c in chunks}  # (s,e) -> attempt

    while pending:
        batch = list(pending.keys())
        if debug: print(f"[parallel] run batch: {len(batch)} pending")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(incremental_fetch_window, subdomain, headers, s, e, brand_id, debug):(s,e) for (s,e) in batch}
            for fut in as_completed(futs):
                s,e = futs[fut]
                try:
                    items = fut.result()
                    for t in items: all_by_id[int(t["id"])] = t
                    del pending[(s,e)]  # başarı: çıkar
                except Exception as er:
                    att = pending[(s,e)] + 1
                    pending[(s,e)] = att
                    wait = min(60.0, 0.5 * (2 ** att)) + random.uniform(0, 0.25)
                    if debug: print(f"[parallel-chunk ERR] {er} ({_utc_iso(s)}..{_utc_iso(e)}) -> retry in {wait:.2f}s (attempt {att})")
                    time.sleep(wait)
    if debug: print(f"[incremental-parallel] unique ids={len(all_by_id)} (chunks completed)")
    return list(all_by_id.values())


# ===============================
# SLOW BUT SURE: Incremental API (tek akış)
# ===============================
def incremental_fetch(subdomain: str, headers: Dict[str, str],
                      start_ts: int, end_ts: int,
                      brand_id: Optional[int] = None,
                      debug: bool = True) -> List[dict]:
    url = f"https://{subdomain}.zendesk.com/api/v2/incremental/tickets.json?start_time={start_ts}"
    by_id: Dict[int, dict] = {}
    while url:
        def _do():
            r = _req("GET", url, headers=headers)
            if r.status_code != 200:
                raise RuntimeError(f"Incremental API hata: {r.status_code} — {r.text[:200]}")
            return r.json() or {}

        data = _retry_forever(_do, label="incremental_page")

        for t in data.get("tickets", []):
            ca = t.get("created_at") or ""
            try:
                created = datetime.fromisoformat(ca.replace("Z","+00:00")).timestamp()
            except Exception:
                created = start_ts
            if created < start_ts or created > end_ts: continue
            if brand_id and t.get("brand_id") != brand_id: continue
            by_id[int(t["id"])] = t

        if data.get("end_of_stream"): break
        url = data.get("next_page")
        time.sleep(0.15)
    if debug: print(f"[incremental] unique ids={len(by_id)}")
    return list(by_id.values())


# ==================
# Sayım / Kategoriler
# ==================
_STATUS_SOLVED  = {"solved", "closed"}
_STATUS_PENDING = {"open", "pending", "new"}
_STATUS_HOLD    = {"hold", "on-hold"}

def count_by_category(tickets: List[dict], form_map: Dict[int, str]) -> Dict[str, Dict[str, int]]:
    out = {name: {"Çözülen":0, "Bekleyen":0, "Askıda":0} for name in form_map.values()}
    for t in tickets:
        cat = form_map.get(t.get("ticket_form_id"))
        if not cat: continue
        st = str(t.get("status") or "").lower()
        if st in _STATUS_SOLVED:   out[cat]["Çözülen"] += 1
        elif st in _STATUS_PENDING:out[cat]["Bekleyen"] += 1
        elif st in _STATUS_HOLD:   out[cat]["Askıda"]   += 1
    return out

def totals(counts: Dict[str, Dict[str, int]]) -> Tuple[int, int, int, int]:
    """Dönüş: (çözülen, bekleyen, askıda, toplam)."""
    s = p = h = 0
    for v in counts.values():
        s += int(v.get("Çözülen", 0))
        p += int(v.get("Bekleyen", 0))
        h += int(v.get("Askıda",   0))
    return s, p, h, s + p + h

# ===============
# Slack formatı
# ===============
def format_blocks(counts: Dict[str, Dict[str, int]], title: str) -> List[dict]:
    emoji = {"Ceza İtiraz":"📝","E-Posta Değişikliği":"✉️","Etkinlik & Kampanya Sorun":"🎉",
             "Hesap Güvenliği":"🔒","Hile Şikayeti":"🎯","Küfür / Hakaret Şikayeti":"🤬",
             "Oyuna Giriş / Bağlantı":"🎮","Teknik Sorunlar":"🛠️","Ödemeler":"💳"}
    blocks = [{"type":"header","text":{"type":"plain_text","text":title}},{"type":"divider"}]
    ts=tp=th=0
    for k in sorted(counts.keys()):
        v=counts[k]; s=int(v.get("Çözülen",0)); p=int(v.get("Bekleyen",0)); h=int(v.get("Askıda",0)); tot=s+p+h
        ts+=s; tp+=p; th+=h
        blocks.append({"type":"section","text":{"type":"mrkdwn",
            "text":f"*{emoji.get(k,'📁')} {k}*\n✅ Çözülen: *{s}*  | 🕓 Bekleyen: *{p}* | ⏸️ Askıda: *{h}*\n📊 Toplam: *{tot}*"}})
    blocks += [{"type":"divider"},{"type":"section","text":{"type":"mrkdwn",
               "text":f"*🔢 Genel Toplamlar:*\n✅ Çözülen: *{ts}*  | 🕓 Bekleyen: *{tp}* | ⏸️ Askıda: *{th}*\n📊 Toplam: *{ts+tp+th}*"}}]
    return blocks

# =========================
# STREAMING MONTHLY COUNTING
# =========================
def _bump(counts: Dict[str, Dict[str, int]], cat: str, status: str):
    if not cat: return
    c = counts.setdefault(cat, {"Çözülen":0, "Bekleyen":0, "Askıda":0})
    st = (status or "").lower()
    if st in _STATUS_SOLVED:          c["Çözülen"] += 1
    elif st in _STATUS_HOLD:          c["Askıda"]   += 1
    else:                             c["Bekleyen"] += 1

def incremental_count_window_stream(subdomain: str, headers: Dict[str,str],
    start_ts: int, end_ts: int, brand_id: Optional[int], form_map: Dict[int,str],
    debug: bool = False) -> Dict[str, Dict[str, int]]:
    """Tek pencereyi (örn. 1 gün) incremental export ile stream ederek sayar."""
    loc_headers = dict(headers); loc_headers["Accept-Encoding"] = "gzip"
    url = f"https://{subdomain}.zendesk.com/api/v2/incremental/tickets.json?start_time={start_ts}"
    counts: Dict[str, Dict[str, int]] = {}
    if debug: print(f"[chunk] start {_utc_iso(start_ts)}..{_utc_iso(end_ts)}")
    stop = False
    while url:
        r = _req("GET", url, headers=loc_headers)
        if r.status_code != 200: raise RuntimeError(f"Incremental API hata: {r.status_code} — {r.text[:200]}")
        data = r.json() or {}
        for t in data.get("tickets", []):
            try:
                ca = t.get("created_at") or ""
                created = datetime.fromisoformat(ca.replace("Z","+00:00")).timestamp()
            except Exception:
                created = start_ts
            if created < start_ts: continue
            if created > end_ts:   stop = True; continue
            if brand_id and t.get("brand_id") != brand_id: continue
            form_id = t.get("ticket_form_id")
            _bump(counts, form_map.get(form_id), t.get("status") or "")
        if stop or data.get("end_of_stream"): break
        url = data.get("next_page")
    if debug:
        tot = sum(v["Çözülen"]+v["Bekleyen"]+v["Askıda"] for v in counts.values())
        print(f"[chunk] done -> {tot} items ({_utc_iso(start_ts)}..{_utc_iso(end_ts)})")
    return counts

def incremental_count_parallel(subdomain: str, headers: Dict[str,str],
    start_ts: int, end_ts: int, brand_id: Optional[int], form_map: Dict[int,str],
    chunk_days: int = 1, workers: int = 12, debug: bool = True) -> Dict[str, Dict[str,int]]:

    chunks = []; cur = start_ts; step = chunk_days * 24 * 3600
    while cur <= end_ts:
        nxt = min(end_ts, cur + step - 1)
        chunks.append((cur, nxt)); cur = nxt + 1
    if debug: print(f"[parallel] {len(chunks)} chunks; chunk_days={chunk_days}, workers={workers}")

    merged: Dict[str, Dict[str,int]] = {}
    def merge(src: Dict[str, Dict[str,int]]):
        for k,v in src.items():
            m = merged.setdefault(k, {"Çözülen":0,"Bekleyen":0,"Askıda":0})
            m["Çözülen"] += v.get("Çözülen",0)
            m["Bekleyen"]+= v.get("Bekleyen",0)
            m["Askıda"]  += v.get("Askıda",0)

    pending = {c: 0 for c in chunks}
    while pending:
        batch = list(pending.keys())
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(incremental_count_window_stream, subdomain, headers, s, e, brand_id, form_map, debug):(s,e) for (s,e) in batch}
            for fut in as_completed(futs):
                s,e = futs[fut]
                try:
                    part = fut.result()
                    merge(part)
                    del pending[(s,e)]
                except Exception as er:
                    att = pending[(s,e)] + 1
                    pending[(s,e)] = att
                    wait = min(60.0, 0.5 * (2 ** att)) + random.uniform(0, 0.25)
                    if debug: print(f"[parallel ERR] {_utc_iso(s)}..{_utc_iso(e)} -> {er} -> retry in {wait:.2f}s (attempt {att})")
                    time.sleep(wait)

    if debug:
        tot = sum(v["Çözülen"]+v["Bekleyen"]+v["Askıda"] for v in merged.values())
        print(f"[parallel] merged total={tot} (all chunks completed)")
    return merged


# ------- public exports -------
__all__ = [
    "auth_headers",
    "tr_yesterday_range", "range_by_report_type",
    "search_fetch_window", "search_fetch_window_safe",
    "incremental_fetch_window", "incremental_fetch_parallel", "incremental_fetch",
    "count_by_category", "totals", "format_blocks",
    "incremental_count_window_stream", "incremental_count_parallel",
]

