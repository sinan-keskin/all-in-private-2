# zendesk_reports/app.py
import streamlit as st
from datetime import datetime, timedelta, timezone
import pandas as pd

from .utils import auth_headers, incremental_fetch, count_by_category, totals
from .maps_wolfteam import FORM_MAP as WOLF_FORMS
from .maps_zula import FORM_MAP_PC, FORM_MAP_STRIKE


# --- küçük yardımcılar ---
def _tz_today():
    # UTC bazlı bugün (Streamlit deploy’da TZ’ler karışmasın)
    return datetime.now(timezone.utc).date()

def _to_ts(dt: datetime) -> int:
    # naive datetimes'ı UTC olarak say
    return int(dt.replace(tzinfo=timezone.utc).timestamp())

def _in_range_factory(start_ts: int, end_ts: int):
    def _in_range(t):
        try:
            ca = t.get("created_at") or ""
            dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            ts = int(dt.timestamp())
            return start_ts <= ts <= end_ts
        except Exception:
            return False
    return _in_range

def _table_for_counts(title: str, counts: dict):
    rows = [
        {
            "Kategori": k,
            "Çözülen": int(v.get("Çözülen", 0)),
            "Bekleyen": int(v.get("Bekleyen", 0)),
            "Askıda":   int(v.get("Askıda",   0)),
            "Toplam":   int(v.get("Çözülen",  0)) + int(v.get("Bekleyen", 0)) + int(v.get("Askıda", 0)),
        }
        for k, v in counts.items()
    ]
    if not rows:
        rows = [{"Kategori": "—", "Çözülen": 0, "Bekleyen": 0, "Askıda": 0, "Toplam": 0}]
    df = pd.DataFrame(rows).sort_values("Toplam", ascending=False, kind="stable")
    st.subheader(title)
    st.dataframe(df, use_container_width=True)
    s, p, h, tot = totals(counts)
    c = st.columns(4)
    c[0].metric("Toplam",   int(tot))
    c[1].metric("Çözülen",  int(s))
    c[2].metric("Bekleyen", int(p))
    c[3].metric("Askıda",   int(h))


# ---- veri çekme yardımcıları (cache'li) ----
@st.cache_data(show_spinner=False)
def _fetch_tickets_cached(sub: str, email_tok: str, api_tok: str,
                          start_ts: int, end_ts: int, brand_id: int | None):
    headers = auth_headers(email_tok, api_tok)
    # incremental_fetch’i her zaman start+end ts ile sınırlıyoruz (daha hızlı ve güvenli)
    return [
        t for t in incremental_fetch(
            subdomain=sub, headers=headers,
            start_ts=start_ts, end_ts=end_ts,
            brand_id=brand_id, debug=False
        )
    ]

def _fetch_tickets(sub: str, email_tok: str, api_tok: str,
                   start_ts: int, end_ts: int, brand_id: int | None):
    try:
        return _fetch_tickets_cached(sub, email_tok, api_tok, start_ts, end_ts, brand_id)
    except Exception as e:
        # cache anahtarı değişirse vs. (ör. secrets güncellenirse) fallback olarak doğrudan çağır
        headers = auth_headers(email_tok, api_tok)
        return [
            t for t in incremental_fetch(
                subdomain=sub, headers=headers,
                start_ts=start_ts, end_ts=end_ts,
                brand_id=brand_id, debug=True
            )
        ]


