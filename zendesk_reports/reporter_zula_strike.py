# -*- coding: utf-8 -*-
# zendesk_reports/reporter_zula_strike.py

import os, json, requests, re, traceback
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from .utils import (
    auth_headers, range_by_report_type,
    search_fetch_window_safe, incremental_fetch,  # <-- düzeltildi
    count_by_category, format_blocks,
)
from .maps_zula import FORM_MAP_STRIKE as FORM_MAP  # form_id -> kategori adı

TITLE = {
    "DAILY":   "📅 Zula Strike Günlük Zendesk Raporu",
    "WEEKLY":  "📊 Zula Strike Haftalık Zendesk Raporu",
    "MONTHLY": "📈 Zula Strike Aylık Zendesk Raporu",
}

# Rapor tipine göre Türkçe prefix
PERIOD_PREFIX = {
    "DAILY": "Günlük",
    "WEEKLY": "Haftalık",
    "MONTHLY": "Aylık",
}

DEFAULT_BRAND_ID = 20939571650204
ZULA_STRIKE_SHEET_ID = (os.getenv("ZULA_STRIKE_SHEET_ID") or "1n5ViLggsLsWkJ9vi1rtgCQkI4DRWCwhP0i88VXucrpU").strip()

# --- Mağaza sabitleri (GLOBAL vitrin = US/en) ---
PLAY_PACKAGE    = "com.mboyun.zulamobile"
APPSTORE_APP_ID = "6746648821"
STORE_COUNTRY   = "tr"
STORE_LANG      = "tr"

# --- Emoji ayarları ---
# Slack'te :star-0:..:star-5: yoksa yanında Unicode fallback göster:
USE_UNICODE_STARS_FALLBACK = True

# ---------- APP_SECRETS ----------
def _env_from_app_secrets() -> Dict[str, str]:
    raw = os.getenv("APP_SECRETS")
    if not raw:
        return {}
    try:
        j = json.loads(raw)
        zula = ((j.get("zendesk") or {}).get("zula") or {})
        slack = ((j.get("slack") or {}).get("webhooks") or {}).get("zula_strike", "")
        sheets = j.get("GOOGLE_SHEETS_CREDENTIALS") or {}
        out = {
            "ZENDESK_SUBDOMAIN": zula.get("subdomain", ""),  # madbytehelp
            "ZENDESK_EMAIL_TOKEN": zula.get("email_token", ""),
            "ZENDESK_API_TOKEN": zula.get("api_token", ""),
            "SLACK_WEBHOOK_URL": slack,
            "GOOGLE_SHEETS_CREDENTIALS": json.dumps(sheets),
        }
        if zula.get("brand_strike_id"):
            out["ZULA_BRAND_ID"] = str(zula["brand_strike_id"])
        return out
    except Exception:
        return {}

def _brand_id() -> int:
    s = (os.getenv("ZULA_BRAND_ID")
         or _env_from_app_secrets().get("ZULA_BRAND_ID")
         or os.getenv("BRAND_ID")
         or "").strip()
    try:
        return int(s) if s else DEFAULT_BRAND_ID
    except:
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

