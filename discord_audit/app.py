# all-in-private/discord_audit/app.py
import os, json, requests, pandas as pd
from datetime import datetime, timezone
from functools import lru_cache
import calendar

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ============ Secrets (APP_SECRETS ya da TOML tablo) ============
def _load_secrets_from_env_if_needed():
    try:
        if ("APP_SECRETS" in os.environ) and (len(getattr(st, "secrets", {})) == 0):
            st.secrets = json.loads(os.environ["APP_SECRETS"])
    except Exception as e:
        # UI içinde göstereceğiz; burada raise etmeyelim
        print("APP_SECRETS parse error:", e)
_load_secrets_from_env_if_needed()

# ============ Page config (tek sefer) ============
try:
    if not st.session_state.get("_pc_done", False):
        st.set_page_config(page_title="Discord Audit Stats", layout="wide")
        st.session_state["_pc_done"] = True
except Exception:
    pass

# ============ Sabitler / Secrets ============
API_BASE = "https://discord.com/api/v10"
DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", st.secrets.get("DISCORD_BOT_TOKEN", ""))

# Discord action codes
ACTION_MEMBER_KICK = 20
ACTION_MEMBER_BAN_ADD = 22
ACTION_MEMBER_UPDATE = 24
ACTION_MESSAGE_DELETE = 72
ACTION_MESSAGE_BULK_DELETE = 73

# TR aylar
AYLAR_TR = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran",
            "Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"]

# users.json (opsiyonel)
PKG_DIR = os.path.dirname(__file__)
USERS_FILE = os.path.join(PKG_DIR, "users.json")
user_overrides = {}
if os.path.exists(USERS_FILE):
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        user_overrides = {str(u["id"]): u for u in data if "id" in u}
    except Exception:
        pass

# ============ Google Sheets client (standart) ============
SPREADSHEET_ID = "1mz9nAMfaYLIc8TbSUs3sIWtstfhJn_fwfkhrju6pq6M"

def _gs_client():
    raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", st.secrets.get("GOOGLE_SHEETS_CREDENTIALS"))
    if raw is None:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS bulunamadı.")
    if isinstance(raw, str):
        try:
            info = json.loads(raw)
        except Exception as e:
            raise RuntimeError(f"GOOGLE_SHEETS_CREDENTIALS JSON parse hatası: {e}")
    else:
        info = dict(raw)
    pk = info.get("private_key")
    if pk:
        info["private_key"] = pk.replace("\\n", "\n")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)

# ============ Helpers ============
def auth_headers(token: str):
    return {"Authorization": f"Bot {token}", "User-Agent": "AuditStatsBot (streamlit, 1.0)"}

@st.cache_data(show_spinner=False, ttl=300)
def get_bot_guilds(token: str):
    if not token: return []
    url = f"{API_BASE}/users/@me/guilds"
    try:
        r = requests.get(url, headers=auth_headers(token), params={"limit": 200}, timeout=30)
        if r.status_code != 200: return []
        return [{"id": str(g["id"]), "name": g.get("name","")} for g in (r.json() or [])]
    except Exception:
        return []

