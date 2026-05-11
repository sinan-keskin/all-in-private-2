# slack_transfer/app.py
import os
import pytz
import sqlite3
import streamlit as st
from datetime import datetime, date
from dotenv import load_dotenv
import pandas as pd
from .slack_helpers import fetch_messages, transfer_messages

# ---------------- ENV / SECRETS ----------------
load_dotenv()
try:
    # APP_SECRETS varsa içindeki her şeyi ortama (environ) çıkar
    raw_secrets = os.environ.get("APP_SECRETS")
    if raw_secrets:
        import json
        data = json.loads(raw_secrets)
        for k, v in data.items():
            if isinstance(v, str):
                os.environ[k] = v

    # Alternatif olarak st.secrets kullanılmışsa
    src_tok = st.secrets.get("SRC_BOT_TOKEN", None)
    dst_tok = st.secrets.get("DST_BOT_TOKEN", None)
    if src_tok: os.environ["SRC_BOT_TOKEN"] = src_tok
    if dst_tok: os.environ["DST_BOT_TOKEN"] = dst_tok
except Exception:
    pass

SRC_CHANNEL_ID = os.environ.get("SRC_CHANNEL_ID")
DST_CHANNEL_ID = os.environ.get("DST_CHANNEL_ID")

# --- Tek süreçte Slack Bildirim Listener (aynı bot) --- #
import threading
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

def start_notify_once():
    if st.session_state.get("_notify_started"):
        return
    st.session_state["_notify_started"] = True

    BOT_TOKEN = os.environ.get("DST_BOT_TOKEN") or os.environ.get("SRC_BOT_TOKEN")
    APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
    NOTIFY_USER_ID = os.getenv("NOTIFY_USER_ID", "")
    NOTIFY_CHANNEL_ID = os.getenv("NOTIFY_CHANNEL_ID", "")

    if not BOT_TOKEN or not APP_TOKEN or not (NOTIFY_USER_ID or NOTIFY_CHANNEL_ID):
        # We shouldn't spam warnings on import, just silently return or print
        print("Bildirim listener için BOT_TOKEN / SLACK_APP_TOKEN / NOTIFY_* eksik. .env’i kontrol et.")
        return

    SRC_CH = os.getenv("SRC_CHANNEL_ID", "")
    DST_CH = os.getenv("DST_CHANNEL_ID", "")

    web = WebClient(token=BOT_TOKEN)
    sock = SocketModeClient(app_token=APP_TOKEN, web_client=web)

    try:
        BOT_USER_ID = web.auth_test()["user_id"]
    except Exception as e:
        print(f"auth_test hatası: {e}")
        return

    def notify(text, blocks=None):
        try:
            if NOTIFY_USER_ID:
                im = web.conversations_open(users=NOTIFY_USER_ID)
                ch = im["channel"]["id"]
            else:
                ch = NOTIFY_CHANNEL_ID
            web.chat_postMessage(channel=ch, text=text, blocks=blocks or [])
        except Exception as e:
            print("notify error:", e)

    def permalink(channel, ts):
        try:
            return web.chat_getPermalink(channel=channel, message_ts=ts)["permalink"]
        except Exception:
            return None

    def is_bots_message(channel, ts):
        try:
            r = web.conversations_history(channel=channel, latest=ts, oldest=ts, inclusive=True, limit=1)
            m = (r.get("messages") or [None])[0] or {}
            return m.get("user") == BOT_USER_ID or bool(m.get("bot_id"))
        except Exception:
            return False

    def parent_is_bots_message(channel, thread_ts):
        try:
            r = web.conversations_replies(channel=channel, ts=thread_ts, limit=1, inclusive=True)
            m = (r.get("messages") or [None])[0] or {}
            return m.get("user") == BOT_USER_ID or bool(m.get("bot_id"))
        except Exception:
            return False

    def channel_allowed(channel_id: str) -> bool:
        if SRC_CH and channel_id == SRC_CH:
            return True
        if DST_CH and channel_id == DST_CH:
            return True
        return not (SRC_CH or DST_CH)

    def handle_reaction_added(ev):
        item = ev.get("item", {})
        ch, ts = item.get("channel"), item.get("ts")
        if not ch or not ts or not channel_allowed(ch): return
        if not is_bots_message(ch, ts): return
        link = permalink(ch, ts) or ""
        blocks = [{
            "type":"section",
            "text":{"type":"mrkdwn",
                    "text": f"*Reaction:* :{ev.get('reaction')}: • <@{ev.get('user')}>\n<{link}|Mesaja git>"}
        },{
            "type":"context","elements":[{"type":"mrkdwn","text": f"Kanal: <#{ch}>"}]
        }]
        notify(":tada: Mesajına reaction geldi", blocks)

    def handle_app_mention(ev):
        ch = ev.get("channel")
        if not ch or not channel_allowed(ch): return
        link = permalink(ch, ev.get("ts")) or ""
        txt = (ev.get("text") or "")[:500]
        blocks = [{
            "type":"section",
            "text":{"type":"mrkdwn","text": f"*<@{ev.get('user')}> seni etiketledi:*\n{txt}\n<{link}|Mesaja git>"}
        }]
        notify(":bell: Bot etiketlendi", blocks)

    def handle_message(ev):
        ch = ev.get("channel")
        if not ch or not channel_allowed(ch): return
        thread_ts, ts = ev.get("thread_ts"), ev.get("ts")
        if not thread_ts or ts == thread_ts: return
        if ev.get("subtype") in ("message_replied", "thread_broadcast"): return
        if not parent_is_bots_message(ch, thread_ts): return
        txt = (ev.get("text") or "")[:500]
        link = permalink(ch, ts) or ""
        blocks = [{
            "type":"section",
            "text":{"type":"mrkdwn","text": f"*<@{ev.get('user')}> yanıtladı:*\n{txt}\n<{link}|Yanıta git>"}
        },{
            "type":"context","elements":[{"type":"mrkdwn","text": f"Kanal: <#{ch}> • Thread TS: {thread_ts}"}]
        }]
        notify(":left_speech_bubble: Bot mesajına thread yanıtı", blocks)

    @sock.on("events_api")
    def on_events(client: SocketModeClient, req: SocketModeRequest):
        # Slack'e ACK gönder
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
    
        # Sadece events_api paketleriyle ilgilen
        if req.type != "events_api":
            return
    
        ev = (req.payload or {}).get("event", {}) or {}
        et = ev.get("type")
        try:
            if et == "reaction_added":
                handle_reaction_added(ev)
            elif et == "app_mention":
                handle_app_mention(ev)
            elif et == "message":
                handle_message(ev)
        except Exception as e:
            print("notify handler error:", e)
    
    sock.socket_mode_request_listeners.append(on_events)

    def run_forever():
        try:
            sock.connect()
            import time
            while True:
                time.sleep(30)
        except Exception as e:
            print("socket run error:", e)

    threading.Thread(target=run_forever, daemon=True).start()

