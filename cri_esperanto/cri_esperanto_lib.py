from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta
from typing import Iterable, List, Optional, Dict, Tuple
from urllib.parse import urlencode, urlparse, quote, urlunparse, urljoin

import requests
from bs4 import BeautifulSoup

from .nuxt_payload import decode_payload


log = logging.getLogger(__name__)


@dataclass
class Article:
    url: str
    title: str
    published: Optional[datetime]
    content_text: str
    author: Optional[str] = None
    categories: Optional[List[str]] = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "url": self.url,
                "title": self.title,
                "published": self.published.isoformat() if self.published else None,
                "content_text": self.content_text,
                "author": self.author,
                "categories": self.categories or [],
            },
            ensure_ascii=False,
        )


@dataclass
class CRIConfig:
    base_url: str = "https://esperanto.cri.cn"
    # 2010-01-01 以降
    start_date: date = date(2010, 1, 1)
    end_date: date = date.today()
    throttle_sec: float = 0.5
    timeout_sec: int = 30
    max_workers: int = 16
    # 検索APIの推定チャネル（エスペラント）
    channel_id: str = "CHAL1723113653432123"


def _session(cfg: CRIConfig) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; CRICollector/1.0; +https://esperanto.cri.cn)",
        }
    )
    return s


def _to_datetime_ms(ms: Optional[str | int]) -> Optional[datetime]:
    if ms is None:
        return None
    try:
        ms_int = int(ms)
        # 13-digit millis since epoch
        if ms_int > 10_000_000_000:
            return datetime.utcfromtimestamp(ms_int / 1000)
        # seconds
        return datetime.utcfromtimestamp(ms_int)
    except Exception:
        return None


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    # 余計な要素の除去（広告・ナビなどは記事詳細には少ないが念のため）
    for bad in soup.select("script, style, nav, header, footer, aside, noscript, form, iframe"):
        bad.decompose()
    txt = soup.get_text("\n")
    # 連続改行の整理
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt


def _extract_links_from_listing_payload(payload_obj: Dict) -> List[str]:
    links: List[str] = []
    try:
        result = payload_obj["data"]["w30cgFITTF"]["result"]
        modules = result.get("modules", [])
        for m in modules:
            if not isinstance(m, dict):
                continue
            if "cardgroups" not in m:
                continue
            for cg in m.get("cardgroups", []):
                cg = cg or {}
                cgrp = (cg.get("cardgroup") or {})
                for c in cgrp.get("cards", []):
                    card = c.get("card") or {}
                    link = card.get("link")
                    if isinstance(link, str) and link.startswith("https://esperanto.cri.cn/"):
                        links.append(link)
    except Exception:
        pass
    # 重複除去
    uniq = []
    seen = set()
    for u in links:
        if u not in seen:
            uniq.append(u)
            seen.add(u)
    return uniq


def collect_urls_via_query_payload(cfg: CRIConfig, *, section_path: str = "/aktualajo/page.shtml") -> List[str]:
    """
    Nuxt の `_payload.json?path=<encoded>` を使い、ページ番号付きで列挙を試みる。
    サーバ実装上、クエリが無視される場合もあるため、無限には回さず早期停止の安全策を入れる。
    """
    s = _session(cfg)
    base = cfg.base_url.rstrip("/")
    all_links: List[str] = []
    stagnant_rounds = 0
    max_rounds = 50  # 安全上限
    for p in range(1, max_rounds + 1):
        qpath = f"{section_path}?page={p}"
        url = f"{base}/_payload.json?path={quote(qpath, safe='') }"
        try:
            r = s.get(url, headers={"accept": "application/json"}, timeout=cfg.timeout_sec)
            if r.status_code != 200:
                log.debug("payload listing status=%s url=%s", r.status_code, url)
                break
            payload = r.json()
            obj = decode_payload(payload)
            links = _extract_links_from_listing_payload(obj)
            # 新規数
            new_links = [u for u in links if u not in all_links]
            if not new_links:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
                all_links.extend(new_links)
            # 3ラウンド連続で増えなければ終了
            if stagnant_rounds >= 3:
                break
            time.sleep(cfg.throttle_sec)
        except Exception as e:
            log.debug("listing error: %s", e)
            break
    return all_links


