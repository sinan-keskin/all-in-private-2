import os, json, requests, re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from .utils import (
    auth_headers, range_by_report_type,
    search_fetch_window, incremental_fetch_parallel,
    count_by_category, format_blocks,
    incremental_count_parallel,   # MONTHLY streaming
)
from .maps_wolfteam import FORM_MAP

TITLE = {
    "DAILY":   "📅 Wolfteam Günlük Zendesk Raporu",
    "WEEKLY":  "📊 Wolfteam Haftalık Zendesk Raporu",
    "MONTHLY": "📈 Wolfteam Aylık Zendesk Raporu",
}

# Rapor tipi -> Türkçe prefix
PERIOD_PREFIX = {
    "DAILY": "Günlük",
    "WEEKLY": "Haftalık",
    "MONTHLY": "Aylık",
}

DEFAULT_BRAND_ID = 33471181389841
WOLFTEAM_SHEET_ID = os.getenv("WOLFTEAM_SHEET_ID", "1ZmFn4W1X85S8u3fqkaptmJ44ywa-bScvQX0QkAJbcWw")

CATEGORY_CELL_MAP = {
    "Ceza İtiraz": (5, 6),
    "Etkinlik & Kampanya Sorun": (7, 8),
    "Hesap Güvenliği": (9, 10),
    "Hile Şikayeti": (11, 12),
    "Küfür / Hakaret Şikayeti": (13, 14),
    "E-Posta Değişikliği": (15, 16),
    "Ödemeler": (17, 18),
    "Oyuna Giriş / Bağlantı": (19, 20),
    "Teknik Sorunlar": (21, 22),
}

# --- İstatistikleri yazacağın hücreler (örnek) ---
# Bunları kendi şablonuna göre güncelle:
STATS_CELL_MAP = {
    "reply_rate":        "C22",  # Yanıtlanan %
    "non_reply_rate":    "C23",  # Yanıtlanmayan %
    "satisfaction_rate": "C24",  # Memnuniyet %
}

# ---------- APP_SECRETS ----------
def _env_from_app_secrets() -> Dict[str, str]:
    raw = os.getenv("APP_SECRETS")
    if not raw:
        return {}
    try:
        j = json.loads(raw)
        wolf = ((j.get("zendesk") or {}).get("wolfteam") or {})
        slack = ((j.get("slack") or {}).get("webhooks") or {}).get("wolfteam", "")
        sheets = j.get("GOOGLE_SHEETS_CREDENTIALS") or {}
        return {
            "ZENDESK_SUBDOMAIN": wolf.get("subdomain", ""),
            "ZENDESK_EMAIL_TOKEN": wolf.get("email_token", ""),
            "ZENDESK_API_TOKEN": wolf.get("api_token", ""),
            "SLACK_WEBHOOK_URL": slack,
            "GOOGLE_SHEETS_CREDENTIALS": json.dumps(sheets),
        }
    except Exception:
        return {}

def _brand_id() -> int:
    s = (os.getenv("WOLFTEAM_BRAND_ID") or os.getenv("BRAND_ID") or "").strip()
    if s:
        try: return int(s)
        except: pass
    return DEFAULT_BRAND_ID

# ---------- Google Sheets ----------
def _sheet_client():
    import gspread
    from google.oauth2.service_account import Credentials

    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json and creds_json.strip():
        info = json.loads(creds_json)
    else:
        fb = _env_from_app_secrets().get("GOOGLE_SHEETS_CREDENTIALS")
        info = json.loads(fb) if fb else {}

    if not info:
        raise RuntimeError("Google service account bilgisi bulunamadı.")

    pk = info.get("private_key")
    if pk:
        pk = pk.replace("\r\n", "\n").replace("\\\\n", "\n").replace("\\n", "\n")
        info["private_key"] = pk

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