# ---------- Sheet yaz + (url, gid) döndür ----------
def _ensure_sheet_and_update(
    counts: Dict[str, Dict[str, int]],
    sheet_id: str,
    sheet_name: str,
    template_name: str = "ŞABLON",
    extra_stats: Optional[Dict[str, Optional[float]]] = None,
) -> Tuple[str, int]:
    """
    - Sayfa varsa günceller; yoksa template kopyalar (yoksa boş sayfa ekler)
    - Kategori satırlarına Bekleyen/Çözülen değerlerini yazar
    - B29-B31 etiketli satırlara Yanıtlanan/ Yanıtlanmayan / Memnuniyet yüzdesini yazar
    """
    import gspread
    gc = _sheet_client()
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        try:
            template = sh.worksheet(template_name)
            sh.duplicate_sheet(source_sheet_id=template.id, new_sheet_name=sheet_name)
            ws = sh.worksheet(sheet_name)
        except Exception:
            ws = sh.add_worksheet(title=sheet_name, rows=300, cols=20)

    ALIAS = {
        "hata bildirimi": "Hata Bildirimi",
        "hesap problemleri": "Hesap Problemleri",
        "odeme problemi": "Ödeme Problemi",
        "ödeme problemi": "Ödeme Problemi",
        "sikayet/onerı": "Şikayet/Öneri",
        "şikayet/öneri": "Şikayet/Öneri",
        "hile bildirimi": "Hile Bildirimi",
        "diger": "Diğer",
        "diğer": "Diğer",
        "hesap silme": "Hesap Silme",
    }
    def _norm(s: str) -> str:
        return (s or "").strip().lower()\
            .replace("ı","i").replace("ş","s").replace("ğ","g")\
            .replace("ç","c").replace("ö","o").replace("ü","u")

    total_pending = sum(int(v.get("Bekleyen", 0)) + int(v.get("Askıda", 0)) for v in counts.values())
    total_solved  = sum(int(v.get("Çözülen", 0)) for v in counts.values())

    rows = ws.get_all_values()
    for r, row in enumerate(rows, start=1):
        if len(row) < 2:
            continue
        label = (row[1] or "").strip()
        if not label:
            continue
        nlabel = _norm(label)

        if "bekleyen ticket sayisi" in nlabel:
            ws.update_cell(r, 3, total_pending); continue
        if "cozulen ticket sayisi" in nlabel or "cevaplanan ticket sayisi" in nlabel:
            ws.update_cell(r, 3, total_solved); continue

        parts = label.split()
        if not parts:
            continue
        tail = parts[-1].lower()
        if tail.endswith("bekleyen"):
            durum = "Bekleyen"; kat_etiket = " ".join(parts[:-1]).strip()
        elif tail.endswith("cevaplanan") or tail.endswith("cevaplananlar"):
            durum = "Çözülen"; kat_etiket = " ".join(parts[:-1]).strip()
        else:
            continue

        nk = _norm(kat_etiket); key = None
        for k in counts.keys():
            if _norm(k) == nk:
                key = k
                break
        if not key:
            alias_target = ALIAS.get(nk)
            if alias_target and alias_target in counts:
                key = alias_target

        value = 0
        if key:
            if durum == "Bekleyen":
                value = int(counts.get(key, {}).get("Bekleyen", 0)) + int(counts.get(key, {}).get("Askıda", 0))
            else:
                value = int(counts.get(key, {}).get("Çözülen", 0))
        ws.update_cell(r, 3, value)

    # --- Yüzdelikleri alttaki satırlara yaz ---
    if extra_stats:
        reply = extra_stats.get("reply_rate")
        non_reply = extra_stats.get("non_reply_rate")
        sat = extra_stats.get("satisfaction_rate")

        if reply is not None:
            _write_sheet_value_by_label(ws, "Yanıtlanan Yüzdesi(%)", round(reply, 1))
        if non_reply is not None:
            _write_sheet_value_by_label(ws, "Yanıtlanmayan Yüzdesi(%)", round(non_reply, 1))
        if sat is not None:
            _write_sheet_value_by_label(ws, "Memnuniyet(%)", round(sat, 1))

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={ws.id}"
    return url, ws.id

