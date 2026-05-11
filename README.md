🧭 All-in Private — Unified Control Center
<p align="center"> <img src="https://img.shields.io/badge/Streamlit-v1.38.0-FF4B4B?logo=streamlit&logoColor=white&style=for-the-badge"/> <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white&style=for-the-badge"/> <img src="https://img.shields.io/badge/License-Private-darkred?style=for-the-badge"/> </p> <p align="center"> <img src="https://github.com/user-attachments/assets/4adff1f5-07cb-4fd9-bbc2-cda4cc2a8d7f" width="720"/> </p>

🚀 All-in Private, Discord, Slack, Zendesk, Google Sheets ve Translation araçlarını
tek bir Streamlit panelinde birleştiren özel yapım, çok fonksiyonlu bir kontrol merkezidir.

Tüm uygulamalar tek secret JSON ile yönetilir —
“5 ayrı dashboard yerine tek kumanda masası.”

🌐 İçindekiler
```
✨ Özellikler
🗂️ Uygulama Yapısı
🔐 Secret Sistemi (Tek JSON)
⚙️ Kurulum ve Çalıştırma
🧩 Sekmelerin Detayları
💎 Ekran Görselleri
⚠️ Güvenlik Notları
📜 Lisans
```

### ✨ Özellikler

| Alan                         | Açıklama                                                                                                                   |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 🎮 **Discord Audit Panel**   | Discord sunucularındaki **ban**, **kick**, **timeout** ve **mesaj silme** kayıtlarını analiz eder.                         |
| 🌍 **Translation App**       | Türkçe metinleri **İngilizce, İspanyolca, Portekizce, Azerice** vb. dillere çevirir; özel kelime eşleştirmeleri destekler. |
| 🕒 **Saat & Link Paneli**    | Saat dönüştürücü + Google Sheets tabanlı özel bağlantı yöneticisi.                                                         |
| 🧾 **Zendesk Help Center**   | Makaleleri çeviri durumuna göre listeler, düzenleme & toplu export/import sunar.                                           |
| 🔁 **Slack Transfer Tool**   | Kanallar arası mesaj & dosya transferi yapar. Socket Mode ile **reaction/mention listener** içerir.                        |
| 🧩 **Tek Sayfa, Tek Secret** | Tüm uygulamalar `APP_SECRETS` adlı tek JSON ile yönetilir.                                                                 |


#🗂️ Uygulama Yapısı
```markdown
all-in-private/
│
├── main.py                        # Ana kontrol paneli (sekme tabanlı)
├── requirements.txt                # Tek dependency listesi
│
├── common/
│   └── secrets_loader.py           # APP_SECRETS yükleyici
│
├── discord_audit/
│   ├── app.py
│   └── users.json
│
├── translation/
│   ├── app.py
│   └── special_translations.json
│
├── saat_uygulamasi/
│   └── app.py
│
├── helpcenter_streamlit/
│   ├── app.py
│   └── zendesk.py
│
└── slack_transfer/
    ├── app.py
    └── slack_helpers.py
```

🔐 Secret Sistemi (Tek JSON)

All-in Private, tüm API anahtarlarını tek bir secret içinde kullanır:
GitHub’da → Settings → Secrets → Actions → New repository secret

Name: APP_SECRETS
Value: (örnek JSON aşağıda)
```markdown
{
  "DISCORD_BOT_TOKEN": "discord_bot_token_buraya",

  "GOOGLE_SHEETS_CREDENTIALS": {
    "type": "service_account",
    "project_id": "your-gcp-project-id",
    "private_key_id": "xxxxxxxxxxxxxxxxxxxx",
    "private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n",
    "client_email": "service-account@project.iam.gserviceaccount.com",
    "client_id": "123456789",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token"
  },

  "zendesk_account": {
    "subdomain": "your_zendesk_subdomain",
    "email": "your@email.com",
    "api_token": "your_zendesk_api_token"
  },

  "SRC_BOT_TOKEN": "xoxb-src...",
  "DST_BOT_TOKEN": "xoxb-dst...",
  "SRC_CHANNEL_ID": "C0123456789",
  "DST_CHANNEL_ID": "C9876543210",
  "SLACK_APP_TOKEN": "xapp-1-...",
  "NOTIFY_USER_ID": "U111111111"
}
```