def _ensure_sheet_and_update(
    counts: Dict[str, Dict[str, int]],
    sheet_id: str,
    name: str,
    template_name: str = "ŞABLON",
    extra_stats: Optional[Dict[str, Optional[float]]] = None,
) -> Tuple[str, int]:
    """
    - Sayfa varsa günceller; yoksa template kopyalar (yoksa boş sayfa ekler)
    - C sütununa Bekleyen/Çözülen değerlerini TEK batch ile yazar
    - extra_stats ile: Yanıtlama / Yanıtlamama / Memnuniyet yüzdelerini de yazar
    - Dönüş: (worksheet_url, worksheet_gid)
    """
    import gspread
    gc = _sheet_client()
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        try:
            template = sh.worksheet(template_name)
            sh.duplicate_sheet(source_sheet_id=template.id, new_sheet_name=name)
            ws = sh.worksheet(name)
        except Exception:
            ws = sh.add_worksheet(title=name, rows=200, cols=20)

    updates = []
    # Kategori bazlı Bekleyen/Çözülen
    for kategori, (row_pending, row_solved) in CATEGORY_CELL_MAP.items():
        v = counts.get(kategori, {"Bekleyen": 0, "Çözülen": 0})
        updates.append({"range": f"C{row_pending}", "values": [[int(v.get("Bekleyen", 0))]]})
        updates.append({"range": f"C{row_solved}",  "values": [[int(v.get("Çözülen", 0))]]})

    # Genel istatistikler (yüzdeler)
    if extra_stats:
        r = extra_stats.get("reply_rate")
        nr = extra_stats.get("non_reply_rate")
        sat = extra_stats.get("satisfaction_rate")

        if r is not None and STATS_CELL_MAP.get("reply_rate"):
            updates.append({
                "range": STATS_CELL_MAP["reply_rate"],
                "values": [[round(r, 1)]],
            })
        if nr is not None and STATS_CELL_MAP.get("non_reply_rate"):
            updates.append({
                "range": STATS_CELL_MAP["non_reply_rate"],
                "values": [[round(nr, 1)]],
            })
        if sat is not None and STATS_CELL_MAP.get("satisfaction_rate"):
            updates.append({
                "range": STATS_CELL_MAP["satisfaction_rate"],
                "values": [[round(sat, 1)]],
            })

    if updates:
        ws.batch_update(updates, value_input_option="RAW")

    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={ws.id}", ws.id

def _hide_other_tabs_by_pattern(sheet_id: str, keep_gid: int, pattern: re.Pattern):
    gc = _sheet_client()
    sh = gc.open_by_key(sheet_id)
    reqs = []
    for ws in sh.worksheets():
        if ws.id == keep_gid:
            reqs.append({"updateSheetProperties":{"properties":{"sheetId":ws.id,"hidden":False},"fields":"hidden"}})
            continue
        if pattern.match(ws.title or ""):
            reqs.append({"updateSheetProperties":{"properties":{"sheetId":ws.id,"hidden":True},"fields":"hidden"}})
    if reqs:
        sh.batch_update({"requests": reqs})

# ---------- İsim üreticiler ----------
def _daily_sheet_name_tr(day_utc_ts: int, tz_offset_hours: int = 3) -> str:
    tr_dt = datetime.utcfromtimestamp(day_utc_ts) + timedelta(hours=tz_offset_hours)
    aylar = ["OCAK","ŞUBAT","MART","NİSAN","MAYIS","HAZİRAN","TEMMUZ","AĞUSTOS","EYLÜL","EKİM","KASIM","ARALIK"]
    return f"{tr_dt.day:02d} {aylar[tr_dt.month-1]} {tr_dt.year}"

def _weekly_sheet_name_tr(start_ts: int, end_ts: int, tz_offset_hours: int = 3) -> str:
    """
    - Aynı AY & YIL      -> "GG - GG AAAA YYYY"
    - AY farklı, YIL aynı-> "GG AAAA - GG AAAA YYYY"
    - YIL farklı         -> "GG AAAA YYYY - GG AAAA YYYY"
    """
    def as_tr(ts: int):
        d = datetime.utcfromtimestamp(ts) + timedelta(hours=tz_offset_hours)
        aylar = ["OCAK","ŞUBAT","MART","NİSAN","MAYIS","HAZİRAN","TEMMUZ","AĞUSTOS","EYLÜL","EKİM","KASIM","ARALIK"]
        return d, aylar[d.month-1]

    s, sm = as_tr(start_ts)
    e, em = as_tr(end_ts)

    if s.year == e.year:
        if s.month == e.month:
            return f"{s.day:02d} - {e.day:02d} {em} {e.year}"
        else:
            return f"{s.day:02d} {sm} - {e.day:02d} {em} {e.year}"
    else:
        return f"{s.day:02d} {sm} {s.year} - {e.day:02d} {em} {e.year}"

