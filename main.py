# all-in-private/main.py
import importlib
import hashlib
import streamlit as st

# Cookie manager – session kalıcılığı için
try:
    import extra_streamlit_components as stx
    _COOKIE_MANAGER_AVAILABLE = True
except ImportError:
    _COOKIE_MANAGER_AVAILABLE = False

st.set_page_config(
    page_title="All-in Private — Control Center",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────
# GLOBAL CSS  — Login ekranı + genel tema
# ──────────────────────────────────────────────────────────────
LOGIN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Reset & body ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
    font-family: 'Inter', sans-serif !important;
    background: #080b14 !important;
    overflow-x: hidden;
}

/* ── Animated mesh gradient ── */
[data-testid="stAppViewContainer"]::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
        radial-gradient(ellipse 80% 60% at 20% -10%, rgba(99,102,241,.35) 0%, transparent 60%),
        radial-gradient(ellipse 60% 50% at 80%  110%, rgba(168,85,247,.25) 0%, transparent 55%),
        radial-gradient(ellipse 40% 40% at 50%  50%, rgba(14,165,233,.10) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
    animation: meshMove 12s ease-in-out infinite alternate;
}
@keyframes meshMove {
    0%   { opacity: .8; transform: scale(1); }
    100% { opacity: 1;  transform: scale(1.06); }
}

/* ── Floating orbs ── */
[data-testid="stAppViewContainer"]::after {
    content: '';
    position: fixed;
    width: 600px; height: 600px;
    top: -200px; left: -200px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(99,102,241,.12) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
    animation: orbFloat 8s ease-in-out infinite;
}
@keyframes orbFloat {
    0%, 100% { transform: translate(0, 0); }
    50%       { transform: translate(80px, 60px); }
}

/* Hide Streamlit chrome on login */
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stSidebar"],
footer { display: none !important; }

/* ── Outer wrapper ── */
.login-wrapper {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 24px;
}

/* ── Card ── */
.login-card {
    width: 100%;
    max-width: 440px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 28px;
    padding: 56px 44px 48px;
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    box-shadow:
        0 0 0 1px rgba(99,102,241,.15),
        0 32px 80px -12px rgba(0,0,0,.7),
        inset 0 1px 0 rgba(255,255,255,.08);
    animation: cardIn .6s cubic-bezier(.22,1,.36,1) both;
}
@keyframes cardIn {
    from { opacity:0; transform: translateY(32px) scale(.96); }
    to   { opacity:1; transform: translateY(0)    scale(1);   }
}

/* ── Brand ── */
.brand-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 68px; height: 68px;
    border-radius: 20px;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    font-size: 30px;
    margin: 0 auto 20px;
    box-shadow: 0 8px 32px rgba(99,102,241,.5);
    animation: iconPulse 3s ease-in-out infinite;
}
@keyframes iconPulse {
    0%, 100% { box-shadow: 0 8px 32px rgba(99,102,241,.5); }
    50%       { box-shadow: 0 8px 48px rgba(139,92,246,.7); }
}
.brand-title {
    color: #fff;
    font-size: 1.65rem;
    font-weight: 700;
    text-align: center;
    letter-spacing: -0.5px;
    margin-bottom: 6px;
}
.brand-sub {
    color: rgba(255,255,255,.4);
    font-size: .85rem;
    text-align: center;
    margin-bottom: 40px;
    font-weight: 400;
}

/* ── Form label ── */
.field-label {
    color: rgba(255,255,255,.65);
    font-size: .78rem;
    font-weight: 600;
    letter-spacing: .08em;
    text-transform: uppercase;
    margin-bottom: 8px;
}

/* Override Streamlit input */
[data-testid="stTextInput"] input {
    background: rgba(255,255,255,0.06) !important;
    border: 1.5px solid rgba(255,255,255,0.10) !important;
    border-radius: 14px !important;
    color: #fff !important;
    font-family: 'Inter', sans-serif !important;
    font-size: .95rem !important;
    padding: 14px 18px !important;
    transition: border-color .2s, box-shadow .2s !important;
    caret-color: #6366f1;
}
[data-testid="stTextInput"] input:focus {
    border-color: rgba(99,102,241,.7) !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,.18) !important;
    outline: none !important;
}
[data-testid="stTextInput"] input::placeholder { color: rgba(255,255,255,.25) !important; }
[data-testid="stTextInput"] label { display: none !important; }