def fetch_audit_logs(token: str, guild_id: str, action_type: int, before: str | None, limit: int):
    params = {"limit": limit, "action_type": action_type}
    if before: params["before"] = before
    url = f"{API_BASE}/guilds/{guild_id}/audit-logs"
    r = requests.get(url, headers=auth_headers(token), params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Discord API hata: {r.status_code} — {r.text[:200]}")
    return r.json()

def _ts_iso_to_ms(value) -> int:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0

def enrich_timestamps(entries):
    DISCORD_EPOCH = 1420070400000
    for e in entries:
        try:
            snow = int(e["id"])
            e["created_ts"] = (snow >> 22) + DISCORD_EPOCH
        except Exception:
            e["created_ts"] = 0
    return entries

def is_timeout_entry(entry: dict) -> bool:
    for c in (entry.get("changes") or []):
        if c.get("key") == "communication_disabled_until":
            new = c.get("new"); old = c.get("old")
            if new and (not old or _ts_iso_to_ms(new) > (_ts_iso_to_ms(old) if old else 0)):
                return True
    return False

def deletion_count(entry: dict) -> int:
    a = entry.get("action_type")
    if a == ACTION_MESSAGE_DELETE: return 1
    if a == ACTION_MESSAGE_BULK_DELETE:
        try: return int((entry.get("options") or {}).get("count", 0) or 0)
        except Exception: return 0
    return 0

def paginate_fetch(token: str, guild_id: str, action_type: int, start_ms: int, end_ms: int, page_limit: int, hard_cap: int):
    out, before, fetched = [], None, 0
    while True:
        data = fetch_audit_logs(token, guild_id, action_type, before, page_limit)
        entries = data.get("audit_log_entries") or []
        if not entries: break
        enrich_timestamps(entries)
        out.extend(entries)
        fetched += len(entries)
        before = entries[-1]["id"]
        oldest_ts = entries[-1].get("created_ts", 0)
        if oldest_ts and oldest_ts < start_ms: break
        if fetched >= hard_cap: break
    return [e for e in out if start_ms <= e.get("created_ts", 0) <= end_ms]

@lru_cache(maxsize=16384)
def get_member_info_cached(token: str, guild_id: str, user_id: str) -> dict:
    try:
        url = f"{API_BASE}/guilds/{guild_id}/members/{user_id}"
        r = requests.get(url, headers=auth_headers(token), timeout=20)
        if r.status_code != 200:
            return {"isim": str(user_id), "kullanici_adi": str(user_id)}
        m = r.json() or {}
        user = m.get("user") or {}
        username = user.get("username") or str(user_id)
        global_name = user.get("global_name")
        nick = m.get("nick")
        display = nick or global_name or username
        return {"isim": display, "kullanici_adi": username}
    except Exception:
        return {"isim": str(user_id), "kullanici_adi": str(user_id)}

def aggregate(entries, token: str, guild_id: str, kind_label: str):
    agg = {}
    for e in entries:
        uid = e.get("user_id")
        if not uid: continue
        target = e.get("target_id")

        override = user_overrides.get(str(uid))
        if override:
            tam_ad = override.get("isim") or str(uid)
            info = get_member_info_cached(DISCORD_TOKEN, guild_id, str(uid))
            kullanici_adi = info["kullanici_adi"]
        else:
            info = get_member_info_cached(DISCORD_TOKEN, guild_id, str(uid))
            tam_ad = info["isim"]
            kullanici_adi = info["kullanici_adi"]

        rec = agg.setdefault(
            uid,
            {"guild_id": guild_id, "adi_soyadi": tam_ad, "kullanici_adi": kullanici_adi,
             "ban": 0, "kick": 0, "timeout": 0, "silinen": 0,
             "targets": {"ban": set(), "kick": set(), "timeout": set(), "silme": set()}}
        )
        if kind_label == "silme": rec["silinen"] += deletion_count(e)
        else: rec[kind_label] += 1
        if target:
            key = "silme" if kind_label == "silme" else kind_label
            rec["targets"][key].add(str(target))
    return agg

# ---- Guild üye sayısı (G3 için) ----
def get_guild_member_count(guild_id: str) -> int | None:
    try:
        r = requests.get(
            f"{API_BASE}/guilds/{guild_id}",
            headers=auth_headers(DISCORD_TOKEN),
            params={"with_counts": "true"},
            timeout=20
        )
        if r.status_code != 200:
            return None
        data = r.json() or {}
        return int(data.get("approximate_member_count") or data.get("member_count") or 0)
    except Exception:
        return None

# ---- Google Sheets yazıcı ----
def _ensure_sheet_and_update(
    df: pd.DataFrame,
    ay_tr: str,
    yil: int,
    current_member_count: int | None,
    previous_member_count: int | None,
) -> str:
    gc = _gs_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    target_title = f"{ay_tr} - {yil}"
    try:
        ws = sh.worksheet(target_title)
    except gspread.WorksheetNotFound:
        try:
            template = sh.worksheet("ŞABLON")
            ws = sh.duplicate_sheet(source_sheet_id=template.id, new_sheet_name=target_title)
            ws = sh.worksheet(target_title)
        except Exception:
            ws = sh.add_worksheet(title=target_title, rows=200, cols=20)

    wanted = ["Adı Soyadı", "Engelleme", "Atma", "Uzaklaştırma", "Mesaj Silme", "Toplam Puan"]
    tbl = df[wanted].copy()
    for col in wanted[1:]:
        tbl[col] = pd.to_numeric(tbl[col], errors="coerce").fillna(0).astype(int)
    tbl["Adı Soyadı"] = tbl["Adı Soyadı"].fillna("").astype(str)
    values = tbl.values.tolist()

    max_rows = 5  # A2:F6
    clear_range = f"A2:F{max_rows+1}"
    ws.batch_clear([clear_range])

    if values:
        subset = values[:max_rows]
        ws.update("A2", subset, value_input_option="RAW")

    ws.update("G3", [[int(current_member_count or 0)]], value_input_option="RAW")
    ws.update("G5", [[int(previous_member_count or 0)]], value_input_option="RAW")

    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={ws.id}"

# ================================
# ============ UI ================
# ================================
def render_ui():
    # --- Stil (select yazı yazılamasın & anchor gizle) ---
    st.markdown("""
    <style>
    div[data-baseweb="select"] input{
      color: transparent !important; caret-color: transparent !important;
      text-shadow: 0 0 0 transparent !important; pointer-events: none !important;
      height: 0 !important; min-height: 0 !important; padding: 0 !important;
      margin: 0 !important; border: 0 !important;
    }
    div[data-baseweb="select"] input::placeholder{color: transparent !important;}
    a.anchor-link { display:none !important; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🔎 Discord Audit")

    if not DISCORD_TOKEN:
        st.error("DISCORD_BOT_TOKEN bulunamadı (secrets).")
        st.stop()

    guilds = get_bot_guilds(DISCORD_TOKEN)
    if not guilds:
        st.error("Botun bulunduğu sunucular alınamadı.")
        st.stop()

    # Sunucular — öncelik + görünen ad
    PRIORITY = [("Zula", "Zula Türkiye"), ("PlayZula", "Zula Avrupa"), ("Zula Akademi", "Zula Akademi")]
    display_to_id, ordered_display = {}, []
    for orig, shown in PRIORITY:
        g = next((x for x in guilds if x["name"] == orig), None)
        if g:
            display_to_id[shown] = g["id"]
            ordered_display.append(shown)

    # -------- Seçimler --------
    c1, c2 = st.columns(2)
    with c1:
        sunucu_secim = st.selectbox(
            "Sunucu", ["Tümü"] + ordered_display, index=0, key="audit_sunucu_select"
        )
    with c2:
        current_month_index = datetime.now(timezone.utc).month - 1
        ay_secim = st.selectbox(
            "Ay", AYLAR_TR, index=current_month_index, key="audit_ay_select"
        )

    secili_guild_ids_now = (
        list(display_to_id.values()) if sunucu_secim == "Tümü" else [display_to_id[sunucu_secim]]
    )
    single_mode = (len(secili_guild_ids_now) == 1)

    getir = st.button("📥 Getir", use_container_width=True, key="audit_getir_btn")

    # State
    for k, v in [("audit_df", None), ("audit_guild_ids", None), ("audit_month", None),
                 ("audit_year", None), ("last_sheet_url", None)]:
        if k not in st.session_state: st.session_state[k] = v

    # Tarih aralığı
    yil = datetime.now(timezone.utc).year
    ay_index = AYLAR_TR.index(ay_secim) + 1
    son_gun = calendar.monthrange(yil, ay_index)[1]
    start_dt = datetime(yil, ay_index, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_dt   = datetime(yil, ay_index, son_gun, 23, 59, 59, tzinfo=timezone.utc)
    start_ms, end_ms = int(start_dt.timestamp()*1000), int(end_dt.timestamp()*1000)

    if getir:
        tum_satirlar = []

        for gid in secili_guild_ids_now:
            bans = paginate_fetch(DISCORD_TOKEN, gid, ACTION_MEMBER_BAN_ADD, start_ms, end_ms, 100, 5000)
            kicks = paginate_fetch(DISCORD_TOKEN, gid, ACTION_MEMBER_KICK, start_ms, end_ms, 100, 5000)
            ups = paginate_fetch(DISCORD_TOKEN, gid, ACTION_MEMBER_UPDATE, start_ms, end_ms, 100, 5000)
            timeouts = [e for e in ups if is_timeout_entry(e)]
            del1 = paginate_fetch(DISCORD_TOKEN, gid, ACTION_MESSAGE_DELETE, start_ms, end_ms, 100, 5000)
            deln = paginate_fetch(DISCORD_TOKEN, gid, ACTION_MESSAGE_BULK_DELETE, start_ms, end_ms, 100, 5000)

            agg = {}
            for kind, entries in (("ban", bans), ("kick", kicks), ("timeout", timeouts)):
                part = aggregate(entries, DISCORD_TOKEN, gid, kind)
                for uid, rec in part.items():
                    if uid not in agg: agg[uid] = rec
                    else:
                        agg[uid]["ban"] += rec["ban"]; agg[uid]["kick"] += rec["kick"]
                        agg[uid]["timeout"] += rec["timeout"]; agg[uid]["silinen"] += rec["silinen"]

            part_del = aggregate(del1 + deln, DISCORD_TOKEN, gid, "silme")
            for uid, rec in part_del.items():
                if uid not in agg: agg[uid] = rec
                else: agg[uid]["silinen"] += rec["silinen"]

            guild_display = next((d for d, _id in display_to_id.items() if _id == gid), gid)
            for uid, r in agg.items():
                tum_satirlar.append({
                    "Sunucu": guild_display,
                    "Adı Soyadı": r["adi_soyadi"],
                    "Kullanıcı Adı": r["kullanici_adi"],
                    "Engelleme": r["ban"],
                    "Atma": r["kick"],
                    "Uzaklaştırma": r["timeout"],
                    "Mesaj Silme": r["silinen"],
                })

        if not tum_satirlar:
            st.info("Seçilen ay için kayıt yok.")
            st.session_state["audit_df"] = None
        else:
            df = pd.DataFrame(tum_satirlar)

            banned_patterns = ["「🤖」", "Refleks", "Zula Destek"]
            mask = df["Adı Soyadı"].astype(str).apply(lambda x: any(p in x for p in banned_patterns))
            df = df[~mask]

            df["Toplam Puan"] = (
                df["Engelleme"]*25 + df["Atma"]*25 + df["Uzaklaştırma"]*25 + df["Mesaj Silme"]*10
            ).astype(int)
            df = df.sort_values(
                ["Toplam Puan","Engelleme","Atma","Uzaklaştırma","Mesaj Silme"], ascending=False
            )

            def fmt(n: int) -> str:
                try: return f"{int(n):,}".replace(",", ".")
                except Exception: return str(n)

            num_cols = ["Engelleme","Atma","Uzaklaştırma","Mesaj Silme","Toplam Puan"]
            df_disp = df.copy()
            for c in num_cols: df_disp[c] = df[c].map(fmt)

            st.dataframe(
                df_disp[["Sunucu","Adı Soyadı","Kullanıcı Adı",
                         "Engelleme","Atma","Uzaklaştırma","Mesaj Silme","Toplam Puan"]],
                use_container_width=True, hide_index=True
            )
            # State’e kaydet (Sheets için)
            st.session_state["audit_df"] = df
            st.session_state["audit_guild_ids"] = secili_guild_ids_now
            st.session_state["audit_month"] = ay_secim
            st.session_state["audit_year"] = yil
            st.session_state["last_sheet_url"] = None

    # ================================
    # Google Sheets: BUTONLAR (yalnızca tekli seçimde)
    # ================================
    if single_mode:
        # 1) Tam genişlik "Tabloya Gönder"
        send_to_sheet = st.button("📄 Tabloya Gönder", use_container_width=True)
    
        if send_to_sheet:
            if st.session_state.get("audit_df") is not None:
                try:
                    df_state = st.session_state["audit_df"]
                    gid_list = st.session_state.get("audit_guild_ids") or []
                    ay_tr = st.session_state.get("audit_month")
                    yil_state = st.session_state.get("audit_year")
    
                    cur_count = get_guild_member_count(gid_list[0]) if len(gid_list) == 1 else 0
    
                    m_idx = AYLAR_TR.index(ay_tr)
                    prev_yil = yil_state if m_idx > 0 else (yil_state - 1)
                    prev_ay_tr = AYLAR_TR[(m_idx - 1) % 12]
    
                    try:
                        sh_tmp = _gs_client().open_by_key(SPREADSHEET_ID)
                        ws_prev = sh_tmp.worksheet(f"{prev_ay_tr} - {prev_yil}")
                        prev_val = ws_prev.acell("G3").value
                        prev_count = int(prev_val) if str(prev_val).strip().isdigit() else 0
                    except Exception:
                        prev_count = 0
    
                    url = _ensure_sheet_and_update(
                        df=df_state, ay_tr=ay_tr, yil=yil_state,
                        current_member_count=cur_count, previous_member_count=prev_count
                    )
                    st.success("Google Sheets güncellendi.")
                    st.session_state["last_sheet_url"] = url
                except Exception as e:
                    st.error(f"Sheets güncelleme hatası: {e}")
            else:
                st.warning("Önce **Getir** ile tabloyu oluşturun.")
    
        # 2) (Varsa) “Sheets’te Aç”ı da tam genişlikte, key parametresi OLMADAN göster
        if st.session_state.get("last_sheet_url"):
            st.link_button("🧾 Google Sheets’te Aç",
                           st.session_state["last_sheet_url"],
                           use_container_width=True)
    else:
        st.caption("ℹ️ Google Sheets’e yazma işlemi yalnızca **tek bir sunucu** seçiliyken kullanılabilir.")

# --- embed uyumlu wrapper ---
def run(embedded: bool = False):
    render_ui()

if __name__ == "__main__":
    run(False)
