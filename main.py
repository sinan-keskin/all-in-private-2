# all-in-private/main.py
import importlib
import streamlit as st

st.set_page_config(page_title="All-in Private Control Center", layout="wide")
st.title("🧭 All-in Private — Control Center")
st.caption("Discord • Translation • Saat/Sheets • Zendesk • Slack")

def render_module(module_name: str):
    """
    Modülü aktif tab konteksinde çalıştır:
    - Varsa run(embedded=True) -> çağır
    - Yoksa main() -> çağır
    - Hiçbiri yoksa: reload ile top-level UI'yi bu tab içinde yeniden yürüt
    """
    try:
        mod = importlib.import_module(module_name)
        mod = importlib.reload(mod)  # top-level UI tab içinde çizilsin
    except Exception as e:
        st.error(f"{module_name} import/reload hatası: {e}")
        return

    try:
        if hasattr(mod, "run") and callable(mod.run):
            return mod.run(embedded=True)
        if hasattr(mod, "main") and callable(mod.main):
            return mod.main()
        return
    except Exception as e:
        st.error(f"{module_name} çalışma hatası: {e}")

# --- Slack listener'ı tab beklemeden bir kez ayağa kaldır ---
try:
    slack_mod = importlib.import_module("slack_transfer.app")
    if hasattr(slack_mod, "init") and callable(slack_mod.init):
        slack_mod.init()  # start_notify_once koruması var
except Exception as e:
    st.warning(f"slack_transfer.app.init() hata: {e}")

# --- Sekmeler ---
tabs = st.tabs([
    "1️⃣ Discord Audit",
    "2️⃣ Translation",
    "3️⃣ Saat & Link Paneli",
    "4️⃣ Zendesk Help Center",
    "5️⃣ Slack Transfer",
    "6️⃣ Zendesk Raporları"
])

with tabs[0]:
    render_module("discord_audit.app")
with tabs[1]:
    render_module("translation.app")
with tabs[2]:
    render_module("saat_uygulamasi.app")
with tabs[3]:
    render_module("helpcenter_streamlit.app")
with tabs[4]:
    render_module("slack_transfer.app")
with tabs[5]:
    render_module("zendesk_reports.app")