def collect_urls_via_latest_sitemap(cfg: CRIConfig, limit: int = 500) -> List[str]:
    """
    最新サイトマップ（増分）から直近URLを収集。全期間は賄えないため補助用途。
    """
    s = _session(cfg)
    url = f"{cfg.base_url.rstrip('/')}/sitemap/latest_sitemap.xml"
    out: List[str] = []
    try:
        r = s.get(url, timeout=cfg.timeout_sec)
        if r.status_code != 200:
            return out
        soup = BeautifulSoup(r.text, "xml")
        for loc in soup.select("url > loc"):
            u = (loc.text or "").strip()
            if u.startswith("https://esperanto.cri.cn/"):
                out.append(u)
            if len(out) >= limit:
                break
    except Exception:
        pass
    # 重複排除
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            uniq.append(u)
            seen.add(u)
    return uniq


LEGACY_CDX_YEAR_MAX = 2020
LEGACY_CDX_LIMIT = 2000
LEGACY_NEWS_YEAR_MAX = 2020
LEGACY_NEWS_SNAPSHOTS_PER_YEAR = 24
LEGACY_NEWS_MAX_EXTRA_PAGES = 80
LEGACY_NEWS_MAX_DEPTH = 2


def _normalize_legacy_url(original: str) -> Optional[str]:
    try:
        parsed = urlparse(original)
        if not parsed.path.lower().endswith(".htm"):
            return None
        path = parsed.path
        # drop :80
        host = parsed.hostname or "esperanto.cri.cn"
        return urlunparse(("https", host, path, "", "", ""))
    except Exception:
        return None


def _build_legacy_http_url(href: str) -> Optional[str]:
    if not href or href.startswith("javascript"):
        return None
    href = href.strip()
    if href.startswith("/web/"):
        parts = href.split("/", 3)
        if len(parts) == 4 and parts[3].startswith("http"):
            href = parts[3]
    if href.startswith("https://web.archive.org/web/") and "http" in href.split("/web/")[-1]:
        target = href.split("/web/")[-1]
        idx = target.find("http")
        if idx != -1:
            href = target[idx:]
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if not href.startswith("/"):
        href = "/" + href
    return f"http://esperanto.cri.cn{href}"


def _build_archived_url(timestamp: str, url: str) -> str:
    return f"https://web.archive.org/web/{timestamp}/{url}"


def _collect_links_from_snapshot(
    session: requests.Session,
    cfg: CRIConfig,
    timestamp: str,
    html: str,
) -> List[str]:
    collected: List[str] = []
    queue: deque[Tuple[str, str, int]] = deque(
        [(_build_archived_url(timestamp, "http://esperanto.cri.cn/news.htm"), html, 0)]
    )
    visited = set()
    while queue and len(visited) < LEGACY_NEWS_MAX_EXTRA_PAGES:
        page_url, content, depth = queue.popleft()
        if page_url in visited:
            continue
        visited.add(page_url)
        soup = BeautifulSoup(content, "lxml")
        for a in soup.find_all("a", href=True):
            raw = (a.get("href") or "").split("#")[0].strip()
            http_url = _build_legacy_http_url(raw)
            if not http_url:
                continue
            norm = _normalize_legacy_url(http_url)
            if norm and _is_legacy_url(norm):
                d = _extract_date_from_url(norm)
                if d and cfg.start_date <= d <= cfg.end_date and norm not in collected:
                    collected.append(norm)
                continue
            if depth >= LEGACY_NEWS_MAX_DEPTH:
                continue
            if norm and LEGACY_MORE_LINK_RE.match(norm):
                archived = _build_archived_url(timestamp, http_url)
                if archived in visited:
                    continue
                try:
                    resp = session.get(archived, timeout=cfg.timeout_sec)
                    if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                        queue.append((archived, resp.text, depth + 1))
                except Exception:
                    continue
        time.sleep(cfg.throttle_sec)
    return collected