/* ── Submit button ── */
[data-testid="stFormSubmitButton"] > button {
    width: 100% !important;
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
    border: none !important;
    border-radius: 14px !important;
    color: #fff !important;
    font-family: 'Inter', sans-serif !important;
    font-size: .95rem !important;
    font-weight: 600 !important;
    padding: 15px !important;
    margin-top: 12px !important;
    cursor: pointer !important;
    transition: all .2s !important;
    box-shadow: 0 4px 20px rgba(99,102,241,.4) !important;
    letter-spacing: .02em !important;
}
[data-testid="stFormSubmitButton"] > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 30px rgba(99,102,241,.55) !important;
    background: linear-gradient(135deg, #5254cc 0%, #7c3aed 100%) !important;
}
[data-testid="stFormSubmitButton"] > button:active {
    transform: translateY(0) !important;
}

/* ── Error / success alerts ── */
[data-testid="stAlert"] {
    border-radius: 12px !important;
    margin-top: 12px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: .88rem !important;
}

/* ── Footer note ── */
.login-footer {
    text-align: center;
    margin-top: 28px;
    color: rgba(255,255,255,.2);
    font-size: .75rem;
}
.login-footer span { color: rgba(99,102,241,.7); font-weight: 600; }

/* ── Sidebar logout button (post-login) ── */
[data-testid="stSidebar"] { background: #0d1117 !important; border-right: 1px solid rgba(255,255,255,.06) !important; }
</style>
"""

APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
html, body, [data-testid="stAppViewContainer"] {
    font-family: 'Inter', sans-serif !important;
    background: #080b14 !important;
}
[data-testid="stSidebar"] {
    background: #0d1117 !important;
    border-right: 1px solid rgba(255,255,255,.06) !important;
}
[data-testid="stHeader"] { background: transparent !important; }
.stTabs [data-baseweb="tab-list"] { background: rgba(255,255,255,.03) !important; border-radius: 12px !important; padding: 4px !important; gap: 2px !important; }
.stTabs [data-baseweb="tab"] { color: rgba(255,255,255,.5) !important; border-radius: 9px !important; font-family: 'Inter', sans-serif !important; font-size: .85rem !important; font-weight: 500 !important; padding: 8px 16px !important; }
.stTabs [aria-selected="true"] { background: linear-gradient(135deg,#6366f1,#8b5cf6) !important; color: #fff !important; box-shadow: 0 4px 14px rgba(99,102,241,.4) !important; }
</style>
"""

# ──────────────────────────────────────────────────────────────
# COOKIE SESSION YÖNETİMİ
# ──────────────────────────────────────────────────────────────
COOKIE_NAME = "aip_auth"
SESSION_HOURS = 12  # Kaç saat oturum açık kalsın

def _get_cookie_manager():
    if not _COOKIE_MANAGER_AVAILABLE:
        return None
    return stx.CookieManager(key="aip_cookie_mgr")

def _make_token(password: str) -> str:
    """Şifre + gizli tuz ile bir oturum token'ı üret."""
    salt = "aip_salt_2025"
    return hashlib.sha256(f"{password}{salt}".encode()).hexdigest()[:32]

def is_authenticated() -> bool:
    """
    1. session_state'i kontrol et (aynı sekme/sayfa yenileme)
    2. Cookie'yi kontrol et (tarayıcı yeniden açıldığında)
    """
    # Zaten memory'de varsa direkt geç
    if st.session_state.get("authenticated"):
        return True

    # Cookie'yi oku
    if _COOKIE_MANAGER_AVAILABLE:
        try:
            cm = _get_cookie_manager()
            cookie_val = cm.get(COOKIE_NAME)
            if cookie_val:
                correct_pw = st.secrets.get("ADMIN_PASSWORD", "")
                expected = _make_token(correct_pw)
                if cookie_val == expected:
                    st.session_state["authenticated"] = True
                    return True
        except Exception:
            pass

    return False

def set_authenticated(password: str):
    st.session_state["authenticated"] = True
    if _COOKIE_MANAGER_AVAILABLE:
        try:
            cm = _get_cookie_manager()
            token = _make_token(password)
            import datetime
            expires = datetime.datetime.now() + datetime.timedelta(hours=SESSION_HOURS)
            cm.set(COOKIE_NAME, token, expires_at=expires)
        except Exception:
            pass

def logout():
    st.session_state["authenticated"] = False
    if _COOKIE_MANAGER_AVAILABLE:
        try:
            cm = _get_cookie_manager()
            cm.delete(COOKIE_NAME)
        except Exception:
            pass

# ──────────────────────────────────────────────────────────────
# LOGIN SAYFASI
# ──────────────────────────────────────────────────────────────
def show_login():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)

    # Çoklu col hilesi: orta kolda form göster
    _, col, _ = st.columns([1, 1.3, 1])

    with col:
        # Brand bloğu
        st.markdown("""
        <div style="text-align:center;padding-top:10vh;">
            <div class="brand-icon">🔐</div>
            <div class="brand-title">All-in Private</div>
            <div class="brand-sub">Control Center &mdash; Yönetici Girişi</div>
        </div>
        """, unsafe_allow_html=True)

        # Şifre formu
        with st.form("login_form", clear_on_submit=True):
            st.markdown('<div class="field-label">Yönetici Şifresi</div>', unsafe_allow_html=True)
            password = st.text_input(
                "pwd",
                type="password",
                placeholder="••••••••••••",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("🔓  Giriş Yap", use_container_width=True)

        if submitted:
            correct = st.secrets.get("ADMIN_PASSWORD", "")
            if password and password == correct:
                set_authenticated(password)
                st.rerun()
            elif submitted:
                st.error("❌  Hatalı şifre. Lütfen tekrar deneyin.")

        st.markdown("""
        <div class="login-footer">
            Oturum <span>12 saat</span> boyunca açık kalır
        </div>
        """, unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────
# ANA UYGULAMA
# ──────────────────────────────────────────────────────────────
if not is_authenticated():
    show_login()
    st.stop()

# ── Giriş yapıldı ──
st.markdown(APP_CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("""
    <div style='text-align:center;padding:20px 0 12px;'>
        <div style='font-size:2rem;'>🔐</div>
        <div style='color:#fff;font-weight:700;font-size:1rem;margin-top:6px;'>All-in Private</div>
        <div style='color:rgba(255,255,255,.35);font-size:.75rem;margin-top:2px;'>Control Center</div>
    </div>
    <hr style='border-color:rgba(255,255,255,.07);margin:8px 0 16px;'/>
    """, unsafe_allow_html=True)
    st.success("✅ Oturum açık", icon="🟢")
    st.markdown("<br/>", unsafe_allow_html=True)
    if st.button("🚪  Çıkış Yap", use_container_width=True, type="secondary"):
        logout()
        st.rerun()

st.title("🧭 All-in Private — Control Center")
st.caption("Discord • Translation • Saat/Sheets • Zendesk • Slack")

def render_module(module_name: str):
    try:
        mod = importlib.import_module(module_name)
        mod = importlib.reload(mod)
    except Exception as e:
        st.error(f"{module_name} import/reload hatası: {e}")
        return
    try:
        if hasattr(mod, "run") and callable(mod.run):
            return mod.run(embedded=True)
        if hasattr(mod, "main") and callable(mod.main):
            return mod.main()
    except Exception as e:
        st.error(f"{module_name} çalışma hatası: {e}")

# Slack listener
try:
    slack_mod = importlib.import_module("slack_transfer.app")
    if hasattr(slack_mod, "init") and callable(slack_mod.init):
        slack_mod.init()
except Exception as e:
    st.warning(f"slack_transfer.app.init() hata: {e}")

tabs = st.tabs([
    "1️⃣ Discord Audit",
    "2️⃣ Translation",
    "3️⃣ Saat & Link Paneli",
    "4️⃣ Zendesk Help Center",
    "5️⃣ Slack Transfer",
    "6️⃣ Zendesk Raporları"
])

with tabs[0]: render_module("discord_audit.app")
with tabs[1]: render_module("translation.app")
with tabs[2]: render_module("saat_uygulamasi.app")
with tabs[3]: render_module("helpcenter_streamlit.app")
with tabs[4]: render_module("slack_transfer.app")
with tabs[5]: render_module("zendesk_reports.app")
