# common/secrets_loader.py
import os, json

def load_secrets():
    """
    APP_SECRETS varsa st.secrets'e yükler.
    Streamlit'e hiçbir şey yazmaz; (ok, message) döner.
    """
    try:
        import streamlit as st  # sadece st.secrets'e atamak için
        env_key = "APP_SECRETS"
        if env_key in os.environ:
            st.secrets = json.loads(os.environ[env_key])
            return True, "Secrets yüklendi."
        else:
            return False, "APP_SECRETS bulunamadı (lokalde). Secrets'i elle injekte edebilirsin."
    except Exception as e:
        return False, f"APP_SECRETS JSON parse hatası: {e}"