def _monthly_sheet_name_tr(any_ts: int, tz_offset_hours: int = 3) -> str:
    d = datetime.utcfromtimestamp(any_ts) + timedelta(hours=tz_offset_hours)
    aylar = ["OCAK","ŞUBAT","MART","NİSAN","MAYIS","HAZİRAN","TEMMUZ","AĞUSTOS","EYLÜL","EKİM","KASIM","ARALIK"]
    return f"{aylar[d.month-1]} {d.year}"

# ---------- İstatistik yardımcıları ----------

def _compute_stats_from_counts(counts: Dict[str, Dict[str, int]]) -> Dict[str, Optional[float]]:
    """
    counts içindeki Bekleyen/Çözülen toplamlarından:
    - Yanıtlama %
    - Yanıtlamama %
    hesaplar.
    """
    total = 0
    answered = 0
    for v in counts.values():
        bek = int(v.get("Bekleyen", 0) or 0)
        coz = int(v.get("Çözülen", 0) or 0)
        total += bek + coz
        answered += coz

    if total == 0:
        return {
            "reply_rate": None,
            "non_reply_rate": None,
        }

    reply = answered * 100.0 / total
    non_reply = 100.0 - reply
    return {
        "reply_rate": reply,
        "non_reply_rate": non_reply,
    }

def _compute_csat_from_tickets(tickets) -> Optional[float]:
    """
    Zendesk ticket'larındaki satisfaction_rating.score alanından
    memnuniyet yüzdesi hesaplar.

    good / (good + bad) * 100
    """
    if not tickets:
        return None

    good = 0
    bad = 0

    for t in tickets:
        rating = (t.get("satisfaction_rating") or {})
        score = rating.get("score")
        if score == "good":
            good += 1
        elif score == "bad":
            bad += 1

    total = good + bad
    if total == 0:
        return None

    return good * 100.0 / total

