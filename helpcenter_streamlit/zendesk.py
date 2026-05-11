# zendesk.py (hızlı sürüm)
import time, base64, json, requests, random
from typing import Dict, Any, List, Optional, Tuple, Generator
from concurrent.futures import ThreadPoolExecutor, as_completed

class ZendeskClient:
    def __init__(self, subdomain: str, email: str, api_token: str, timeout: int = 20):
        self.base = f"https://{subdomain}.zendesk.com"
        token = base64.b64encode(f"{email}/token:{api_token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
        self.timeout = timeout

        # Tek bir session: keep-alive + connection pool
        self.sess = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0)
        self.sess.mount("https://", adapter)
        self.sess.mount("http://", adapter)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = path if path.startswith("http") else self.base + path
        backoff = 1.0
        while True:
            resp = self.sess.request(method, url, headers=self.headers,
                                     data=json.dumps(payload) if payload else None,
                                     timeout=self.timeout)
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                wait = (int(ra) if ra and ra.isdigit() else backoff) + random.uniform(0, 0.5)
                time.sleep(wait)
                backoff = min(backoff * 2, 10)
                continue
            if not resp.ok:
                try:
                    data = resp.json()
                    msg = data.get("error") or data.get("description") or resp.text
                except Exception:
                    msg = resp.text
                raise RuntimeError(f"{resp.status_code} {resp.reason}: {msg}")
            try:
                return resp.json()
            except Exception:
                return {}

    # ------------ ACCOUNT-LEVEL (markalar) ----------------
    def list_brands(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/api/v2/brands")
        return data.get("brands", [])

    # ------------ BRAND-LEVEL (Help Center) ----------------
    def with_brand(self, brand_subdomain: str) -> "ZendeskClient":
        z = ZendeskClient.__new__(ZendeskClient)
        z.base = f"https://{brand_subdomain}.zendesk.com"
        z.headers = self.headers
        z.timeout = self.timeout
        z.sess = self.sess  # aynı session/pool
        return z

    def get_help_center_locales(self) -> Tuple[List[str], Optional[str]]:
        d = self._request("GET", "/api/v2/help_center/locales")
        locales = d.get("locales", []) or d.get("enabled_locales", [])
        default_locale = d.get("default_locale") or d.get("default")
        return locales, default_locale

    def list_articles_paginated(self, per_page: int = 100, max_pages: int = 1000) -> Generator[Dict[str, Any], None, None]:
        path = f"/api/v2/help_center/articles.json?per_page={per_page}"
        pages = 0
        while path and pages < max_pages:
            data = self._request("GET", path)
            for a in data.get("articles", []):
                yield a
            next_page = data.get("next_page")
            path = next_page.replace(self.base, "") if next_page else None
            pages += 1

    def get_article(self, article_id: int) -> Dict[str, Any]:
        return self._request("GET", f"/api/v2/help_center/articles/{article_id}.json")

    def get_article_translations(self, article_id: int) -> List[Dict[str, Any]]:
        d = self._request("GET", f"/api/v2/help_center/articles/{article_id}/translations.json")
        return d.get("translations", [])

    def get_article_missing_locales(self, article_id: int) -> List[str]:
        d = self._request("GET", f"/api/v2/help_center/articles/{article_id}/translations/missing")
        return d.get("locales", [])

    def get_article_outdated_locales(self, article_id: int) -> List[str]:
        d = self._request("GET", f"/api/v2/help_center/articles/{article_id}/translations?outdated=true")
        return [t.get("locale") for t in d.get("translations", []) if t.get("locale")]

    def create_translation(self, article_id: int, locale: str, title: str, body: str, draft: bool = True) -> Dict[str, Any]:
        payload = {"translation": {"locale": locale, "title": title, "body": body, "draft": draft}}
        return self._request("POST", f"/api/v2/help_center/articles/{article_id}/translations.json", payload)

    def update_translation(self, article_id: int, locale: str, title: str, body: str, draft: bool = True) -> Dict[str, Any]:
        payload = {"translation": {"title": title, "body": body, "draft": draft}}
        return self._request("PUT", f"/api/v2/help_center/articles/{article_id}/translations/{locale}.json", payload)

    def update_article(self, article_id: int, **fields) -> Dict[str, Any]:
        payload = {"article": fields}
        return self._request("PUT", f"/api/v2/help_center/articles/{article_id}.json", payload)

    # --------- YENİ: hızlı toplu durum çıkar (concurrent) ----------
    def bulk_status(self, article_ids: List[int], max_workers: int = 12) -> Dict[int, Dict[str, Any]]:
        """
        Her makale için: missing locales, outdated locales.
        Eşzamanlı çalışır ve bağlantıyı yeniden kullanır.
        """
        results: Dict[int, Dict[str, Any]] = {}

        def job_missing(aid: int):
            return aid, "missing", self.get_article_missing_locales(aid)

        def job_outdated(aid: int):
            return aid, "outdated", self.get_article_outdated_locales(aid)

        tasks = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for aid in article_ids:
                tasks.append(ex.submit(job_missing, aid))
                tasks.append(ex.submit(job_outdated, aid))
            for fut in as_completed(tasks):
                aid, kind, data = fut.result()
                slot = results.setdefault(aid, {"missing": [], "outdated": []})
                slot[kind] = data
        return results