# ---- ana uygulama ----
def run(embedded: bool = False):
    st.title("📊 Zendesk Rapor — Önizleme (Tarih Aralığı)")

    import os
    def _get_sec(k): return os.environ.get(k, st.secrets.get(k))
    s_wolf = {
        "subdomain": _get_sec("ZENDESK_WOLF_SUBDOMAIN"),
        "email_token": _get_sec("ZENDESK_WOLF_EMAIL_TOKEN"),
        "api_token": _get_sec("ZENDESK_WOLF_API_TOKEN")
    }
    s_zula = {
        "subdomain": _get_sec("ZENDESK_ZULA_SUBDOMAIN"),
        "email_token": _get_sec("ZENDESK_ZULA_EMAIL_TOKEN"),
        "api_token": _get_sec("ZENDESK_ZULA_API_TOKEN"),
        "brand_pc_id": _get_sec("ZENDESK_ZULA_BRAND_PC_ID"),
        "brand_strike_id": _get_sec("ZENDESK_ZULA_BRAND_STRIKE_ID")
    }

    hesap = st.selectbox(
        "Hesap",
        ["Tümü", "Wolfteam", "Zula(PC&STRIKE)", "Zula PC", "Zula Strike"],
        index=0
    )

    today = _tz_today()
    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("Başlangıç", value=today - timedelta(days=7))
    with c2:
        end_d = st.date_input("Bitiş", value=today)

    # günün tamamı: 00:00–23:59:59
    start_dt = datetime.combine(start_d, datetime.min.time())
    end_dt   = datetime.combine(end_d,   datetime.max.time())
    start_ts, end_ts = _to_ts(start_dt), _to_ts(end_dt)
    in_range = _in_range_factory(start_ts, end_ts)

    if not st.button("Verileri Çek"):
        st.info("Tarihleri seçip **Verileri Çek**’e basın.")
        return

    def render_wolf():
        sub, email_tok, api_tok = s_wolf.get("subdomain"), s_wolf.get("email_token"), s_wolf.get("api_token")
        if not (sub and email_tok and api_tok):
            st.error("Wolfteam Zendesk secrets eksik (zendesk.wolfteam)."); return
        # brand filtresi yoksa None
        tickets = _fetch_tickets(sub, email_tok, api_tok, start_ts, end_ts, brand_id=None)
        # (in_range, incremental_fetch zaten sınırlı ama yine de kalsın)
        tickets = [t for t in tickets if in_range(t)]
        counts  = count_by_category(tickets, WOLF_FORMS)
        _table_for_counts("Wolfteam — Kategori Dağılımı", counts)


    def render_zula(pc: bool, strike: bool):
        sub, email_tok, api_tok = s_zula.get("subdomain"), s_zula.get("email_token"), s_zula.get("api_token")
        brand_pc, brand_st = s_zula.get("brand_pc_id"), s_zula.get("brand_strike_id")
        if not (sub and email_tok and api_tok):
            st.error("Zula Zendesk secrets eksik (zendesk.zula)."); return

        # --- Zula PC ---
        if pc:
            if not brand_pc:
                st.warning("Zula PC brand id (zendesk.zula.brand_pc_id) tanımlı değil — filtre uygulanmadan devam.")
                brand_pc_int = None
            else:
                try:
                    brand_pc_int = int(brand_pc)
                except:
                    st.warning(f"Zula PC brand id sayıya çevrilemedi: {brand_pc!r} — filtre uygulanmadan devam.")
                    brand_pc_int = None

            t_pc = _fetch_tickets(sub, email_tok, api_tok, start_ts, end_ts, brand_pc_int)
            t_pc = [t for t in t_pc if in_range(t)]
            counts_pc = count_by_category(t_pc, FORM_MAP_PC)
            _table_for_counts("Zula PC — Kategori Dağılımı", counts_pc)


        # --- Zula Strike ---
        if strike:
            if not brand_st:
                st.warning("Zula Strike brand id (zendesk.zula.brand_strike_id) tanımlı değil — filtre uygulanmadan devam.")
                brand_st_int = None
            else:
                try:
                    brand_st_int = int(brand_st)
                except:
                    st.warning(f"Zula Strike brand id sayıya çevrilemedi: {brand_st!r} — filtre uygulanmadan devam.")
                    brand_st_int = None

            t_st = _fetch_tickets(sub, email_tok, api_tok, start_ts, end_ts, brand_st_int)
            t_st = [t for t in t_st if in_range(t)]
            counts_st = count_by_category(t_st, FORM_MAP_STRIKE)
            _table_for_counts("Zula Strike — Kategori Dağılımı", counts_st)


    # --- seçimlere göre render ---
    if hesap == "Tümü":
        render_wolf(); render_zula(pc=True, strike=True)
    elif hesap == "Wolfteam":
        render_wolf()
    elif hesap == "Zula(PC&STRIKE)":
        render_zula(pc=True, strike=True)
    elif hesap == "Zula PC":
        render_zula(pc=True, strike=False)
    elif hesap == "Zula Strike":
        render_zula(pc=False, strike=True)


if __name__ == "__main__":
    run(False)