# Sayfa yüklendiğinde listener'ı başlat (Sadece ilk seferinde çalışır)
try:
    start_notify_once()
except Exception as e:
    print(f"Bildirim listener başlatılamadı: {e}")

# ---------------- STATE DB (SQLite) ----------------
DB_PATH = os.path.join(os.getcwd(), "state.db")

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sent_messages (
        source_channel_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        sent_date TEXT NOT NULL,
        PRIMARY KEY (source_channel_id, ts, sent_date)
    )
    """)
    conn.commit()
    return conn

@st.cache_resource(show_spinner=False)
def get_conn():
    return init_db()

conn = get_conn()

def get_already_sent_ts_for(db_conn, source_channel_id: str, day_str: str) -> set:
    cur = db_conn.cursor()
    cur.execute("SELECT ts FROM sent_messages WHERE source_channel_id=? AND sent_date=?", (source_channel_id, day_str))
    rows = cur.fetchall()
    return set(r[0] for r in rows)

def mark_sent_ts_for(db_conn, source_channel_id: str, ts_list, day_str: str):
    if not ts_list:
        return
    cur = db_conn.cursor()
    data = [(source_channel_id, ts, day_str) for ts in ts_list]
    try:
        cur.executemany("INSERT OR IGNORE INTO sent_messages (source_channel_id, ts, sent_date) VALUES (?,?,?)", data)
        db_conn.commit()
    except Exception:
        db_conn.rollback()
        raise

# ---------------- TIME HELPERS ----------------
TZ = pytz.timezone("Europe/Istanbul")

def day_epoch_range(d: date):
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TZ)
    end   = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ)
    return str(int(start.timestamp())), str(int(end.timestamp()))

def date_str(d: date):
    return d.strftime("%Y-%m-%d")

# ---------------- MAIN UI FUNCTION ----------------
def run(embedded: bool = False):
    if not embedded:
        try:
            st.set_page_config(page_title="Slack Mesaj Taşıma", layout="wide")
        except Exception:
            pass

    # ---------------- GUARD RAILS ----------------
    if not os.environ.get("SRC_BOT_TOKEN") or not os.environ.get("DST_BOT_TOKEN"):
        st.error("ENV’de bot token’ları yok. .env içine SRC_BOT_TOKEN ve DST_BOT_TOKEN ekle.")
        st.stop()
    if not SRC_CHANNEL_ID or not DST_CHANNEL_ID:
        st.error("ENV’de kanal ID’leri yok. .env içine SRC_CHANNEL_ID ve DST_CHANNEL_ID ekle.")
        st.stop()

    # ---------------- SESSION INIT ----------------
    if "selected_date" not in st.session_state:
        st.session_state["selected_date"] = datetime.now(TZ).date()
    if "oldest" not in st.session_state or "latest" not in st.session_state:
        o, l = day_epoch_range(st.session_state["selected_date"])
        st.session_state["oldest"], st.session_state["latest"] = o, l
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "auto_loaded" not in st.session_state:
        st.session_state["auto_loaded"] = False

    # ---------------- THEME / STYLE ----------------
    st.markdown("""
    <style>
    .block-container {padding-top:.6rem; padding-bottom:.6rem; max-width:1220px;}
    .toolbar{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;padding:.7rem .9rem;
      border:1px solid rgba(120,120,140,.18);border-radius:14px;backdrop-filter:blur(8px);
      background:linear-gradient(180deg, rgba(255,255,255,.65), rgba(255,255,255,.35));}
    .badge{padding:.25rem .6rem;border-radius:999px;font-size:12px;border:1px solid rgba(120,120,140,.25);}
    .small{font-size:12px;color:rgba(60,62,74,.72)}
    .stButton > button{width:100%;border-radius:12px;padding:.7rem 1rem;}
    .stDataFrame,.stDataEditor{border:1px solid rgba(120,120,140,.18);border-radius:14px;}
    a.anchor-link { display:none !important; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🔁 Slack Mesaj Taşıma")
    st.caption("Sabit kanallar, **seçilebilir gün** (00:00–23:59), mobil uyum. Seçili günde gönderilmiş mesajlar yeniden listelenmez.")

    # ---------------- TOP BAR ----------------
    colA, colB, colC = st.columns([2.6, 2.6, 2.2])

    with colA:
        st.markdown(f"""
        <div class="toolbar">
          <span class="badge">Kaynak</span> <b>{SRC_CHANNEL_ID}</b>
          <span class="small">ID sabit</span>
        </div>
        """, unsafe_allow_html=True)

    with colB:
        st.markdown(f"""
        <div class="toolbar">
          <span class="badge">Hedef</span> <b>{DST_CHANNEL_ID}</b>
          <span class="small">ID sabit</span>
        </div>
        """, unsafe_allow_html=True)

    with colC:
        picked = st.date_input("Gün seç", value=st.session_state["selected_date"])
        if picked != st.session_state["selected_date"]:
            st.session_state["selected_date"] = picked
            o, l = day_epoch_range(picked)
            st.session_state["oldest"], st.session_state["latest"] = o, l
            st.session_state["auto_loaded"] = False

    st.markdown(f"""
    <div class="toolbar" style="margin-top:.5rem;">
      <span class="badge">Filtre</span>
      {date_str(st.session_state["selected_date"])} · 00:00–23:59 (Europe/Istanbul)
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # ---------------- FETCH (AUTO-LOAD / REFRESH) ----------------
    def fetch_for_selected_day():
        try:
            msgs = fetch_messages(SRC_CHANNEL_ID, st.session_state["oldest"], st.session_state["latest"])
            st.session_state["messages"] = msgs
            st.toast(f"{len(msgs)} mesaj bulundu", icon="✅")
        except Exception as e:
            st.error(f"Mesajlar alınamadı: {e}")

    def apply_sent_filter():
        day_key = date_str(st.session_state["selected_date"])
        already = get_already_sent_ts_for(conn, SRC_CHANNEL_ID, day_key)
        st.session_state["messages"] = [m for m in st.session_state["messages"] if m["ts"] not in already]
        return day_key, already

    def refresh_selected_day_now():
        fetch_for_selected_day()
        return apply_sent_filter()

    refresh = st.button("↻ Yenile (Seçili Gün)")
    if refresh:
        day_k, already_sent_list = refresh_selected_day_now()
        st.session_state["auto_loaded"] = True

    if not st.session_state["auto_loaded"]:
        day_k, already_sent_list = refresh_selected_day_now()
        st.session_state["auto_loaded"] = True
    else:
        day_k = date_str(st.session_state["selected_date"])
        already_sent_list = get_already_sent_ts_for(conn, SRC_CHANNEL_ID, day_k)
        st.session_state["messages"] = [m for m in st.session_state["messages"] if m["ts"] not in already_sent_list]

    msgs = st.session_state.get("messages", [])

    # ---------------- QUICK SEARCH + SELECT ALL ----------------
    top1, top2 = st.columns([2, 1])
    with top1:
        search_q = st.text_input("Hızlı filtre", placeholder="örn. @ali, pdf, hata… (mobilde de çalışır)")
    with top2:
        select_all = st.checkbox("Tümünü Seç", value=True)

    msgs_filtered = [m for m in msgs if (search_q or "").lower() in (m.get("text") or "").lower()] if search_q else msgs

    # ---------------- TABLE ----------------
    def to_rows_and_ts(ms):
        rows, ts_order = [], []
        for m in ms:
            rows.append({"Seç": select_all, "Mesaj": (m.get("text") or "").replace("\n", " ")[:180], "Ek": len(m.get("files") or [])})
            ts_order.append(m["ts"])
        return rows, ts_order

    if msgs_filtered:
        rows, ts_order = to_rows_and_ts(msgs_filtered)
        df = pd.DataFrame(rows)
        edited = st.data_editor(
            df, use_container_width=True, hide_index=True,
            disabled=["Mesaj","Ek"],
            column_config={
                "Seç": st.column_config.CheckboxColumn("Seç"),
                "Mesaj": st.column_config.TextColumn("Mesaj"),
                "Ek": st.column_config.NumberColumn("Ek", help="Dosya adedi", width="small"),
            },
            height=520
        )
        selected_idx = edited.index[edited["Seç"] == True].tolist()
        selected_ts = [ts_order[i] for i in selected_idx]
    else:
        if already_sent_list:
            st.info(f"**{day_k}** günü daha önce gönderildiği için **{len(already_sent_list)}** mesaj gizlendi.", icon="ℹ️")
        else:
            st.info("Seçili gün için listelenecek mesaj yok.", icon="ℹ️")
        selected_ts = []

    st.divider()

    # ---------------- TRANSFER ----------------
    left, mid, right = st.columns([1.2, 1.2, 1])
    with left:
        copy_threads = st.checkbox("Thread yanıtlarını koru", value=True)
    with mid:
        keep_blocks = st.checkbox("Block Kit’i koru", value=True)
    with right:
        st.metric("Seçili", len(selected_ts))

    send_btn = st.button("✅ Seçilenleri Hedefe Gönder", type="primary", disabled=not (DST_CHANNEL_ID and selected_ts))

    if send_btn:
        try:
            to_send = [m for m in msgs_filtered if m["ts"] in selected_ts]
            with st.spinner("Gönderiliyor…"):
                result = transfer_messages(DST_CHANNEL_ID, to_send, copy_threads=copy_threads, keep_blocks=keep_blocks)
            mark_sent_ts_for(conn, SRC_CHANNEL_ID, selected_ts, day_k)
            st.success(
                f"{day_k} için tamamlandı → {result['messages_sent']} mesaj, {result['files_sent']} dosya. "
                f"Bu mesajlar aynı gün içinde tekrar listelenmeyecek.",
                icon="✅"
            )
            refresh_selected_day_now()
        except Exception as e:
            st.error(f"Gönderimde hata: {e}")

if __name__ == "__main__":
    run(False)
