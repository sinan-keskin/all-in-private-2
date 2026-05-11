# saat_uygulamasi/app.py
import json
import os
from datetime import datetime, timedelta
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ---------- page_config (tek sefer) ----------
try:
    if not st.session_state.get("_root_page_config_done", False):
        st.set_page_config(page_title="Saat ve Link Paneli", layout="wide")
        st.session_state["_root_page_config_done"] = True
except Exception:
    pass

# 🔐 Google Sheets client (standart)
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

# 📄 Google Sheet'e bağlan
def get_sheet():
    gc = _gs_client()
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", st.secrets.get("GOOGLE_SHEET_NAME", "Özel Bağlantılar"))
    # İstersen sheet_id de destekleyebilirsin; şimdilik isimle açıyoruz:
    return gc.open(sheet_name).sheet1

def load_links():
    sheet = get_sheet()
    return sheet.get_all_records()

# ✅ 3 parametreli versiyon (değişmedi)
def add_link(ad, url, kategori):
    sheet = get_sheet()
    sheet.append_row([ad, url, kategori])

def delete_link(ad):
    sheet = get_sheet()
    cell = sheet.find(ad)
    if cell:
        sheet.delete_rows(cell.row)

# 🎨 Hafif CSS
st.markdown("""
<style>
a.anchor-link { display:none !important; }
.stForm { background-color: rgba(255,255,255,0.02); padding: 1em; border-radius: 10px;
  border: 1px solid rgba(120,120,140,.18); }
.stButton>button { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

def main():
    st.title("🕒 Saat ve Link Paneli")
    tab1, tab2 = st.tabs(["Dönüştürücü", "Özel Bağlantılar"])

    # 🔁 Tab 1: Saat Dönüştürücü
    with tab1:
        st.subheader("Lokal Saat → Panel Saati")
        saat_araliklari = ["0"] + [f"{h}:{m:02}" for h in range(24) for m in (0, 30) if not (h == 0 and m == 0)]
        secilen_saat = st.selectbox("Lokal Saat Seç:", saat_araliklari)
        if secilen_saat == "0":
            secilen_saat = "00:00"
        bugun_str = datetime.now().strftime("%d.%m.%Y")
        lokal_saat = datetime.strptime(f"{bugun_str} {secilen_saat}", "%d.%m.%Y %H:%M")
        panel_saati = lokal_saat - timedelta(hours=3)

        saat_24 = "0" if (panel_saati.hour == 0 and panel_saati.minute == 0) else f"{panel_saati.hour}:{panel_saati.strftime('%M')}"
        saat_12_raw = panel_saati.strftime("%I:%M %p")
        saat = str(int(saat_12_raw.split(":")[0]))
        dakika = saat_12_raw.split(":")[1].split(" ")[0]
        am_pm = saat_12_raw.split(" ")[1].lower()
        saat_12 = f"{saat}:{dakika}{am_pm}" if saat_24 != "0" else "0"

        col1, col2 = st.columns(2)
        col1.write("12 Saat Dilimi"); col1.code(saat_12, language="text")
        col2.write("24 Saat Dilimi"); col2.code(saat_24, language="text")

        st.subheader("📋 Flaş Teklif Saatleri")
        teklifler = [
            ("TREU 12", "9:00", "12:00"),
            ("TREU 15", "12:00", "15:00"),
            ("TREU 18", "15:00", "18:00"),
            ("TREU 21", "18:00", "21:00"),
            ("LATAM 12", "18:00", "21:00"),
            ("LATAM 15 (Bitiş +1 Tarih)", "21:00", "0"),
            ("LATAM 18 (+1 Tarih)", "0", "3:00"),
            ("LATAM 21 (+1 Tarih)", "3:00", "6:00")
        ]
        for blok in ["TREU", "LATAM"]:
            with st.expander(f"🌎 {blok} Teklifleri", expanded=True):
                col0, col1, col2 = st.columns([2, 3, 3])
                col0.markdown("**Teklif**"); col1.markdown("**Başlangıç**"); col2.markdown("**Bitiş**")
                for teklif, bas, bit in teklifler:
                    if blok in teklif:
                        c0, c1, c2 = st.columns([2, 3, 3]); c0.markdown(f"**{teklif}**"); c1.code(bas); c2.code(bit)

    # 🔗 Tab 2: Özel Bağlantılar
    with tab2:
        st.markdown("## ➕ Bağlantı Ekle")
        with st.form("link_form", clear_on_submit=True):
            ad = st.text_input("Buton Adı")
            url = st.text_input("Buton Linki (https:// ile)")
            kategori = st.selectbox("Kategori", ["Sheet", "Klasör"])
            submitted = st.form_submit_button("Bağlantı Ekle")

        if submitted:
            if ad and url and kategori:
                add_link(ad, url, kategori)
                st.success(f"✅ '{ad}' bağlantısı eklendi.")
                st.experimental_rerun()
            else:
                st.warning("Tüm alanları doldur.")

        linkler = sorted(load_links(), key=lambda x: (x.get("kategori",""), x.get("ad","").lower()))
        st.subheader("📁 Klasör Bağlantıları")
        for item in linkler:
            if item.get("kategori", "").strip() == "Klasör":
                col1, col2, col3 = st.columns([4, 4, 2])
                col1.markdown(f"📁 **{item['ad']}**")
                col2.link_button("🔗 Git", item["url"], use_container_width=False)
                if col3.button("🗑️ Sil", key=item["ad"] + "_klasor"):
                    delete_link(item["ad"]); st.experimental_rerun()

        st.subheader("📄 Sheet Bağlantıları")
        for item in linkler:
            if item.get("kategori", "").strip() == "Sheet":
                col1, col2, col3 = st.columns([4, 4, 2])
                col1.markdown(f"📄 **{item['ad']}**")
                col2.link_button("🔗 Git", item["url"], use_container_width=False)
                if col3.button("🗑️ Sil", key=item["ad"] + "_sheet"):
                    delete_link(item["ad"]); st.experimental_rerun()

# --- wrapper (embed uyumlu) ---
def run(embedded: bool = False):
    if not embedded:
        try:
            st.set_page_config(page_title="Saat ve Link Paneli", layout="centered")
        except Exception:
            pass
    main()

if __name__ == "__main__":
    run()