def collect_urls_via_cdx(cfg: CRIConfig) -> List[str]:
    """
    Wayback Machine の CDX API を利用して、旧プラットフォーム(.htm)の記事URLを列挙。
    """
    start_year = cfg.start_date.year
    if start_year > LEGACY_CDX_YEAR_MAX:
        return []
    end_year = min(cfg.end_date.year, LEGACY_CDX_YEAR_MAX)
    if end_year < start_year:
        return []

    session = _session(cfg)
    urls: List[str] = []
    base_params = [
        ("output", "json"),
        ("filter", "statuscode:200"),
        ("filter", "mimetype:text/html"),
        ("filter", r"original:.*[0-9]{4}/[0-9]{2}/[0-9]{2}/.*\\.htm"),
        ("collapse", "digest"),
        ("limit", str(LEGACY_CDX_LIMIT)),
        ("showResumeKey", "true"),
    ]

    for year in range(start_year, end_year + 1):
        resume_key = None
        while True:
            params = [
                ("url", "esperanto.cri.cn/*"),
                ("from", str(year)),
                ("to", str(year)),
            ]
            params.extend(base_params)
            if resume_key:
                params.append(("resumeKey", resume_key))
            try:
                resp = session.get("https://web.archive.org/cdx/search/cdx", params=params, timeout=60)
                if resp.status_code != 200:
                    log.debug("cdx status=%s year=%s", resp.status_code, year)
                    break
                data = resp.json()
            except Exception as e:
                log.debug("cdx error year=%s: %s", year, e)
                break
            if len(data) <= 1:
                break
            resume_key = None
            for row in data[1:]:
                if not row:
                    continue
                if len(row) == 1:
                    resume_key = row[0] or None
                    continue
                if len(row) < 3:
                    continue
                original = row[2]
                if not isinstance(original, str):
                    continue
                norm = _normalize_legacy_url(original)
                if not norm:
                    continue
                m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", norm)
                if not m:
                    continue
                y, mo, da = map(int, m.groups())
                try:
                    d = date(y, mo, da)
                except ValueError:
                    continue
                if d < cfg.start_date or d > cfg.end_date:
                    continue
                urls.append(norm)
            if not resume_key:
                break
            time.sleep(cfg.throttle_sec)
    return urls


def _list_news_snapshots(year: int, session: requests.Session) -> List[str]:
    """
    Returns Wayback timestamps for news.htm for a given year.
    """
    params = [
        ("url", "esperanto.cri.cn/news.htm"),
        ("from", str(year)),
        ("to", str(year)),
        ("output", "json"),
        ("filter", "statuscode:200"),
        ("limit", str(LEGACY_NEWS_SNAPSHOTS_PER_YEAR * 5)),
    ]
    try:
        resp = session.get("https://web.archive.org/cdx/search/cdx", params=params, timeout=60)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []
    timestamps = []
    seen = set()
    for row in data[1:]:
        if len(row) >= 2:
            ts = row[1][:14]
            if ts not in seen:
                seen.add(ts)
                timestamps.append(ts)
        if len(timestamps) >= LEGACY_NEWS_SNAPSHOTS_PER_YEAR:
            break
    return timestamps


def collect_urls_via_news_snapshots(cfg: CRIConfig) -> List[str]:
    """
    Use archived `news.htm` snapshots to recover historic article URLs.
    """
    if cfg.start_date.year > LEGACY_NEWS_YEAR_MAX:
        return []
    end_year = min(cfg.end_date.year, LEGACY_NEWS_YEAR_MAX)
    session = _session(cfg)
    urls: List[str] = []

    for year in range(cfg.start_date.year, end_year + 1):
        for ts in _list_news_snapshots(year, session):
            snapshot_url = f"https://web.archive.org/web/{ts}/http://esperanto.cri.cn/news.htm"
            try:
                resp = session.get(snapshot_url, timeout=cfg.timeout_sec)
                if resp.status_code != 200:
                    continue
                links = _collect_links_from_snapshot(session, cfg, ts, resp.text)
                for link in links:
                    if link not in urls:
                        urls.append(link)
            except Exception:
                continue
            time.sleep(cfg.throttle_sec)
    return urls


