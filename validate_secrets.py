import os
import json
from dotenv import load_dotenv

def validate():
    # .env dosyasını yükle
    load_dotenv()
    
    raw = os.environ.get("APP_SECRETS")
    if not raw:
        print("❌ HATA: .env dosyasında APP_SECRETS bulunamadı!")
        return

    # 1. JSON Formatını Kontrol Et
    try:
        data = json.loads(raw)
        print("✅ BAŞARILI: JSON formatı tamamen geçerli ve hatasız!")
    except json.JSONDecodeError as e:
        print(f"❌ HATA: JSON formatı bozuk! Lütfen virgülleri ve tırnakları kontrol edin.\nDetay: {e}")
        return
        
    # 2. Kritik Anahtarları Kontrol Et
    required_keys = [
        "DISCORD_BOT_TOKEN",
        "SRC_BOT_TOKEN",
        "DST_BOT_TOKEN",
        "SRC_CHANNEL_ID",
        "DST_CHANNEL_ID",
        "SLACK_APP_TOKEN",
        "zendesk_account",
        "GOOGLE_SHEETS_CREDENTIALS",
        "zendesk",
        "slack"
    ]
    
    missing = []
    for key in required_keys:
        if key not in data:
            missing.append(key)
            
    if missing:
        print(f"⚠️ UYARI: JSON formatı doğru ama şu anahtarlar eksik: {', '.join(missing)}")
    else:
        print("✅ BAŞARILI: Tüm kritik sistem anahtarları (Slack, Discord, Zendesk, Google) eksiksiz yer alıyor.")

if __name__ == "__main__":
    print("--- APP_SECRETS KONTROL ARACI ---")
    validate()
    print("---------------------------------")
