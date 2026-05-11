# helpcenter_streamlit/app.py
import io, math
from html import escape
import streamlit as st
import pandas as pd
from typing import Dict, Any, List, Tuple
from streamlit_quill import st_quill
from .zendesk import ZendeskClient

# ---------- page_config (tek sefer) ----------
try:
    if not st.session_state.get("_root_page_config_done", False):
        st.set_page_config(page_title="Zendesk Help Center • Çeviri Yönetimi", layout="wide")
        st.session_state["_root_page_config_done"] = True
except Exception:
    pass

# ---------- yardımcılar ----------
def clear_selection():
    st.session_state.pop("selected_article_id", None)

def ss_get(name, default=None):
    if name not in st.session_state:
        st.session_state[name] = default
    return st.session_state[name]

def render_ui():
    # ----- Başlık -----
    st.markdown(
        "<div class='app-title'>🌐 Zendesk Help Center - Çeviri Yönetimi</div>",
        unsafe_allow_html=True
    )

    import os
    def _get_sec(k): return os.environ.get(k, st.secrets.get(k))
    ACC = {
        "subdomain": _get_sec("ZENDESK_HC_SUBDOMAIN"),
        "email": _get_sec("ZENDESK_HC_EMAIL"),
        "api_token": _get_sec("ZENDESK_HC_API_TOKEN")
    }

    # ---- Locale görünür adları ----
    _LOCALE_MAP = {
        "TR": "Türkiye",
        "AR": "Arapça",
        "AZ": "Azerbaycanca",
        "EN-US": "İngilizce",
        "ES": "İspanyolca",
        "PT-BR": "Portekizce",
        "RU": "Rusça",
    }
    def pretty_locale(loc: str) -> str:
        if not loc:
            return loc
        return _LOCALE_MAP.get(loc.replace("_", "-").upper(), loc)

    def reorder_locales_tr_first(locales: List[str]) -> List[str]:
        if not locales:
            return locales
        norm = [l.replace("_", "-").upper() for l in locales]
        out: List[str] = []
        if "TR" in norm:
            out.append(locales[norm.index("TR")])
        out += [l for i, l in enumerate(locales) if norm[i] != "TR"]
        return out

    # ---- Global sabitler ----
    CACHE_TTL = 300   # sn
    PER_PAGE = 100
    MAX_PAGES = 1000

    # ---- Stil ----
    st.markdown("""
    <style>
    .app-title{ font-size:2.2rem; font-weight:800; line-height:1.15; margin:0 0 .5rem 0; }
    .section-title{ font-size:1.4rem; font-weight:700; margin:.5rem 0 .5rem; }
    .hc-cell{ border:1px solid rgba(255,255,255,0.15); padding:6px 8px; min-height:34px;
      display:flex; align-items:center; justify-content:center; text-align:center; font-variant-numeric: tabular-nums;}
    .hc-header{ font-weight:600; background:rgba(255,255,255,0.04); }
    .hc-title-left{ justify-content:flex-start !important; text-align:left !important; white-space:nowrap !important;
      overflow:hidden !important; text-overflow:clip !important; }
    .hc-spacer{ border:none !important; background:transparent !important; }
    a.anchor-link { display:none !important; }
    .stButton > button, .stLinkButton > a{ width:100%; height:34px; min-height:34px; padding:0; line-height:34px;
      border:1px solid rgba(255,255,255,0.15); border-radius:0.25rem; background:transparent; }
    .stButton > button:hover, .stLinkButton > a:hover{ background: rgba(255,255,255,0.06); }
    div[data-baseweb="select"] input{
      color: transparent !important; caret-color: transparent !important; text-shadow: 0 0 0 transparent !important;
      pointer-events: none !important; height: 0 !important; min-height: 0 !important; padding: 0 !important;
      margin: 0 !important; border: 0 !important;
    }
    div[data-baseweb="select"] input::placeholder{ color: transparent !important; }
    </style>
    """, unsafe_allow_html=True)

    # ---- Cache: API ----
    @st.cache_data(ttl=CACHE_TTL, show_spinner=False)
    def get_brands(subdomain: str, email: str, token: str) -> List[Dict[str, Any]]:
        return ZendeskClient(subdomain, email, token).list_brands()

    @st.cache_data(ttl=CACHE_TTL, show_spinner=False)
    def get_locales(subdomain: str, email: str, token: str, brand_sub: str) -> Tuple[List[str], str]:
        return ZendeskClient(subdomain, email, token).with_brand(brand_sub).get_help_center_locales()

    @st.cache_data(ttl=CACHE_TTL, show_spinner=False)
    def get_articles(subdomain: str, email: str, token: str, brand_sub: str, per_page: int, max_pages: int) -> List[Dict[str, Any]]:
        return list(ZendeskClient(subdomain, email, token).with_brand(brand_sub)
                    .list_articles_paginated(per_page=per_page, max_pages=max_pages))

    @st.cache_data(ttl=CACHE_TTL, show_spinner=False)
    def get_bulk_status(subdomain: str, email: str, token: str, brand_sub: str, ids: List[int], workers: int) -> Dict[int, Dict[str, Any]]:
        return ZendeskClient(subdomain, email, token).with_brand(brand_sub).bulk_status(ids, max_workers=workers)

    # ---------- Üst düzey sekmeler (sidebar yerine) ----------
    tab_settings, tab_list, tab_excel = st.tabs(["⚙️ Ayarlar", "📚 Liste", "📄 Excel"])

    # =============== ⚙️ Ayarlar ===============
    with tab_settings:
        st.markdown("<div class='section-title' style='margin-top:0'>Ayarlar</div>", unsafe_allow_html=True)

        brands = get_brands(ACC["subdomain"], ACC["email"], ACC["api_token"])
        brands = [b for b in brands if b.get("has_help_center") and b.get("help_center_state") == "enabled"]
        if not brands:
            st.error("Bu hesapta aktif Help Center'ı olan marka yok.")
            st.stop()

        brand_options = list(range(len(brands)))
        prev_brand_idx = ss_get("prev_brand_idx", 0)
        brand_idx = st.selectbox(
            "Help Center (Marka) seç",
            options=brand_options,
            format_func=lambda i: f"{brands[i]['name']} ({brands[i]['subdomain']})",
            index=min(prev_brand_idx, len(brand_options)-1),
            key="brand_select",
        )
        if brand_idx != prev_brand_idx:
            st.session_state["prev_brand_idx"] = brand_idx
            clear_selection()

        brand = brands[brand_idx]
        brand_sub = brand["subdomain"]

        max_workers = st.slider("Eşzamanlı istek sayısı", 4, 32, 12, 2, on_change=clear_selection)

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("🧹 Önbelleği temizle"):
                st.cache_data.clear(); clear_selection(); st.success("Önbellek temizlendi.")
        with c2:
            if st.button("🔄 Marka listesini yenile"):
                st.cache_data.clear(); clear_selection(); st.rerun()
        with c3:
            if st.button("▶ Tarama Başlat / Yenile", type="primary", on_click=clear_selection):
                st.session_state["scan"] = True
                st.session_state["page"] = 1

        # Filtreler
        st.markdown("<div class='section-title'>Filtreler</div>", unsafe_allow_html=True)
        prev_missing = ss_get("prev_missing", False)
        prev_outdated = ss_get("prev_outdated", False)
        colm, colo = st.columns(2)
        with colm:
            only_missing = st.checkbox("⛔ Sadece Çevirisi Eksikleri Olanları Göster", prev_missing)
        with colo:
            only_outdated = st.checkbox("⚠️ Sadece Çevirisi Yanlış Olanları Göster", prev_outdated)
        if (only_missing != prev_missing) or (only_outdated != prev_outdated):
            st.session_state["prev_missing"] = only_missing
            st.session_state["prev_outdated"] = only_outdated
            clear_selection()

    # State dışındaki sekmeler de brand_sub’a ihtiyaç duyuyor → güvenli alalım
    brands = get_brands(ACC["subdomain"], ACC["email"], ACC["api_token"])
    brands = [b for b in brands if b.get("has_help_center") and b.get("help_center_state") == "enabled"]
    brand_idx = ss_get("prev_brand_idx", 0)
    brand_idx = min(brand_idx, max(0, len(brands)-1))
    brand = brands[brand_idx]
    brand_sub = brand["subdomain"]
    only_missing = ss_get("prev_missing", False)
    only_outdated = ss_get("prev_outdated", False)

    # =============== 📚 Liste ===============
    df = None
    locales: List[str] = []
    default_locale = None

    def title_font_px(text: str) -> int:
        n = len(text or "")
        if n <= 60: return 14
        if n <= 90: return 13
        if n <= 120: return 10
        return 8

    with tab_list:
        if st.session_state.get("scan"):
            with st.spinner("Diller ve makaleler alınıyor..."):
                locales, default_locale = get_locales(ACC["subdomain"], ACC["email"], ACC["api_token"], brand_sub)
                if not locales:
                    st.warning("Etkin locale bulunamadı."); st.stop()

                locales = reorder_locales_tr_first(locales)
                articles = get_articles(ACC["subdomain"], ACC["email"], ACC["api_token"], brand_sub, PER_PAGE, MAX_PAGES)
                ids = [a.get("id") for a in articles]
                status_map = get_bulk_status(ACC["subdomain"], ACC["email"], ACC["api_token"], brand_sub, ids, ss_get("max_workers", 12) or 12)

                rows: List[Dict[str, Any]] = []
                for art in articles:
                    a_id = art.get("id")
                    title = art.get("title") or art.get("name") or "(untitled)"
                    url = art.get("html_url") or art.get("url")
                    missing = set(status_map.get(a_id, {}).get("missing", []))
                    outdated = set(status_map.get(a_id, {}).get("outdated", []))
                    row = {"id": a_id, "title": title, "html_url": url,
                           "missing_count": len(missing), "outdated_count": len(outdated)}
                    for loc in locales:
                        row[loc] = "MISSING" if loc in missing else ("OUTDATED" if loc in outdated else "OK")
                    rows.append(row)

            df = pd.DataFrame(rows).sort_values(["missing_count", "outdated_count"], ascending=[False, False])

            # Filtre mantığı (OR)
            if only_missing and only_outdated:
                df = df[(df["missing_count"] > 0) | (df["outdated_count"] > 0)]
            elif only_missing:
                df = df[df["missing_count"] > 0]
            elif only_outdated:
                df = df[df["outdated_count"] > 0]

            st.markdown("<div class='section-title'>Hızlı İşlem Listesi</div>", unsafe_allow_html=True)

            # Sayfalama
            page_size = 20
            total_rows = len(df)
            total_pages = max(1, math.ceil(total_rows / page_size))
            cur_page = ss_get("page", 1)
            cur_page = max(1, min(cur_page, total_pages))
            st.session_state["page"] = cur_page

            start = (cur_page - 1) * page_size
            end = min(start + page_size, total_rows)
            page_df = df.iloc[start:end].copy()

            def build_widths(locales: List[str]) -> List[float]:
                widths = [1.0, 5.8, 0.6]
                for loc in locales:
                    w = 1.0
                    if loc.replace("_", "-").upper() == "AZ":
                        w = 1.3
                    widths.append(w)
                widths.append(1.2)
                return widths
            widths = build_widths(locales)

            # Başlık satırı
            cols = st.columns(widths)
            cols[0].markdown("<div class='hc-cell hc-header'>Seç</div>", unsafe_allow_html=True)
            cols[1].markdown("<div class='hc-cell hc-header'>Başlık</div>", unsafe_allow_html=True)
            cols[2].markdown("<div class='hc-cell hc-spacer'></div>", unsafe_allow_html=True)
            for i, loc in enumerate(locales, start=3):
                cols[i].markdown(f"<div class='hc-cell hc-header hc-nowrap'>{pretty_locale(loc)}</div>", unsafe_allow_html=True)
            cols[-1].markdown("<div class='hc-cell hc-header'>Link</div>", unsafe_allow_html=True)

            # Satırlar
            for _, row in page_df.iterrows():
                rid = int(row["id"]); rtitle = row["title"]; rurl = row["html_url"]
                rcols = st.columns(widths)

                if rcols[0].button("Seç", key=f"sel-{rid}", on_click=clear_selection):
                    st.session_state["selected_article_id"] = rid

                fpx = title_font_px(str(rtitle))
                rcols[1].markdown(
                    f"<div class='hc-cell hc-title-left' style='font-size:{fpx}px'>{escape(str(rtitle))}</div>",
                    unsafe_allow_html=True
                )
                rcols[2].markdown("<div class='hc-cell hc-spacer'></div>", unsafe_allow_html=True)

                for j, loc in enumerate(locales, start=3):
                    raw = str(row[loc]); mark = "✅" if raw == "OK" else "❌"
                    rcols[j].markdown(f"<div class='hc-cell'>{mark}</div>", unsafe_allow_html=True)

                with rcols[-1]:
                    if rurl: st.link_button("Aç", rurl, use_container_width=True)
                    else:    st.markdown("<div class='hc-cell'>-</div>", unsafe_allow_html=True)

            # Pager
            def render_pager(cur: int, total: int):
                if total <= 0: return
                nums = list(range(1, total + 1))
                chunks = [nums[i:i+12] for i in range(0, len(nums), 12)]
                for idx, chunk in enumerate(chunks):
                    c = st.columns([0.7] + [1]*len(chunk) + [0.7])
                    if c[0].button("⏮️", key=f"pg_first_{idx}"):
                        clear_selection(); st.session_state["page"] = 1; st.rerun()
                    for k, p in enumerate(chunk, start=1):
                        def go(p=p):
                            clear_selection(); st.session_state["page"] = p
                        c[k].button(f"{p}", key=f"pg_{idx}_{p}", disabled=(p==cur), on_click=go)
                    if c[-1].button("⏭️", key=f"pg_last_{idx}"):
                        clear_selection(); st.session_state["page"] = total; st.rerun()
            render_pager(cur_page, total_pages)

        # Seçilen makaleyi düzenle
        selected_article_id = st.session_state.get("selected_article_id")
        if selected_article_id:
            st.markdown("<hr/>", unsafe_allow_html=True)

            try:
                a = ZendeskClient(ACC["subdomain"], ACC["email"], ACC["api_token"]).with_brand(brand_sub).get_article(int(selected_article_id)).get("article", {})
            except Exception as e:
                st.error(f"Makale yüklenemedi: {e}"); st.stop()

            article_title_text = escape(a.get("title") or "(Başlıksız)")
            st.markdown(f"<div class='section-title'>📝 {article_title_text}</div>", unsafe_allow_html=True)

            link_url = a.get("html_url") or a.get("url")
            if link_url:
                st.link_button("Zendesk’te Aç", link_url, use_container_width=False)

            st.write(f"Durum: **{'Taslak' if a.get('draft') else 'Yayında'}**")

            if "locales_cache" not in st.session_state:
                locales, default_locale = get_locales(ACC["subdomain"], ACC["email"], ACC["api_token"], brand_sub)
                st.session_state["locales_cache"] = reorder_locales_tr_first(locales)
            locales = st.session_state["locales_cache"]

            live_client = ZendeskClient(ACC["subdomain"], ACC["email"], ACC["api_token"]).with_brand(brand_sub)
            trans = live_client.get_article_translations(a["id"])
            by_locale = {t.get("locale"): t for t in trans}

            st.markdown("<strong>Kaydetme seçenekleri</strong>", unsafe_allow_html=True)
            colA, colB, colC = st.columns([1,1,1])
            with colA:
                publish_translations_single = st.checkbox("Çevirileri Yayınla!", True)
            with colB:
                publish_article_single = st.checkbox("Türkçe'yi Yayınla!", True)
            with colC:
                if st.button("❌ Seçimi Kapat"):
                    clear_selection(); st.rerun()

            st.markdown("<hr/>", unsafe_allow_html=True)
            st.markdown("<div class='section-title' style='font-size:1.1rem'>Çeviriler</div>", unsafe_allow_html=True)
            tabs = st.tabs([pretty_locale(l) for l in locales])
            inputs: Dict[str, Dict[str, Any]] = {}
            for i, loc in enumerate(locales):
                with tabs[i]:
                    existing = by_locale.get(loc)
                    t_title = st.text_input("Başlık", value=(existing.get("title") if existing else ""), key=f"title-{a['id']}-{loc}")
                    html_content = st_quill(html=True, value=(existing.get("body") if existing else "") or "",
                                            placeholder="İçeriği buraya yazın…", key=f"quill-{a['id']}-{loc}")
                    inputs[loc] = {"title": (t_title or "").strip(),
                                   "body": (html_content or "").strip(),
                                   "exists": bool(existing)}

            st.markdown("<hr/>", unsafe_allow_html=True)
            if st.button("💾 Kaydet ve Yayınla!", type="primary"):
                errors, successes = [], []
                for loc, data in inputs.items():
                    if not data["title"] and not data["body"]:
                        continue
                    try:
                        if data["exists"]:
                            live_client.update_translation(a["id"], loc, data["title"], data["body"],
                                                           draft=not publish_translations_single)
                        else:
                            live_client.create_translation(a["id"], loc, data["title"], data["body"],
                                                           draft=not publish_translations_single)
                        successes.append(pretty_locale(loc))
                    except Exception as e:
                        errors.append(f"{pretty_locale(loc)} → {e}")
                if publish_article_single:
                    try:
                        live_client.update_article(a["id"], draft=False)
                    except Exception as e:
                        errors.append(f"Makale publish → {e}")
                if successes: st.success(f"Kaydedildi: {', '.join(successes)}")
                if errors: st.error("Hatalar:\n- " + "\n- ".join(errors))
                if not successes and not errors: st.info("Kaydedilecek değişiklik bulunamadı.")

    # =============== 📄 Excel (sidebar yerine ana sekme) ===============
    with tab_excel:
        if not st.session_state.get("scan"):
            st.info("Önce **Ayarlar** sekmesinden tarama yapın.")
        else:
            live_client = ZendeskClient(ACC["subdomain"], ACC["email"], ACC["api_token"]).with_brand(brand_sub)

            def build_export_rows(article_ids: List[int], locales: List[str]) -> pd.DataFrame:
                rows: List[Dict[str, Any]] = []
                for a_id in article_ids:
                    art = live_client.get_article(int(a_id)).get("article", {})
                    art_title = art.get("title") or art.get("name") or "(untitled)"
                    url = art.get("html_url") or art.get("url")

                    translations = live_client.get_article_translations(a_id)
                    by_loc = {t.get("locale"): t for t in translations}
                    missing = set(live_client.get_article_missing_locales(a_id))
                    outdated = set(live_client.get_article_outdated_locales(a_id))

                    for loc in st.session_state.get("locales_cache", []):
                        state = "OK"
                        if loc in missing: state = "MISSING"
                        elif loc in outdated: state = "OUTDATED"
                        t = by_loc.get(loc) or {}
                        rows.append({
                            "article_id": a_id,
                            "article_title": art_title,
                            "locale": loc,
                            "status": state,
                            "title": t.get("title") or "",
                            "body": t.get("body") or "",
                            "url": url
                        })
                return pd.DataFrame(rows)

            # df: en son tarama çıktısı
            export_ids = []
            if "page" in st.session_state:
                # tarama yapıldıysa, tabloyu tekrar hesaplamaya gerek kalmadan IDs çekelim
                try:
                    # Güvenli tekrar oluşturma:
                    articles = get_articles(ACC["subdomain"], ACC["email"], ACC["api_token"], brand_sub, PER_PAGE, MAX_PAGES)
                    export_ids = [a.get("id") for a in articles]
                except Exception:
                    export_ids = []

            st.markdown("<div class='section-title' style='font-size:1.1rem'>Dışa Aktar</div>", unsafe_allow_html=True)
            if st.button("📥 XLSX oluştur", on_click=clear_selection):
                with st.spinner("Excel hazırlanıyor..."):
                    locales_cache = st.session_state.get("locales_cache", [])
                    trans_df = build_export_rows(export_ids, locales_cache)
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        info = pd.DataFrame({
                            "field": ["brand_subdomain", "default_locale", "locales_csv", "how_to"],
                            "value": [brand_sub, None, ",".join(locales_cache),
                                      "Translations sayfasını düzenleyin. 'title' ve/veya 'body' dolu satırlar upsert edilir."]
                        })
                        info.to_excel(writer, index=False, sheet_name="Info")
                        # Özet liste (id, title, url) — tarama yapılmışsa
                        try:
                            articles = get_articles(ACC["subdomain"], ACC["email"], ACC["api_token"], brand_sub, PER_PAGE, MAX_PAGES)
                            pd.DataFrame([{
                                "id": a.get("id"), "title": a.get("title") or a.get("name") or "(untitled)",
                                "html_url": a.get("html_url") or a.get("url")
                            } for a in articles]).to_excel(writer, index=False, sheet_name="Articles")
                        except Exception:
                            pass
                        trans_df.to_excel(writer, index=False, sheet_name="Translations")
                    st.download_button("⬇️ Excel'i indir", data=output.getvalue(),
                                       file_name=f"hc_translations_{brand_sub}.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            st.markdown("<div class='section-title' style='font-size:1.1rem'>İçe Aktar</div>", unsafe_allow_html=True)
            upl = st.file_uploader("XLSX dosya yükle", type=["xlsx"], key="xlsx_upload_main")
            c1, c2 = st.columns(2)
            with c1:
                publish_translations = st.checkbox("Çevirileri Yayınla", True, key="import_publish_trans_main")
            with c2:
                publish_articles = st.checkbox("Türkçe Yayınla", True, key="import_publish_articles_main")

            if upl is not None:
                try:
                    xls = pd.ExcelFile(upl)
                except Exception as e:
                    st.error(f"Excel okunamadı: {e}")
                else:
                    if "Translations" not in xls.sheet_names:
                        st.error("Excel'de 'Translations' sayfası yok.")
                    else:
                        trans_df = pd.read_excel(xls, sheet_name="Translations")
                        required_cols = {"article_id", "locale", "title", "body"}
                        if not required_cols.issubset(set(trans_df.columns)):
                            st.error(f"Gerekli kolonlar: {', '.join(sorted(required_cols))}")
                        else:
                            candidates = trans_df[(trans_df["title"].fillna("").astype(str).str.strip() != "") |
                                                  (trans_df["body"].fillna("").astype(str).str.strip() != "")]
                            st.info(f"İşlenecek satır: {len(candidates)}")
                            if st.button("🚀 İçe aktarımı başlat", type="primary", key="run_import_main", on_click=clear_selection):
                                errors, successes = [], []
                                live_client = ZendeskClient(ACC["subdomain"], ACC["email"], ACC["api_token"]).with_brand(brand_sub)
                                cached_trans: Dict[int, Dict[str, Dict[str, Any]]] = {}
                                for _, row in candidates.iterrows():
                                    try:
                                        a_id = int(row["article_id"])
                                        loc = str(row["locale"]).strip()
                                        title_val = "" if pd.isna(row["title"]) else str(row["title"])
                                        body_val  = "" if pd.isna(row["body"])  else str(row["body"])
                                        if not loc: continue
                                        if a_id not in cached_trans:
                                            cur = live_client.get_article_translations(a_id)
                                            cached_trans[a_id] = {t.get("locale"): t for t in cur}
                                        exists = loc in cached_trans[a_id]
                                        if exists:
                                            live_client.update_translation(a_id, loc, title_val, body_val,
                                                                           draft=not publish_translations)
                                        else:
                                            live_client.create_translation(a_id, loc, title_val, body_val,
                                                                           draft=not publish_translations)
                                        successes.append(f"{a_id}:{loc}")
                                    except Exception as e:
                                        errors.append(f"{row.get('article_id')}:{row.get('locale')} → {e}")
                                if publish_articles:
                                    for a_id in set(candidates["article_id"].astype(int).tolist()):
                                        try:
                                            live_client.update_article(int(a_id), draft=False)
                                        except Exception as e:
                                            errors.append(f"{a_id} publish → {e}")
                                if successes:
                                    st.success(f"Başarılı: {len(successes)} satır (örnek: {', '.join(successes[:10])}{'...' if len(successes)>10 else ''})")
                                if errors:
                                    st.error("Hatalar:\n- " + "\n- ".join(errors[:50]) + ("\n... (kısaltıldı)" if len(errors) > 50 else ""))


# --- wrapper (embed uyumlu) ---
def run(embedded: bool = False):
    if not embedded:
        try:
            st.set_page_config(page_title="Zendesk Help Center Çeviri", layout="wide")
        except Exception:
            pass
    render_ui()

if __name__ == "__main__":
    run(False)