# ---------- main ----------
def main():
    fb = _env_from_app_secrets()
    subdomain   = (os.getenv("ZENDESK_SUBDOMAIN")   or fb.get("ZENDESK_SUBDOMAIN","")).strip()
    email_token = (os.getenv("ZENDESK_EMAIL_TOKEN") or fb.get("ZENDESK_EMAIL_TOKEN","")).strip()
    api_token   = (os.getenv("ZENDESK_API_TOKEN")   or fb.get("ZENDESK_API_TOKEN","")).strip()
    slack_url   = (os.getenv("SLACK_WEBHOOK_URL")   or fb.get("SLACK_WEBHOOK_URL","")).strip()

    report_type = (os.getenv("REPORT_TYPE","DAILY") or "DAILY").upper()
    tz_offset   = int(os.getenv("REPORT_TZ_OFFSET_HOURS","3"))
    brand_id    = _brand_id()

    if not (subdomain and email_token and api_token):
        raise SystemExit("Wolfteam Zendesk env eksik (subdomain/email_token/api_token).")

    headers = auth_headers(email_token, api_token)
    start_ts, end_ts = range_by_report_type(report_type, tz_offset)

    tickets = None  # DAILY/WEEKLY için dolduracağız; MONTHLY streaming'de boş kalabilir

    # -------- Veri toplama / sayım --------
    if report_type == "MONTHLY":
        # 220k+ için streaming sayım (RAM dostu, hızlı)
        counts = incremental_count_parallel(
            subdomain=subdomain, headers=headers,
            start_ts=start_ts, end_ts=end_ts,
            brand_id=brand_id, form_map=FORM_MAP,
            chunk_days=1, workers=16, debug=True
        )
        # NOT: incremental_count_parallel ticket detaylarını dönmüyorsa
        # bu ayki memnuniyet oranı hesaplanamaz; o yüzden csat None kalacak.
    else:
        tickets = search_fetch_window(
            subdomain, headers, start_ts, end_ts,
            brand_id=brand_id, mode="both", debug=True
        )
        if not tickets:
            tickets = search_fetch_window(
                subdomain, headers, start_ts, end_ts,
                brand_id=brand_id, mode="created", debug=True
            )
        if not tickets:
            tickets = incremental_fetch_parallel(
                subdomain=subdomain, headers=headers,
                start_ts=start_ts, end_ts=end_ts,
                brand_id=brand_id, chunk_days=3, workers=8, debug=True
            )
        counts = count_by_category(tickets, FORM_MAP)

    title = TITLE.get(report_type, "📊 Wolfteam Zendesk Raporu")

    # -------- Genel istatistikler (yüzdeler) --------
    stats = _compute_stats_from_counts(counts)
    csat = _compute_csat_from_tickets(tickets) if tickets is not None else None
    stats["satisfaction_rate"] = csat

    # -------- Sheets + gizleme + Slack link --------
    sheet_url: Optional[str] = None
    link_text: Optional[str] = None

    try:
        if report_type == "DAILY":
            name = _daily_sheet_name_tr(start_ts, tz_offset)
            sheet_url, gid = _ensure_sheet_and_update(
                counts, WOLFTEAM_SHEET_ID, name, template_name="ŞABLON",
                extra_stats=stats,
            )
            _hide_other_tabs_by_pattern(WOLFTEAM_SHEET_ID, gid, re.compile(r"^\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}$"))
            link_text = name

        elif report_type == "WEEKLY":
            name = _weekly_sheet_name_tr(start_ts, end_ts, tz_offset)
            sheet_url, gid = _ensure_sheet_and_update(
                counts, WOLFTEAM_SHEET_ID, name, template_name="ŞABLON",
                extra_stats=stats,
            )
            weekly_pat = re.compile(
                r"^("
                r"\d{2}\s-\s\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}"
                r"|"
                r"\d{2}\s+[A-ZÇĞİÖŞÜ]+\s-\s\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}"
                r"|"
                r"\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}\s-\s\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}"
                r")$"
            )
            _hide_other_tabs_by_pattern(WOLFTEAM_SHEET_ID, gid, weekly_pat)
            link_text = name

        elif report_type == "MONTHLY":
            name = _monthly_sheet_name_tr(end_ts, tz_offset)  # geçen ay
            sheet_url, gid = _ensure_sheet_and_update(
                counts, WOLFTEAM_SHEET_ID, name, template_name="ŞABLON",
                extra_stats=stats,
            )
            monthly_pat = re.compile(r"^[A-ZÇĞİÖŞÜ]+\s+\d{4}$")
            _hide_other_tabs_by_pattern(WOLFTEAM_SHEET_ID, gid, monthly_pat)
            link_text = name

    except Exception as e:
        print("Sheets hatası:", e)

    # Slack
    blocks = format_blocks(counts, title)

    # 1) Günlük/Haftalık/Aylık istatistik blokları (yüzdeler)
    prefix = PERIOD_PREFIX.get(report_type, "")
    lines = []

    if stats.get("reply_rate") is not None:
        lines.append(f"*{prefix} Yanıtlama Yüzdesi:* {stats['reply_rate']:.1f}%")
    if stats.get("non_reply_rate") is not None:
        lines.append(f"*{prefix} Yanıtlamama Yüzdesi:* {stats['non_reply_rate']:.1f}%")
    if stats.get("satisfaction_rate") is not None:
        lines.append(f"*{prefix} Memnuniyet Yüzdesi:* {stats['satisfaction_rate']:.1f}%")

    if lines:
        # Ana rapor bloklarından SONRA gelsin
        blocks += [
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(lines),
                },
            },
        ]

    # 2) Sheet linki
    if sheet_url and link_text:
        blocks += [
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"🔗 *Rapor: <{sheet_url}|{link_text}>*"}}
        ]
    
    # En alt not
    blocks += [
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "ℹ️ Açık ticket sayısına, kullanıcıdan dönüş bekleyen ticketlar da dahildir."}
            ]
        }
    ]

    if slack_url:
        r = requests.post(slack_url, json={"blocks": blocks}, timeout=60)
        print("Slack status:", r.status_code, r.text[:120])
    else:
        print("⚠️ SLACK_WEBHOOK_URL boş — sadece stdout.")
        for k, v in counts.items():
            print(k, v)

if __name__ == "__main__":
    main()
