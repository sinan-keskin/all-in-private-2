# all-in-private/main.py
import importlib
import streamlit as st

st.set_page_config(page_title="All-in Private Control Center", layout="wide")

# ─────────────────────────────────────────────
# 🔒 YÖNETİCİ GİRİŞİ
# ─────────────────────────────────────────────
def check_login():
    """Session state üzerinden şifre kontrolü yapar."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    # ── Login UI ──────────────────────────────
    st.markdown("""
    <style>
    /* Arka plan */
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    }
    /* Merkez kart */
    .login-card {
        max-width: 420px;
        margin: 10vh auto 0 auto;
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 20px;
        padding: 48px 40px 40px 40px;
        backdrop-filter: blur(16px);
        box-shadow: 0 24px 60px rgba(0,0,0,0.5);
        text-align: center;
    }
    .login-card h1 { color: #fff; font-size: 1.7rem; margin-bottom: 4px; }
    .login-card p  { color: #aaa; font-size: 0.9rem; margin-bottom: 32px; }
    /* Hata mesajı */
    .login-error {
        background: rgba(255,80,80,0.15);
        border: 1px solid rgba(255,80,80,0.4);
        border-radius: 10px;
        padding: 10px 16px;
        color: #ff6b6b;
        font-size: 0.88rem;
        margin-top: 14px;
    }
    </style>
    """, unsafe_allow_html=True)

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("""
        <div class="login-card">
            <h1>🔐 All-in Private</h1>
            <p>Control Center — Yönetici Girişi</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=True):
            password = st.text_input(
                "Yönetici Şifresi",
                type="password",
                placeholder="••••••••••",
                label_visibility="visible"
            )
            submitted = st.form_submit_button("🔓 Giriş Yap", use_container_width=True)

        if submitted:
            correct = st.secrets.get("ADMIN_PASSWORD", "")
            if password == correct:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Hatalı şifre. Tekrar deneyin.")

    return False

# ─────────────────────────────────────────────
# ANA UYGULAMA
# ─────────────────────────────────────────────
if not check_login():
    st.stop()

# Buraya geldiyse kullanıcı giriş yapmış demektir ✅
st.title("🧭 All-in Private — Control Center")
st.caption("Discord • Translation • Saat/Sheets • Zendesk • Slack")

# Çıkış butonu (sağ üst)
with st.sidebar:
    st.markdown("### 👤 Yönetici")
    st.success("✅ Giriş yapıldı")
    if st.button("🚪 Çıkış Yap", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

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