def collect_urls_via_listing_html(cfg: CRIConfig, *, section_path: str) -> List[str]:
    """
    NuxtのHTMLを直接パースし、`/YYYY/MM/DD/ARTI...` へのリンクを抽出する後方互換のフォールバック。
    `_payload.json?path=` が深く遡れない場合に備えて、ページ番号を伸ばしていく。
    """
    s = _session(cfg)
    base = cfg.base_url.rstrip("/")
    links: List[str] = []
    seen = set()
    stagnant = 0
    earliest_year = None
    max_pages = 2000  # 安全上限（十分大きく）
    pat = re.compile(r"https://esperanto\.cri\.cn/\d{4}/\d{2}/\d{2}/ARTI[\w-]+")

    for p in range(1, max_pages + 1):
        url = f"{base}{section_path}?page={p}"
        try:
            r = s.get(url, timeout=cfg.timeout_sec)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "lxml")
            page_links = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if isinstance(href, str):
                    # 絶対URL化
                    if href.startswith("/"):
                        href = base + href
                    if pat.match(href):
                        page_links.add(href)
            # 新規の追加
            new_count = 0
            for u in sorted(page_links):
                if u not in seen:
                    seen.add(u)
                    links.append(u)
                    m = re.search(r"/(\d{4})/\d{2}/\d{2}/ARTI", u)
                    if m:
                        y = int(m.group(1))
                        earliest_year = y if earliest_year is None else min(earliest_year, y)
                    new_count += 1
            if new_count == 0:
                stagnant += 1
            else:
                stagnant = 0
            # 開始年まで届いた／3連続で増えない→終了
            if (earliest_year is not None and earliest_year <= cfg.start_date.year) or stagnant >= 3:
                break
            time.sleep(cfg.throttle_sec)
        except Exception:
            break
    return links


def _min_date_in_cards(payload_obj: Dict) -> Optional[datetime]:
    mind: Optional[int] = None
    try:
        result = payload_obj["data"]["w30cgFITTF"]["result"]
        modules = result.get("modules", [])
        for m in modules:
            if "cardgroups" not in m:
                continue
            for cg in m.get("cardgroups", []):
                cards = (cg.get("cardgroup") or {}).get("cards", [])
                for c in cards:
                    d = (c.get("card") or {}).get("date")
                    try:
                        di = int(d)
                    except Exception:
                        continue
                    if di and (mind is None or di < mind):
                        mind = di
    except Exception:
        pass
    return _to_datetime_ms(mind) if mind is not None else None


def _canonicalize_modern_url(url: str) -> str:
    """Standardise CGTN / CRI host variants to https://esperanto.cri.cn."""
    if not url:
        return url
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith("cgtn.com"):
        host = host.replace("cgtn.com", "cri.cn")
    scheme = "https"
    return f"{scheme}://{host}{parsed.path}"


def collect_urls_via_search_payload(cfg: CRIConfig) -> List[str]:
    """
    CGTN検索API（pcmobileinf）を叩いて最新記事を列挙する。
    公式フロントエンドが使用している endpoint を再利用する。
    """
    api_url = "https://38apicdn.cgtn.com/pcmobileinf/rest/layout/search"
    s = _session(cfg)
    links: List[str] = []
    page = 1
    page_size = 50
    total_pages = None

    while True:
        payload = {
            "keyword": "",
            "type": "all",
            "channel": cfg.channel_id,
            "paging": {
                "pageNo": page,
                "pageSize": str(page_size),
                "orderBy": "date",
            },
        }
        try:
            resp = s.post(api_url, data={"json": json.dumps(payload)}, timeout=cfg.timeout_sec)
            if resp.status_code != 200:
                log.debug("cgtn search status=%s page=%s", resp.status_code, page)
                break
            data = resp.json()
            cardgroups = data.get("cardgroups") or []
            cards: List[Dict] = []
            if cardgroups:
                cards = (cardgroups[0].get("cardgroup") or {}).get("cards", [])
            page_links = []
            for c in cards:
                link = (c.get("card") or {}).get("link")
                if isinstance(link, str) and "/20" in link:
                    page_links.append(_canonicalize_modern_url(link))
            new_links = [u for u in page_links if u not in links]
            if not new_links:
                break
            links.extend(new_links)

            paged = data.get("paged") or {}
            count = paged.get("count")
            if total_pages is None and isinstance(count, int) and count > 0:
                total_pages = min(math.ceil(count / page_size), 400)

            page += 1
            if total_pages and page > total_pages:
                break
            if paged.get("more") != 1:
                break
            time.sleep(cfg.throttle_sec)
        except Exception as e:
            log.debug("cgtn search error: %s", e)
            break
    return links