# ---------- Eski sekmeleri gizleme ----------
def _hide_other_tabs_by_pattern(sheet_id: str, keep_gid: int, pattern: re.Pattern):
    gc = _sheet_client()
    sh = gc.open_by_key(sheet_id)
    reqs = []
    for ws in sh.worksheets():
        if ws.id == keep_gid:
            reqs.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "hidden": False}, "fields": "hidden"}})
            continue
        if pattern.match(ws.title or ""):
            reqs.append({"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "hidden": True}, "fields": "hidden"}})
    if reqs:
        sh.batch_update({"requests": reqs})

def _apply_hide_strategy(report_type: str, sheet_id: str, keep_gid: int):
    daily_pat   = re.compile(r"^\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}$")
    weekly_pat  = re.compile(
        r"^("
        r"\d{2}\s-\s\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}"
        r"|"
        r"\d{2}\s+[A-ZÇĞİÖŞÜ]+\s-\s\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}"
        r"|"
        r"\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}\s-\s\d{2}\s+[A-ZÇĞİÖŞÜ]+\s+\d{4}"
        r")$"
    )
    monthly_pat = re.compile(r"^[A-ZÇĞİÖŞÜ]+\s+\d{4}$")

    rt = (report_type or "DAILY").upper()
    if rt == "DAILY":
        _hide_other_tabs_by_pattern(sheet_id, keep_gid, daily_pat)
    elif rt == "WEEKLY":
        _hide_other_tabs_by_pattern(sheet_id, keep_gid, weekly_pat)
    elif rt == "MONTHLY":
        _hide_other_tabs_by_pattern(sheet_id, keep_gid, monthly_pat)

# ---------- İsim üreticiler ----------
def _daily_name(ts_utc: int, tz: int) -> str:
    tr = datetime.utcfromtimestamp(ts_utc) + timedelta(hours=tz)
    AY = ["OCAK","ŞUBAT","MART","NİSAN","MAYIS","HAZİRAN","TEMMUZ","AĞUSTOS","EYLÜL","EKİM","KASIM","ARALIK"]
    return f"{tr.day:02d} {AY[tr.month-1]} {tr.year}"

def _weekly_name(ts_start_utc: int, ts_end_utc: int, tz: int) -> str:
    def as_tr(ts: int):
        d = datetime.utcfromtimestamp(ts) + timedelta(hours=tz)
        AY = ["OCAK","ŞUBAT","MART","NİSAN","MAYIS","HAZİRAN","TEMMUZ","AĞUSTOS","EYLÜL","EKİM","KASIM","ARALIK"]
        return d, AY[d.month-1]
    s, sm = as_tr(ts_start_utc); e, em = as_tr(ts_end_utc)
    if s.year == e.year:
        return f"{s.day:02d} - {e.day:02d} {em} {e.year}" if s.month == e.month else f"{s.day:02d} {sm} - {e.day:02d} {em} {e.year}"
    return f"{s.day:02d} {sm} {s.year} - {e.day:02d} {em} {e.year}"

def _monthly_name(ts_any_utc: int, tz: int) -> str:
    tr = datetime.utcfromtimestamp(ts_any_utc) + timedelta(hours=tz)
    AY = ["OCAK","ŞUBAT","MART","NİSAN","MAYIS","HAZİRAN","TEMMUZ","AĞUSTOS","EYLÜL","EKİM","KASIM","ARALIK"]
    return f"{AY[tr.month-1]} {tr.year}"

def _sheet_name(report_type: str, start_ts: int, end_ts: int, tz: int) -> str:
    rt = (report_type or "DAILY").upper()
    if rt == "DAILY":   return _daily_name(start_ts, tz)
    if rt == "WEEKLY":  return _weekly_name(start_ts, end_ts, tz)
    if rt == "MONTHLY": return _monthly_name(end_ts, tz)
    return _daily_name(start_ts, tz)

# ---------- MAĞAZA PUANI: Çekme (US/en) ----------
def _fetch_play_rating(package_name: str) -> Tuple[Optional[float], Optional[int]]:
    """
    Google Play puanı ve oy sayısı (yalnız TR).
    Öncelik sırası: aria-label -> JSON-LD -> google_play_scraper.
    Bazı durumlarda JSON-LD 5 döndürebildiği için aria-label'ı tercih ediyoruz.
    """
    lang = "tr"
    country = "TR"  # URL'de büyük harf daha stabil

    # --- 1) HTML (aria-label) ---
    try:
        url = f"https://play.google.com/store/apps/details?id={package_name}&hl={lang}&gl={country}"
        html = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).text

        # ör: aria-label="4,1 yıldız üzerinden 662 oy"
        m = re.search(r'aria-label="[^"]*?([0-9]+[,\.][0-9])\s*yıldız', html)
        if m:
            val = float(m.group(1).replace(",", "."))
            # oy sayısını da yakalamaya çalış (opsiyonel)
            m2 = re.search(r'([0-9][0-9\.\s]*)\s*(oy|değerlendirme)', html)
            cnt = None
            if m2:
                try:
                    cnt = int(re.sub(r"[^\d]", "", m2.group(1)))
                except Exception:
                    cnt = None
            return val, cnt
    except Exception as e:
        print("[play] aria-label parse error:", repr(e))

    # --- 2) HTML (JSON-LD aggregateRating) ---
    try:
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue
            agg = data.get("aggregateRating") if isinstance(data, dict) else None
            if agg:
                val = agg.get("ratingValue")
                cnt = agg.get("ratingCount") or agg.get("reviewCount")
                # bazen val=5 geliyor; yine de döndürmeden önce clamp et
                if val is not None:
                    fval = max(0.0, min(5.0, float(str(val).replace(",", "."))))
                    icnt = int(cnt) if str(cnt).isdigit() else None
                    return fval, icnt
    except Exception as e:
        print("[play] json-ld parse error:", repr(e))

    # --- 3) Kütüphane (son çare) ---
    try:
        from google_play_scraper import app as gp_app
        info = gp_app(package_name, lang="tr", country="tr")
        score = info.get("score")
        ratings = info.get("ratings")
        if score is not None:
            return float(score), int(ratings or 0)
    except Exception as e:
        print("[play] library fetch failed:", repr(e))

    return None, None


def _fetch_ios_rating(app_id: str, country: str = STORE_COUNTRY) -> Tuple[Optional[float], Optional[int]]:
    """App Store ortalama puan ve oy sayısı (iTunes Lookup, US storefront)."""
    try:
        r = requests.get("https://itunes.apple.com/lookup", params={"id": app_id, "country": country}, timeout=30)
        j = r.json()
        results = (j.get("results") or [])
        if not results:
            return None, None
        it = results[0]
        score = float(it.get("averageUserRating")) if it.get("averageUserRating") is not None else None
        ratings = int(it.get("userRatingCount")) if it.get("userRatingCount") is not None else None
        return score, ratings
    except Exception as e:
        print("[ios] fetch error:", repr(e)); traceback.print_exc()
        return None, None

# ---------- SHEET yardımcı ----------
def _read_sheet_value_by_label(ws, target_label: str) -> Optional[float]:
    rows = ws.get_all_values()
    for r, row in enumerate(rows, start=1):
        if len(row) < 3: continue
        label = (row[1] or "").strip().lower()
        if label == target_label.strip().lower():
            val = (row[2] or "").replace(",", ".")
            try: return float(val)
            except Exception: return None
    return None

def _write_sheet_value_by_label(ws, target_label: str, value) -> None:
    rows = ws.get_all_values()
    for r, row in enumerate(rows, start=1):
        if len(row) < 2: continue
        label = (row[1] or "").strip().lower()
        if label == target_label.strip().lower():
            ws.update_cell(r, 3, value if value is not None else "")
            return

# ---------- Yüzde istatistikleri ----------
def _compute_stats_from_counts(counts: Dict[str, Dict[str, int]]) -> Dict[str, Optional[float]]:
    """
    counts içindeki Bekleyen/Askıda/Çözülen toplamlarından:
    - Yanıtlanan %
    - Yanıtlanmayan %
    hesaplar.
    """
    total = 0
    answered = 0
    for v in counts.values():
        bek = int(v.get("Bekleyen", 0) or 0) + int(v.get("Askıda", 0) or 0)
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

# ---------- önceki dönem ----------
def _prev_period_name(report_type: str, start_ts: int, end_ts: int, tz: int) -> Optional[str]:
    rt = (report_type or "DAILY").upper()
    if rt == "DAILY":
        return _daily_name(start_ts - 24*3600, tz)
    if rt == "WEEKLY":
        return _weekly_name(start_ts - 7*24*3600, end_ts - 7*24*3600, tz)
    if rt == "MONTHLY":
        d = datetime.utcfromtimestamp(end_ts) + timedelta(hours=tz)
        first_this_month = datetime(d.year, d.month, 1)
        prev_month_last_day = first_this_month - timedelta(days=1)
        prev_any_ts = int((prev_month_last_day - timedelta(hours=tz)).timestamp())
        return _monthly_name(prev_any_ts, tz)
    return None

def _ensure_ratings_and_deltas_by_period(
    sheet_id: str, sheet_name: str, report_type: str,
    android_score: Optional[float], android_count: Optional[int],
    ios_score: Optional[float], ios_count: Optional[int],
    start_ts: int, end_ts: int, tz: int,
):
    import gspread
    gc = _sheet_client()
    sh = gc.open_by_key(sheet_id)
    ws = sh.worksheet(sheet_name)

    _write_sheet_value_by_label(ws, "Google Play Puanı", android_score)
    _write_sheet_value_by_label(ws, "AppStore Puanı", ios_score)
    _write_sheet_value_by_label(ws, "Android Oy Sayısı", android_count)
    _write_sheet_value_by_label(ws, "iOS Oy Sayısı", ios_count)

    prev_name = _prev_period_name(report_type, start_ts, end_ts, tz)
    d_android = d_ios = None
    if prev_name:
        try:
            y_ws = sh.worksheet(prev_name)
            y_and = _read_sheet_value_by_label(y_ws, "Google Play Puanı")
            y_ios = _read_sheet_value_by_label(y_ws, "AppStore Puanı")
            if (android_score is not None) and (y_and is not None):
                d_android = round(android_score - y_and, 3)
            if (ios_score is not None) and (y_ios is not None):
                d_ios = round(ios_score - y_ios, 3)
        except Exception:
            pass

    _write_sheet_value_by_label(ws, "Google Play Puanı Farkı", d_android)
    _write_sheet_value_by_label(ws, "AppStore Puanı Farkı", d_ios)
    return d_android, d_ios

# ---------- Slack satırı / yıldız ----------
# --- YENİ: yıldızları ilk rakama göre tekrar et ---
def _stars_for_score_first_digit(score: Optional[float]) -> str:
    """
    4.97 -> ':star: :star: :star: :star:'
    0.xx -> '' (yıldız yok)
    """
    if score is None:
        return ""
    try:
        n = int(str(abs(float(score))).split(".", 1)[0])
    except Exception:
        n = 0
    n = max(0, min(5, n))
    return " ".join([":star:"] * n) if n > 0 else ""

def _format_star_line(score: Optional[float], delta: Optional[float], platform: str) -> str:
    icon = ":android:" if platform == "android" else ":ios:"
    stars = _stars_for_score_first_digit(score)
    if score is None:
        # puan yoksa sadece platform ikonu
        return f"{icon} -"
    s = f"{score:.2f}"
    base = f"{icon} {s}" + (f" {stars}" if stars else "")
    if delta is None:
        return base
    sign = "+" if (delta or 0) >= 0 else ""
    return f"{base} (Fark {sign}{delta:.2f})"


# ---------- main ----------
def main():
    fb = _env_from_app_secrets()
    subdomain   = (os.getenv("ZENDESK_SUBDOMAIN")   or fb.get("ZENDESK_SUBDOMAIN","")).strip()
    email_token = (os.getenv("ZENDESK_EMAIL_TOKEN") or fb.get("ZENDESK_EMAIL_TOKEN","")).strip()
    api_token   = (os.getenv("ZENDESK_API_TOKEN")   or fb.get("ZENDESK_API_TOKEN","")).strip()
    slack_url   = (os.getenv("SLACK_WEBHOOK_URL")   or fb.get("SLACK_WEBHOOK_URL","")).strip()
    sheet_id    = (os.getenv("ZULA_STRIKE_SHEET_ID") or ZULA_STRIKE_SHEET_ID).strip()

    report_type = (os.getenv("REPORT_TYPE","DAILY") or "DAILY").upper()
    tz_offset   = int(os.getenv("REPORT_TZ_OFFSET_HOURS","3"))
    brand_id    = _brand_id()

    if not (subdomain and email_token and api_token):
        raise SystemExit("Zula Strike Zendesk env eksik (subdomain/email_token/api_token).")

    headers = auth_headers(email_token, api_token)
    start_ts, end_ts = range_by_report_type(report_type, tz_offset)

    # ---- Mağaza puanları (Android + iOS) ----
    android_score, android_count = _fetch_play_rating(PLAY_PACKAGE)
    ios_score, ios_count         = _fetch_ios_rating(APPSTORE_APP_ID, country=STORE_COUNTRY)

    # ---- Zendesk verisi ----
    tickets = search_fetch_window_safe(     # <-- düzeltildi
        subdomain, headers, start_ts, end_ts,
        brand_id=brand_id, mode="both", debug=True
    )
    if not tickets:
        print("[fallback] search mode='created'")
        tickets = search_fetch_window_safe(  # <-- düzeltildi
            subdomain, headers, start_ts, end_ts,
            brand_id=brand_id, mode="created", debug=True
        )
    if not tickets:
        print("[fallback] incremental export")
        tickets = incremental_fetch(
            subdomain=subdomain, headers=headers,
            start_ts=start_ts, end_ts=end_ts,
            brand_id=brand_id, debug=True
        )
    counts = count_by_category(tickets, FORM_MAP)

    # ---- Genel istatistikler (yüzdeler) ----
    stats = _compute_stats_from_counts(counts)
    csat = _compute_csat_from_tickets(tickets)
    stats["satisfaction_rate"] = csat

    # ---- Sheets (yaz + gizleme + puan farkları) ----
    sheet_url: Optional[str] = None
    link_text: Optional[str] = None
    try:
        name = _sheet_name(report_type, start_ts, end_ts, tz_offset)
        sheet_url, gid = _ensure_sheet_and_update(counts, sheet_id, name, extra_stats=stats)
        d_android, d_ios = _ensure_ratings_and_deltas_by_period(
            sheet_id=sheet_id, sheet_name=name, report_type=report_type,
            android_score=android_score, android_count=android_count,
            ios_score=ios_score, ios_count=ios_count,
            start_ts=start_ts, end_ts=end_ts, tz=tz_offset
        )
        _apply_hide_strategy(report_type, sheet_id, gid)
        link_text = name
        print("Sheets güncellendi:", sheet_url)
    except Exception as e:
        print("Sheets hatası:", e)
        d_android = d_ios = None

    # ---- Slack ----
    title = TITLE.get(report_type, "📊 Zula Strike Zendesk Raporu")
    blocks = format_blocks(counts, title)  # başlık + ana rapor blokları

    # Store puanları satırları
    and_line = _format_star_line(android_score, d_android, "android")
    ios_line = _format_star_line(ios_score, d_ios, "ios")

    # 1) Store yıldızları
    blocks += [
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":star: *Güncel Store Puanları*"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{and_line}\n{ios_line}"},
        },
    ]

    # 2) Yüzdeler (yanıtlanan / yanıtlanmayan / memnuniyet)
    prefix = PERIOD_PREFIX.get(report_type, "")
    stat_lines = []
    if stats.get("reply_rate") is not None:
        stat_lines.append(f"*{prefix} Yanıtlanan Yüzdesi:* {stats['reply_rate']:.1f}%")
    if stats.get("non_reply_rate") is not None:
        stat_lines.append(f"*{prefix} Yanıtlanmayan Yüzdesi:* {stats['non_reply_rate']:.1f}%")
    if stats.get("satisfaction_rate") is not None:
        stat_lines.append(f"*{prefix} Memnuniyet Yüzdesi:* {stats['satisfaction_rate']:.1f}%")

    if stat_lines:
        blocks += [
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(stat_lines)},
            },
        ]

    # 3) Sheet linki
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
        print(and_line); print(ios_line)
        for k, v in counts.items():
            print(k, v)

if __name__ == "__main__":
    main()