Bu tek secret → tüm app’ler için st.secrets’e otomatik yüklenir 🔒

⚙️ Kurulum ve Çalıştırma
🔧 Lokal Kurulum
```markdown
git clone https://github.com/<senin-adin>/all-in-private.git
cd all-in-private
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

🔐 Secret’ı Lokalde Aktarma
```markdown
export APP_SECRETS="$(cat ./APP_SECRETS.json)"
```

🚀 Çalıştır
```markdown
streamlit run main.py
```

☁️ Streamlit Cloud / Codespaces

Sadece APP_SECRETS environment değişkenini ekle, başka ayar gerekmez.
Hepsi tek JSON’dan otomatik yüklenir.

🧩 Sekme Detayları
1️⃣ Discord Audit

🔎 Ban / Kick / Timeout / Mesaj Silme raporu, kullanıcı bazlı istatistik, CSV export.

<p align="center"><img src="https://github.com/user-attachments/assets/2ea77564-8e22-4d8a-a3a8-3f80173082a8" width="720"></p>
2️⃣ Translation

📘 Türkçe metinleri çok dillere çevirir, özel kelime istisnaları destekler.

Excel yükleme

Otomatik çeviri

Özel terim listesi düzenleme

<p align="center"><img src="https://github.com/user-attachments/assets/5f2b99ce-5b83-4011-bb4e-4e5ee409efb1" width="720"></p>
3️⃣ Saat & Link Paneli

🕒 Zaman dönüştürme + Sheets tabanlı bağlantı yönetimi

TREU & LATAM saat blokları

“Sheet” / “Klasör” bağlantıları

<p align="center"><img src="https://github.com/user-attachments/assets/40d1ac10-1e5e-46ed-9b61-baa68c49a5a5" width="720"></p>
4️⃣ Zendesk Help Center

🌐 Makale çeviri yönetimi

Eksik / güncel olmayan çevirileri tarar

Quill editörle inline düzenleme

Excel export & import desteği

<p align="center"><img src="https://github.com/user-attachments/assets/11dc7489-f0cf-45b5-8cb4-8a33244bb4cc" width="720"></p>
5️⃣ Slack Transfer

🔁 Kanal mesajlarını taşı, dosyaları kopyala, reply/thread koru

Gün seçimi (00:00–23:59)

Günlük gönderi engelleme (SQLite ile)

Reaction / Mention listener (Socket Mode)

<p align="center"><img src="https://github.com/user-attachments/assets/ae3bb23a-1b26-4d56-b3c3-220fc6bb2e12" width="720"></p>
💎 Ekran Görselleri
<p align="center"> <img src="https://github.com/user-attachments/assets/828df5e2-4f72-4a84-bcd0-4f23a5bde74b" width="260"> <img src="https://github.com/user-attachments/assets/13d5e2f3-24a0-4a3f-b3e4-d8e6f2bb45f3" width="260"> <img src="https://github.com/user-attachments/assets/4e8320c9-c88c-4df2-b520-8d6e14e712d1" width="260"> </p>
⚠️ Güvenlik Notları

❗ Uygulama özel anahtarlar ve API token’ları içerdiği için kesinlikle public repo yapılmamalıdır.

DISCORD_BOT_TOKEN, SLACK_APP_TOKEN, zendesk_account.api_token, GOOGLE_SHEETS_CREDENTIALS.private_key gibi bilgiler gizli kalmalıdır.

Token sızıntısında ilgili platformlardan hemen revoke edip yenisini oluştur.

📜 Lisans

🔒 Bu proje özel kullanım içindir.
İzinsiz paylaşım, klonlama veya public deployment yasaktır.

<p align="center"> Made with ❤️ by <b>All-in Private Dev Team</b> <br/>Python • Streamlit • Slack • Discord • Zendesk • Google Cloud </p>