MODERN_URL_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/ARTI", re.IGNORECASE)
DATE_IN_PATH_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")


def _extract_date_from_url(url: str) -> Optional[date]:
    m = DATE_IN_PATH_RE.search(url)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def collect_urls(cfg: CRIConfig) -> List[str]:
    """
    URL収集エントリポイント。まずはカテゴリの `_payload.json?path=...` でヒットを集め、
    直近はサイトマップで補完する。将来、検索APIが特定できればここに追加する。
    """
    links: List[str] = []
    # 検索（最広カバレッジ）
    if cfg.end_date.year >= 2020:
        links.extend(collect_urls_via_search_payload(cfg))
    # 代表的なセクションを順に列挙（存在しない場合は静かにスキップ）
    for section in [
        "/aktualajo/page.shtml",
        "/eklubo/page.shtml",
        "/shanny/page.shtml",
        "/LuciaStudio/page.shtml",
        "/pliajlingvoj/page.shtml",
    ]:
        # payload経由（速い）
        links.extend(collect_urls_via_query_payload(cfg, section_path=section))
        # HTMLフォールバック（深く遡る）
        links.extend(collect_urls_via_listing_html(cfg, section_path=section))
    # トップのnewsモジュール（/news 相当）は静的に差し替えられることがあるため一旦保留
    # 直近の補完
    if cfg.end_date.year >= 2023:
        links.extend(collect_urls_via_latest_sitemap(cfg, limit=500))
    # レガシー（2010-2018）アーカイブ
    links.extend(collect_urls_via_cdx(cfg))
    links.extend(collect_urls_via_news_snapshots(cfg))
    # 整理
    seen = set()
    uniq: List[str] = []
    for u in links:
        if u in seen:
            continue
        if MODERN_URL_RE.search(u) or _is_legacy_url(u):
            d = _extract_date_from_url(u)
            if d and (cfg.start_date <= d <= cfg.end_date):
                uniq.append(u)
                seen.add(u)
    return uniq


LEGACY_URL_RE = re.compile(r"https://esperanto\.cri\.cn/\d+/\d{4}/\d{2}/\d{2}/[^/]+\.htm", re.IGNORECASE)
LEGACY_MORE_LINK_RE = re.compile(r"https://esperanto\.cri\.cn/\d+/.+/more\d+\.htm", re.IGNORECASE)


def _is_legacy_url(url: str) -> bool:
    return bool(LEGACY_URL_RE.match(url))


def _fetch_modern_article(cfg: CRIConfig, url: str) -> Optional[Article]:
    s = _session(cfg)
    # 記事詳細は `/YYYY/MM/DD/ARTI...` 形式： 末尾に `/_payload.json` を付与
    detail_payload = url.rstrip("/") + "/_payload.json"
    try:
        r = s.get(detail_payload, headers={"accept": "application/json"}, timeout=cfg.timeout_sec)
        if r.status_code != 200:
            log.debug("detail status=%s %s", r.status_code, detail_payload)
            return None
        payload = r.json()
        obj = decode_payload(payload)
        result = obj["data"]["w30cgFITTF"]["result"]
        title = (result.get("title") or "").strip()
        published = _to_datetime_ms(result.get("published"))
        content_html = None
        # ShijieyuDetail25 モジュール配下に content がいることが多い
        for m in result.get("modules", []):
            # 探索
            stack = [m]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    if "content" in cur and isinstance(cur["content"], str) and len(cur["content"]) > 30:
                        content_html = cur["content"]
                        stack.clear()
                        break
                    for v in cur.values():
                        stack.append(v)
                elif isinstance(cur, list):
                    stack.extend(cur)
            if content_html:
                break
        if not content_html:
            # どうしても見つからなければ空本文で返す（後続で再取得可能）
            content_html = ""
        content_text = _html_to_text(content_html)
        return Article(url=url, title=title or url, published=published, content_text=content_text)
    except Exception as e:
        log.debug("detail error: %s %s", e, url)
        return None


