# slack_helpers.py
import os
import time
import tempfile
import requests
from typing import Dict, List, Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ---------------------------
#   CLIENT (120s timeout)
# ---------------------------
def _client_from_env(src: bool) -> WebClient:
    token = os.environ.get("SRC_BOT_TOKEN") if src else os.environ.get("DST_BOT_TOKEN")
    if not token:
        raise RuntimeError("Gerekli bot token bulunamadı. .env veya st.secrets ile tanımlayın.")
    return WebClient(token=token, timeout=120)

# ---------------------------
#   KANALLARI LİSTELE
# ---------------------------
def list_channels(src: bool, types: str = "public_channel,private_channel") -> List[Dict]:
    client = _client_from_env(src)
    chans, cursor = [], None
    while True:
        resp = client.conversations_list(types=types, limit=200, cursor=cursor)
        chans += resp["channels"]
        cursor = resp.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    return [{"id": c["id"], "name": c["name"], "is_private": c.get("is_private", False)} for c in chans]

# ---------------------------
#   MESAJ ÇEK (Tarih Aralıklı)
# ---------------------------
def fetch_messages(source_channel: str, oldest: Optional[str], latest: Optional[str]) -> List[Dict]:
    client = _client_from_env(src=True)
    msgs, cursor = [], None
    while True:
        resp = client.conversations_history(
            channel=source_channel,
            oldest=oldest,
            latest=latest,
            limit=200,
            cursor=cursor,
            inclusive=True
        )
        for m in resp["messages"]:
            msgs.append({
                "ts": m["ts"],
                "user": m.get("user"),
                "text": m.get("text", ""),
                "files": m.get("files", []),
                "thread_ts": m.get("thread_ts"),
                "blocks": m.get("blocks")
            })
        cursor = resp.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    msgs.sort(key=lambda x: float(x["ts"]))
    return msgs

# ---------------------------
#   RATE LIMIT SAFE CALL
# ---------------------------
def post_with_retry(client: WebClient, method: str, **kwargs):
    for _ in range(6):
        try:
            return getattr(client, method)(**kwargs)
        except SlackApiError as e:
            if e.response.status_code == 429:
                wait = int(e.response.headers.get("Retry-After", "1"))
                time.sleep(wait)
                continue
            raise

# ---------------------------
#   DOSYA YÜKLEME (v2)
# ---------------------------
def _upload_file_to_target(
    dst: WebClient,
    file_path: str,
    filename: str,
    channel: str,
    thread_ts: Optional[str] = None,
    initial_comment: Optional[str] = None
):
    with open(file_path, "rb") as f:
        return post_with_retry(
            dst,
            "files_upload_v2",
            channel=channel,              # önemli: kök mesajda thread_ts GÖNDERME!
            file=f,
            filename=filename,
            initial_comment=initial_comment,
            thread_ts=thread_ts
        )

# Upload response'undan oluşan mesajın ts'ini çekmeye çalış
def _extract_message_ts_from_upload(resp, channel_id: str) -> Optional[str]:
    try:
        files = resp.get("files") or []
        if not files:
            return None
        shares = files[0].get("shares", {})
        for scope in ("public", "private"):
            chs = shares.get(scope, {})
            if channel_id in chs and chs[channel_id]:
                return chs[channel_id][0].get("ts")
    except Exception:
        pass
    return None

# ---------------------------
#   DOSYALARI KOPYALA (ilkine initial_comment)
# ---------------------------
def _copy_files(
    files: Optional[List[Dict]],
    target_channel: str,
    thread_ts: Optional[str],
    initial_comment: Optional[str] = None,
    return_first_ts: bool = False
) -> Optional[str]:
    """
    Dosyaları sırayla yükler. initial_comment sadece ilk dosyaya uygulanır.
    return_first_ts=True ise ilk yüklenen dosyanın mesaj ts'ini döner.
    """
    if not files:
        return None

    src_token = os.environ["SRC_BOT_TOKEN"]
    dst = _client_from_env(src=False)

    first_ts = None

    for idx, f in enumerate(files):
        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            continue

        headers = {"Authorization": f"Bearer {src_token}"}
        r = requests.get(url, headers=headers, stream=True, timeout=120)
        r.raise_for_status()

        name = f.get("name") or "file"
        suffix = "." + name.split(".")[-1] if "." in name else ""

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in r.iter_content(1024 * 1024):
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            resp = _upload_file_to_target(
                dst,
                tmp_path,
                name,
                target_channel,
                thread_ts=thread_ts,                      # reply ise parent'a bağlanır
                initial_comment=(initial_comment if idx == 0 else None)  # metin sadece ilk dosyada
            )
            if return_first_ts and first_ts is None:
                first_ts = _extract_message_ts_from_upload(resp, target_channel)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    return first_ts

# ---------------------------
#   TRANSFER (Ana Akış)
# ---------------------------
def transfer_messages(
    target_channel: str,
    items: List[Dict],
    copy_threads: bool = True,
    keep_blocks: bool = True
) -> Dict:
    """
    - Dosyalı KÖK mesaj: chat.postMessage atma; ilk dosyayı initial_comment=metin ile, thread_ts'siz yükle.
      Böylece metin+ek aynı üst seviye mesajda görünür.
    - Dosyalı REPLY: dosyayı thread_ts=parent_ts ile yükle; initial_comment=reply metni.
    - Dosyasız mesaj: chat.postMessage.
    """
    dst = _client_from_env(src=False)
    ts_map: Dict[str, str] = {}
    sent_count, file_count = 0, 0

    # kökler + cevaplar sıralaması
    roots = [i for i in items if (not i.get("thread_ts")) or (i.get("thread_ts") == i["ts"])]
    replies = [i for i in items if i not in roots]
    ordered = roots + replies

    for it in ordered:
        is_root = (not it.get("thread_ts")) or (it.get("thread_ts") == it["ts"])
        parent_ts = None if is_root else ts_map.get(it["thread_ts"])

        text = (it.get("text") or "").strip()
        files = it.get("files") or []

        if files:
            # --- DOSYALI MESAJ ---
            # kök ise thread_ts vermiyoruz (üst seviye), reply ise parent'a bağlıyoruz
            first_ts = _copy_files(
                files=files,
                target_channel=target_channel,
                thread_ts=(parent_ts if not is_root else None),
                initial_comment=text,
                return_first_ts=True
            )
            # Oluşan ilk dosya mesajının ts'ini, eşleme için sakla
            if first_ts:
                ts_map[it["ts"]] = first_ts
                parent_ts = first_ts
            file_count += len(files)
            sent_count += len(files)  # Slack her upload'ı bir mesaj olarak sayar

        else:
            # --- DOSYASIZ MESAJ ---
            kwargs = dict(channel=target_channel)
            if keep_blocks and it.get("blocks"):
                kwargs["blocks"] = it["blocks"]
                kwargs["text"] = text or " "
            else:
                kwargs["text"] = text or " "
            if parent_ts:
                kwargs["thread_ts"] = parent_ts

            sent = post_with_retry(dst, "chat_postMessage", **kwargs)
            new_ts = sent["ts"]
            ts_map[it["ts"]] = new_ts
            parent_ts = new_ts
            sent_count += 1

    return {"messages_sent": sent_count, "files_sent": file_count}