def _extract_text(element: Optional[BeautifulSoup]) -> str:
    if not element:
        return ""
    txt = element.get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def _parse_legacy_datetime(url: str, soup: BeautifulSoup) -> datetime:
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
    year, month, day = 2010, 1, 1
    if m:
        year, month, day = map(int, m.groups())
    dt = datetime(year, month, day)
    stamp = soup.find(string=re.compile(r"\d{4}-\d{2}-\d{2}"))
    if stamp:
        try:
            parts = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", stamp)
            if parts:
                dt = datetime.strptime(parts.group(1) + " " + parts.group(2), "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return dt


def _fetch_legacy_article(cfg: CRIConfig, url: str) -> Optional[Article]:
    s = _session(cfg)
    try:
        r = s.get(url, timeout=cfg.timeout_sec)
        if r.status_code != 200:
            log.debug("legacy detail status=%s %s", r.status_code, url)
            return None
        soup = BeautifulSoup(r.text, "lxml")
        h1s = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
        title = h1s[-1] if h1s else (soup.title.get_text(strip=True) if soup.title else url)
        content_div = soup.find("div", {"id": "ccontent"})
        if not content_div:
            # fallback to main container
            content_div = soup.find("div", {"class": "text"})
        content_text = _extract_text(content_div)
        if not content_text:
            return None
        published = _parse_legacy_datetime(url, soup)
        return Article(url=url, title=title, published=published, content_text=content_text)
    except Exception as e:
        log.debug("legacy detail error: %s %s", e, url)
        return None


def fetch_article(cfg: CRIConfig, url: str) -> Optional[Article]:
    """
    記事詳細の取得。新旧フォーマットを自動判別する。
    """
    if _is_legacy_url(url):
        return _fetch_legacy_article(cfg, url)
    return _fetch_modern_article(cfg, url)


def serialize_by_year(arts: Iterable[Article], out_dir: str = "output/cri_esperanto") -> Dict[int, str]:
    """
    年ごとに JSONL を出力。戻り値は {year: filepath}
    """
    import os

    os.makedirs(out_dir, exist_ok=True)
    files: Dict[int, str] = {}
    handles: Dict[int, object] = {}
    try:
        for a in arts:
            y = (a.published.date().year if a.published else datetime.utcnow().year)
            if y not in files:
                path = f"{out_dir}/{y}.jsonl"
                files[y] = path
                handles[y] = open(path, "a", encoding="utf-8")
            fh = handles[y]
            fh.write(a.to_json() + "\n")
    finally:
        for fh in handles.values():
            try:
                fh.close()
            except Exception:
                pass
    return files


def collect_and_dump(cfg: CRIConfig, *, out_dir: str = "output/cri_esperanto") -> Dict[int, str]:
    """
    URLを収集し、並列に本文取得→年別JSONLに保存。
    """
    urls = collect_urls(cfg)

    arts: List[Article] = []
    if not urls:
        log.warning("収集URLが空です。のちほど再試行してください。")
        return {}

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
        fut_map = {ex.submit(fetch_article, cfg, u): u for u in urls}
        for fut in as_completed(fut_map):
            art = fut.result()
            if art and art.content_text:
                arts.append(art)
            time.sleep(cfg.throttle_sec)

    return serialize_by_year(arts, out_dir=out_dir)
