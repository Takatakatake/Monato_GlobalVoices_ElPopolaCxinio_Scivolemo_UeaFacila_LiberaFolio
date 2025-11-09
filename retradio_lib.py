# -*- coding: utf-8 -*-
"""
retradio_lib.py
Pola Retradio (https://pola-retradio.org/) 記事収集の共通ライブラリ。

機能概要
- 期間指定（開始・終了日）に基づき、対象サイトの投稿 URL を収集
  - 収集方法は2系統：RSS/Feed と 月別アーカイブの HTML クロール
- 各記事ページから本文（エスペラント）を抽出し、メタデータとともに返す
- マークダウン/テキスト/CSV/JSONL へのエクスポート補助
- robots.txt の遵守と polite な遅延（throttle）

依存: requests, bs4, feedparser, dateparser, python-dateutil, tqdm (CLI 時), lxml(推奨)
"""
from __future__ import annotations

import re
import time
import math
import json
import csv
import os
import sys
import html
import logging
from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional, Dict, Tuple, Set, Callable
from urllib.parse import urljoin, urlparse, urlencode

# --- third-party ---
try:
    import requests_cache  # optional
    _HAS_REQUESTS_CACHE = True
except Exception:
    _HAS_REQUESTS_CACHE = False

import requests
from bs4 import BeautifulSoup
import feedparser
import dateparser
from dateutil import tz
from datetime import datetime, timedelta, date

__all__ = [
    "ScrapeConfig", "Article", "URLCollectionResult", "collect_urls",
    "collect_from_feed", "collect_from_archives", "collect_from_rest",
    "fetch_article", "export_all", "set_progress_callback"
]

USER_AGENT = "Mozilla/5.0 (compatible; PolaRetradioScraper/1.0; +https://pola-retradio.org)"

MONTHS_EO = ["januaro","februaro","marto","aprilo","majo","junio","julio","aŭgusto","septembro","oktobro","novembro","decembro"]
SOURCE_PRIORITY = {"rest": 3, "feed": 2, "archive": 1}

_PROGRESS_CB: Optional[Callable[[str], None]] = None

@dataclass
class ScrapeConfig:
    base_url: str = "https://pola-retradio.org"
    start_date: date = date.today() - timedelta(days=30)
    end_date: date = date.today()
    throttle_sec: float = 1.0
    max_pages: Optional[int] = None  # feedやアーカイブのページ送り最大数（Noneは制限なし）
    method: str = "auto"             # "feed" | "archive" | "both" | "rest" | "auto"
    categories: Optional[List[str]] = None  # 未使用（将来拡張）
    timezone: str = "Europe/Warsaw"  # 公開日時のタイムゾーン想定
    use_cache: bool = True           # requests-cache を使える場合は使用
    timeout_sec: int = 30            # HTTP タイムアウト
    max_retries: int = 3             # HTTP リトライ回数
    respect_robots: bool = True      # robots.txt の遵守（requestsでは変化なし／事前確認用途）
    include_audio_links: bool = False
    # 出力メタ情報のラベル（Markdown のヘッダ）
    # None の場合は対象サイトに応じて自動推定（既存の Pola Retradio 既定値を維持）
    source_label: Optional[str] = None
    # フィード URL をサイト既定から上書きしたい場合に指定
    feed_url_override: Optional[str] = None

    def normalize(self) -> None:
        if isinstance(self.start_date, datetime):
            self.start_date = self.start_date.date()
        if isinstance(self.end_date, datetime):
            self.end_date = self.end_date.date()
        if self.end_date < self.start_date:
            raise ValueError("end_date は start_date 以降である必要があります")
        self.method = self.method.lower()
        if self.method not in ("feed", "archive", "both", "rest", "auto"):
            raise ValueError("method は 'feed' | 'archive' | 'both' | 'rest' | 'auto' のいずれかです")


def set_progress_callback(func: Optional[Callable[[str], None]]) -> None:
    """スクレイプ進捗を通知するコールバックを登録する。"""
    global _PROGRESS_CB
    _PROGRESS_CB = func


def _progress(msg: str) -> None:
    if _PROGRESS_CB:
        try:
            _PROGRESS_CB(msg)
        except Exception:
            logging.getLogger(__name__).debug("progress callback failed", exc_info=True)


@dataclass
class Article:
    url: str
    title: str
    published: Optional[datetime]
    content_text: str
    author: Optional[str] = None
    categories: Optional[List[str]] = None
    audio_links: Optional[List[str]] = None

    def to_row(self) -> Dict[str, str]:
        return {
            "url": self.url,
            "title": self.title,
            "published": self.published.isoformat() if self.published else "",
            "author": self.author or "",
            "categories": ",".join(self.categories or []),
            "audio_links": ",".join(self.audio_links or []),
        }

@dataclass
class FeedEntryData:
    url: str
    title: Optional[str]
    published: Optional[datetime]
    author: Optional[str]
    categories: List[str]
    content_html: Optional[str]
    summary_html: Optional[str]


_FEED_ENTRY_CACHE: Dict[str, FeedEntryData] = {}
_FEED_DISCOVERY_CACHE: Dict[str, Optional[str]] = {}

@dataclass
class URLCollectionResult:
    urls: List[str]
    feed_initial: int
    archive_initial: int
    rest_initial: int
    feed_used: int
    archive_used: int
    rest_used: int
    duplicates_removed: int
    out_of_range_skipped: int
    earliest_date: Optional[date]
    latest_date: Optional[date]

    @property
    def total(self) -> int:
        return len(self.urls)

    def __iter__(self):
        return iter(self.urls)

    def __len__(self):
        return len(self.urls)

    def __getitem__(self, item):
        return self.urls[item]

def _session(cfg: ScrapeConfig) -> requests.Session:
    if _HAS_REQUESTS_CACHE and cfg.use_cache:
        s = requests_cache.CachedSession(
            cache_name="retradio_cache",
            backend="sqlite",
            expire_after=timedelta(hours=12),
        )
    else:
        s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _get(s: requests.Session, url: str, cfg: ScrapeConfig) -> requests.Response:
    last_exc = None
    for i in range(cfg.max_retries):
        try:
            resp = s.get(url, timeout=cfg.timeout_sec)
            if resp.status_code >= 500:
                time.sleep(min(cfg.throttle_sec * (i + 1), 5))
                continue
            return resp
        except Exception as e:
            last_exc = e
            time.sleep(min(cfg.throttle_sec * (i + 1), 5))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"GET 失敗: {url}")


def _parse_date_any(s: str) -> Optional[datetime]:
    """
    エスペラント（eo）・英語（en）・ポーランド語（pl）ほか、
    日付を "ほぼ何でも" 解析する。
    """
    s = s.strip()
    if not s:
        return None
    # まず数字だけのパターン ex) 15.10.2025, 2025-10-15 など
    m = re.search(r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})', s)
    if m:
        dd, mm, yyyy = m.groups()
        yyyy = int(yyyy) if len(yyyy) == 4 else int("20" + yyyy)
        try:
            return datetime(yyyy, int(mm), int(dd))
        except Exception:
            pass

    # エスペラントの月名に対応（例: Oktobro 15, 2025）
    # dateparser に eo/en/pl を渡して汎用解析
    try:
        dt = dateparser.parse(
            s,
            languages=["eo", "en", "pl", "de", "fr", "es", "it"],
            settings={"DATE_ORDER": "DMY"},
        )
        return dt
    except Exception:
        return None


def _extract_date_from_url_or_title(url: str, title: str) -> Optional[datetime]:
    # URLに /YYYY/MM/ が含まれていれば年月は確定
    pu = urlparse(url)
    parts = [p for p in pu.path.split("/") if p]
    yyyy = mm = dd = None
    for i, p in enumerate(parts):
        if re.fullmatch(r"\d{4}", p):
            yyyy = int(p)
            if i + 1 < len(parts) and re.fullmatch(r"\d{2}", parts[i+1]):
                mm = int(parts[i+1])
                # 次のセグメントやタイトルから日を推定
                m = re.search(r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})', title)
                if m:
                    dd = int(m.group(1))
                break
    if yyyy and mm:
        if not dd:
            # タイトルやスラッグに dd を含む場合（e_elsendo-el-la-15-10-2025 など）
            m = re.search(r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})', pu.path)
            if m and int(m.group(2)) == mm and int(m.group(3)) == yyyy:
                dd = int(m.group(1))
        try:
            return datetime(yyyy, mm, dd or 1)
        except Exception:
            pass
    # タイトル側からの推定
    dt = _parse_date_any(title)
    return dt


def _normalize_url(url: str) -> str:
    # WordPress の記事 URL では末尾スラッシュ有無のみが異なる場合がある
    if not url:
        return url
    normalized = url.rstrip("/")
    return normalized or url

def month_range(start_d: date, end_d: date) -> List[Tuple[int, int]]:
    out = []
    y, m = start_d.year, start_d.month
    while (y, m) <= (end_d.year, end_d.month):
        out.append((y, m))
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return out


def _parse_wp_datetime(value: Optional[str], tz_name: Optional[str] = None) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return _parse_date_any(value)
    if dt.tzinfo is None and tz_name:
        tzinfo = tz.gettz(tz_name)
        if tzinfo:
            dt = dt.replace(tzinfo=tzinfo)
    return dt


def _is_feed_content(data: bytes) -> bool:
    try:
        snippet = data[:4096].lower()
    except Exception:
        return False
    return any(token in snippet for token in (b"<rss", b"<feed", b"<rdf", b"<atom"))


def _discover_feed_url(cfg: ScrapeConfig, s: requests.Session) -> Optional[str]:
    key = cfg.base_url.rstrip("/")
    if key in _FEED_DISCOVERY_CACHE:
        return _FEED_DISCOVERY_CACHE[key]

    candidates: List[str] = []
    base_for_join = cfg.base_url
    try:
        resp = _get(s, cfg.base_url, cfg)
        base_for_join = resp.url or cfg.base_url
        soup = BeautifulSoup(resp.content, "lxml")
        for link in soup.find_all("link"):
            rel_attr = link.get("rel")
            if rel_attr:
                rels = [r.lower() for r in (rel_attr if isinstance(rel_attr, list) else [rel_attr])]
            else:
                rels = []
            if "alternate" not in rels:
                continue
            type_attr = (link.get("type") or "").lower()
            if not any(token in type_attr for token in ["rss", "atom", "xml"]):
                continue
            href = link.get("href")
            if not href:
                continue
            candidate = urljoin(base_for_join, html.unescape(href.strip()))
            candidates.append(candidate)
        if not candidates:
            for a in soup.find_all("a"):
                href = a.get("href")
                if not href:
                    continue
                href_lower = href.lower()
                if any(token in href_lower for token in ["rss", "atom", "feed", "xml"]):
                    candidate = urljoin(base_for_join, html.unescape(href.strip()))
                    candidates.append(candidate)
    except Exception:
        base_for_join = cfg.base_url

    fallback_paths = [
        "/feed/",
        "/feed",
        "/?feed=rss2",
        "/?feed=rss",
        "/?feed=atom",
        "/rss.xml",
        "/rss",
        "/rss/",
        "/atom.xml",
        "/index.xml",
    ]

    urls_to_try: List[str] = []
    seen: Set[str] = set()
    for candidate in candidates:
        absolute = urljoin(base_for_join if base_for_join.endswith("/") else base_for_join + "/", candidate)
        if absolute not in seen:
            urls_to_try.append(absolute)
            seen.add(absolute)
    base_join = base_for_join if base_for_join.endswith("/") else base_for_join + "/"
    for path in fallback_paths:
        absolute = urljoin(base_join, path)
        if absolute not in seen:
            urls_to_try.append(absolute)
            seen.add(absolute)

    for url in urls_to_try:
        try:
            resp = s.get(url, timeout=cfg.timeout_sec, allow_redirects=True)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if any(token in content_type for token in ["rss", "atom", "xml"]):
            final_url = resp.url or url
            _FEED_DISCOVERY_CACHE[key] = final_url
            return final_url
        if resp.content and _is_feed_content(resp.content):
            final_url = resp.url or url
            _FEED_DISCOVERY_CACHE[key] = final_url
            return final_url

    _FEED_DISCOVERY_CACHE[key] = None
    return None


def collect_from_feed(cfg: ScrapeConfig, s: Optional[requests.Session] = None) -> List[Tuple[str, Optional[datetime]]]:
    """Feed をたどって URL と日付を収集。WordPress 以外にも対応。"""
    s = s or _session(cfg)
    if cfg.feed_url_override:
        feed_url = cfg.feed_url_override
        _progress(f"[FEED] override feed: {feed_url}")
    else:
        discovered = _discover_feed_url(cfg, s)
        if discovered:
            feed_url = discovered
            _progress(f"[FEED] discovered feed: {feed_url}")
        else:
            feed_url = urljoin(cfg.base_url, "/feed/")
            _progress(f"[FEED] fallback feed: {feed_url}")

    feed_lower = feed_url.lower()
    supports_paging = bool(re.search(r"/feed/?$", feed_lower)) or ("feed=" in feed_lower)
    results: List[Tuple[str, Optional[datetime]]] = []
    seen: Set[str] = set()
    global _FEED_ENTRY_CACHE

    def page_url(n: int) -> str:
        if n <= 1 or not supports_paging:
            return feed_url
        sep = "&" if "?" in feed_url else "?"
        return f"{feed_url}{sep}paged={n}"

    page = 1
    _progress("[FEED] 取得開始")
    while True:
        if cfg.max_pages and page > cfg.max_pages:
            break
        if page > 1 and not supports_paging:
            break
        url = page_url(page)
        resp = _get(s, url, cfg)
        if resp.status_code != 200:
            break
        parsed = feedparser.parse(resp.content)
        if not parsed.entries:
            break
        stop_due_to_date = False
        added_this_page = 0
        for e in parsed.entries:
            link = html.unescape(e.get("link") or e.get("id") or "").strip()
            if not link or link in seen:
                continue
            # 日付
            dt = None
            if e.get("published"):
                dt = _parse_date_any(e["published"])
            elif e.get("updated"):
                dt = _parse_date_any(e["updated"])
            if dt is None:
                # URLやタイトルから推定
                dt = _extract_date_from_url_or_title(link, e.get("title", ""))
            if dt:
                d = dt.date()
                if d < cfg.start_date:
                    stop_due_to_date = True
                    # ただし現在ページ内の他エントリが範囲内かもしれないので、breakせず続行
                if d > cfg.end_date:
                    # 未来や範囲外上限はスキップ
                    continue
            title = html.unescape(e.get("title", "")).strip() or None
            content_html = None
            try:
                content_list = e.get("content")
                if content_list:
                    content_html = content_list[0].value
            except Exception:
                content_html = None
            summary_html = None
            if e.get("summary"):
                summary_html = e["summary"]
            else:
                summary_detail = e.get("summary_detail")
                if isinstance(summary_detail, dict):
                    summary_html = summary_detail.get("value")
            author = html.unescape(e.get("author", "")).strip() or None
            categories: List[str] = []
            for tag in e.get("tags", []):
                term = None
                if isinstance(tag, dict):
                    term = tag.get("term")
                else:
                    term = getattr(tag, "term", None)
                if term:
                    categories.append(html.unescape(term).strip())
            categories = sorted({c for c in categories if c})
            _FEED_ENTRY_CACHE[link] = FeedEntryData(
                url=link,
                title=title,
                published=dt,
                author=author,
                categories=categories,
                content_html=content_html,
                summary_html=summary_html,
            )
            results.append((link, dt))
            seen.add(link)
            added_this_page += 1
        _progress(f"[FEED] page {page}: 取得 {added_this_page} 件 (累計 {len(results)})")
        # 範囲外まで到達したと判断できる場合は終了
        if stop_due_to_date and all((dt and dt.date() < cfg.start_date) for _, dt in results[-min(len(parsed.entries), 20):] if dt):
            break
        page += 1
        if not supports_paging:
            break
        time.sleep(cfg.throttle_sec)
    return results


def _find_next_page_url(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    # ページ送りリンク（数字 or Next/Older）を総当りで探す
    # 1) rel="next"
    a = soup.select_one("a[rel='next']")
    if a and a.get("href"):
        return urljoin(base_url, a["href"])
    # 2) ページ番号の最後の a
    pager = soup.select(".pagination a, .nav-links a, .page-numbers a, .pagination a.next, a.next")
    if pager:
        # 末尾のリンクが「次へ」であることが多い
        href = pager[-1].get("href")
        if href:
            return urljoin(base_url, href)
    # 3) 「Paĝo」「Pli malnovaj」「Older」などを含むリンク
    for a in soup.find_all("a"):
        t = (a.get_text() or "").strip().lower()
        if "older" in t or "pli malnov" in t or "paĝo" in t or "next" in t:
            if a.get("href"):
                return urljoin(base_url, a["href"])
    return None


def collect_from_archives(cfg: ScrapeConfig, s: Optional[requests.Session] = None) -> List[Tuple[str, Optional[datetime]]]:
    """
    /YYYY/MM/ の月別アーカイブを月ごとにクロールして記事URLを収集。
    必要に応じて page/2/ などのページ送りも追う。
    """
    s = s or _session(cfg)
    out: List[Tuple[str, Optional[datetime]]] = []
    seen: Set[str] = set()

    for yyyy, mm in month_range(cfg.start_date, cfg.end_date):
        base = f"{cfg.base_url}/{yyyy:04d}/{mm:02d}/"
        page_url = base
        page_idx = 1
        _progress(f"[ARCHIVE] {yyyy}-{mm:02d} 収集開始")
        while True:
            if cfg.max_pages and page_idx > cfg.max_pages:
                break
            resp = _get(s, page_url, cfg)
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.content, "lxml")
            # 記事リンク候補を列挙（WordPressの一般的な構造）
            candidates = set()
            for sel in [
                "h2 a", "h3 a", ".entry-title a", "article h2 a", "article h3 a",
                ".et_pb_post h2 a", ".et_pb_post h3 a",
                ".post h2 a", ".post h3 a",
                "a.more-link", "a.read-more", "a[rel='bookmark']"
            ]:
                for a in soup.select(sel):
                    href = a.get("href")
                    if href and re.search(r"/\d{4}/\d{2}/", href):
                        candidates.add(urljoin(cfg.base_url, href))
            # URL 正規化 & 重複排除 & 日付推定
            for link in sorted(candidates):
                if link in seen:
                    continue
                dt = _extract_date_from_url_or_title(link, (a.get_text() if (a:=soup.find('a', href=link)) else ""))
                # 月の範囲に入っているか一応確認（後で厳密フィルタ）
                out.append((link, dt))
                seen.add(link)

            _progress(f"[ARCHIVE] {yyyy}-{mm:02d} page {page_idx}: 候補 {len(candidates)} 件 (累計 {len(out)})")
            # 次ページ探索
            next_url = _find_next_page_url(soup, cfg.base_url)
            if not next_url or (f"/{yyyy:04d}/{mm:02d}/" not in next_url):
                break
            page_url = next_url
            page_idx += 1
            time.sleep(cfg.throttle_sec)

    return out


def collect_from_rest(cfg: ScrapeConfig, s: Optional[requests.Session] = None) -> List[Tuple[str, Optional[datetime]]]:
    """
    WordPress REST API (wp-json/wp/v2/posts) から期間内の記事一覧を高速に取得する。
    """
    s = s or _session(cfg)
    endpoint = urljoin(cfg.base_url, "/wp-json/wp/v2/posts")
    per_page = 100
    params = {
        "per_page": per_page,
        "orderby": "date",
        "order": "asc",
        "after": datetime.combine(cfg.start_date, datetime.min.time()).isoformat(),
        "before": datetime.combine(cfg.end_date, datetime.max.time()).isoformat(),
        "_embed": "author,wp:term",
    }
    results: List[Tuple[str, Optional[datetime]]] = []
    seen: Set[str] = set()
    total_pages_reported: Optional[int] = None
    total_items_reported: Optional[int] = None
    _progress(f"[REST] 取得開始: {params['after']} ～ {params['before']}")
    page = 1
    while True:
        params["page"] = page
        query = urlencode(params, doseq=True)
        url = f"{endpoint}?{query}"
        resp = _get(s, url, cfg)
        if resp.status_code == 400 and "rest_post_invalid_page_number" in resp.text:
            break
        if resp.status_code >= 400:
            resp.raise_for_status()
        if total_pages_reported is None:
            try:
                total_pages_reported = int(resp.headers.get("X-WP-TotalPages"))
            except (TypeError, ValueError):
                total_pages_reported = None
            try:
                total_items_reported = int(resp.headers.get("X-WP-Total"))
            except (TypeError, ValueError):
                total_items_reported = None
            if total_items_reported is not None:
                _progress(f"[REST] 総投稿見込み: {total_items_reported} 件 / 推定ページ数 {total_pages_reported or '?'}")
        payload = resp.json()
        if not payload:
            break
        added_this_page = 0
        for item in payload:
            link = html.unescape(item.get("link") or "").strip()
            if not link or link in seen:
                continue
            dt = _parse_wp_datetime(item.get("date_gmt"), "UTC") or _parse_wp_datetime(item.get("date"), cfg.timezone)
            if dt and dt.tzinfo and cfg.timezone:
                tzinfo = tz.gettz(cfg.timezone)
                if tzinfo:
                    dt = dt.astimezone(tzinfo)
            title_raw = item.get("title", {}).get("rendered", "")
            title = html.unescape(title_raw).strip() or None
            content_html = item.get("content", {}).get("rendered")
            summary_html = item.get("excerpt", {}).get("rendered")
            author_name = None
            embedded = item.get("_embedded") or {}
            for author in embedded.get("author") or []:
                name = html.unescape(author.get("name", "")).strip()
                if name:
                    author_name = name
                    break
            categories: List[str] = []
            for term_group in embedded.get("wp:term") or []:
                if not term_group:
                    continue
                for term in term_group:
                    if term.get("taxonomy") == "category":
                        name = html.unescape(term.get("name", "")).strip()
                        if name:
                            categories.append(name)
            categories = sorted({c for c in categories if c})
            entry = FeedEntryData(
                url=link,
                title=title,
                published=dt,
                author=author_name,
                categories=categories,
                content_html=content_html,
                summary_html=summary_html,
            )
            _FEED_ENTRY_CACHE[link] = entry
            results.append((link, dt))
            seen.add(link)
            added_this_page += 1
        _progress(f"[REST] page {page}{f'/{total_pages_reported}' if total_pages_reported else ''}: {added_this_page} 件 (累計 {len(results)})")
        if total_pages_reported and page >= total_pages_reported:
            break
        page += 1
        time.sleep(cfg.throttle_sec)
    return results


def collect_urls(cfg: ScrapeConfig) -> URLCollectionResult:
    """
    cfg.method に従って URL 一覧を返す（重複排除 + 統計情報付き）。
    """
    cfg.normalize()
    s = _session(cfg)
    global _FEED_ENTRY_CACHE
    if cfg.method in ("feed", "both", "archive", "rest", "auto"):
        _FEED_ENTRY_CACHE.clear()

    feed_items: List[Tuple[str, Optional[datetime]]] = []
    archive_items: List[Tuple[str, Optional[datetime]]] = []
    rest_items: List[Tuple[str, Optional[datetime]]] = []
    rest_success = False

    if cfg.method in ("rest", "auto"):
        try:
            rest_items = collect_from_rest(cfg, s)
            rest_success = True
        except Exception as exc:
            logging.getLogger(__name__).warning("REST API 取得に失敗しました: %s", exc, exc_info=True)
            _progress(f"[WARN] REST API 取得失敗: {exc}")
            if cfg.method == "rest":
                raise

    if cfg.method == "rest":
        feed_items = []
        archive_items = []
    elif cfg.method == "auto" and rest_success:
        feed_items = []
        archive_items = []
    else:
        if cfg.method in ("feed", "both", "auto"):
            feed_items = collect_from_feed(cfg, s)
        if cfg.method in ("archive", "both", "auto"):
            archive_items = collect_from_archives(cfg, s)

    combined: List[Tuple[str, Optional[datetime], str]] = []
    combined.extend((u, dt, "rest") for u, dt in rest_items)
    combined.extend((u, dt, "feed") for u, dt in feed_items)
    combined.extend((u, dt, "archive") for u, dt in archive_items)

    duplicates_removed = 0
    uniq: Dict[str, Tuple[str, Optional[datetime], str]] = {}
    for original_url, dt, source in combined:
        key = _normalize_url(original_url)
        dt_naive = dt.replace(tzinfo=None) if (dt and dt.tzinfo) else dt
        existing = uniq.get(key)
        if existing:
            duplicates_removed += 1
            existing_url, existing_dt, existing_source = existing
            existing_dt_naive = (
                existing_dt.replace(tzinfo=None) if (existing_dt and existing_dt.tzinfo) else existing_dt
            )

            replace = False
            current_priority = SOURCE_PRIORITY.get(existing_source, 0)
            new_priority = SOURCE_PRIORITY.get(source, 0)

            if new_priority > current_priority:
                replace = True
            elif new_priority == current_priority:
                if dt_naive and existing_dt_naive:
                    replace = dt_naive < existing_dt_naive
                elif dt_naive and not existing_dt_naive:
                    replace = True
                elif not dt_naive and not existing_dt_naive:
                    replace = original_url < existing_url

            if replace:
                uniq[key] = (original_url, dt, source)
            continue
        uniq[key] = (original_url, dt, source)

    filtered: List[Tuple[str, Optional[datetime], str]] = []
    out_of_range = 0
    earliest_date: Optional[date] = None
    latest_date: Optional[date] = None
    feed_used = 0
    archive_used = 0
    rest_used = 0

    for original_url, dt, source in uniq.values():
        if dt:
            d = dt.date()
            if d < cfg.start_date or d > cfg.end_date:
                out_of_range += 1
                continue
        filtered.append((original_url, dt, source))

    def sort_key(item: Tuple[str, Optional[datetime], str]):
        url, dt, _source = item
        if dt:
            dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
            return (dt_naive, url)
        return (datetime.max, url)

    filtered.sort(key=sort_key)

    urls: List[str] = []
    for original_url, dt, source in filtered:
        urls.append(original_url)
        if dt:
            d = dt.date()
            if earliest_date is None or d < earliest_date:
                earliest_date = d
            if latest_date is None or d > latest_date:
                latest_date = d
        if source == "feed":
            feed_used += 1
        elif source == "archive":
            archive_used += 1
        elif source == "rest":
            rest_used += 1

    return URLCollectionResult(
        urls=urls,
        feed_initial=len(feed_items),
        archive_initial=len(archive_items),
        rest_initial=len(rest_items),
        feed_used=feed_used,
        archive_used=archive_used,
        rest_used=rest_used,
        duplicates_removed=duplicates_removed,
        out_of_range_skipped=out_of_range,
        earliest_date=earliest_date,
        latest_date=latest_date,
    )


def _clean_text(s: str) -> str:
    s = html.unescape(s)
    # 各種空白正規化
    s = re.sub(r'\r\n|\r', '\n', s)
    # 余分な空行を畳む
    s = re.sub(r'\n{3,}', '\n\n', s)
    # 末尾の空白
    return s.strip()


def _extract_main_content(soup: BeautifulSoup) -> str:
    """
    WordPress + Elegant Themes(Divi系) を想定しつつ、汎用的に本文を抽出。
    見出し(H2-H4)と段落(P)、リスト(LI)をテキスト化。
    """
    # 最有力候補
    candidates = [
        ".entry-content",
        ".post-content",
        "article .entry-content",
        "article .post-content",
        ".et_pb_post_content",
        ".et_pb_text_inner",
        "#left-area",
        "article"
    ]
    node = None
    for sel in candidates:
        node = soup.select_one(sel)
        if node:
            break
    if node is None:
        node = soup.body or soup

    # 不要な要素を除去
    for bad in node.select("script, style, nav, header, footer, aside, noscript, form, iframe, figure.share, .post-meta, .et_post_meta_wrapper"):
        bad.decompose()

    texts: List[str] = []
    def push(line: str):
        line = (line or "").strip()
        if line:
            texts.append(line)

    # タイトル直下の著者・カテゴリ・コメント案内などを緩くスキップ
    for h in node.select("h1, h2, h3, h4, p, li"):
        t = h.get_text(" ", strip=True)
        # 余計なラベルを含む段落は回避
        low = t.lower()
        if any(key in low for key in ["ensaluti", "komenta", "skribu komenton", "posted in", "kategori", "enretigita de"]):
            continue
        push(t)

    # 最低限、空なら全文テキスト
    if not texts:
        push(node.get_text(" ", strip=True))
    return _clean_text("\n\n".join(texts))


def _extract_title(soup: BeautifulSoup) -> str:
    for sel in ["h1.entry-title", "h1.post-title", "article h1", "h1"]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(" ", strip=True)
    # <title> からサイト名を取り除く
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
    return re.sub(r"\s*\|\s*Pola Retradio.*$", "", title).strip()


def _extract_author_and_categories(soup: BeautifulSoup) -> Tuple[Optional[str], List[str]]:
    author = None
    cats: List[str] = []
    # 典型的なメタ情報
    meta = soup.find(class_=re.compile(r"(post-meta|et_post_meta_wrapper|entry-meta)"))
    if meta:
        # 著者
        by = meta.find(text=re.compile(r"Enretigita de|By|Autor", re.I))
        if by and hasattr(by, "parent"):
            author = by.parent.get_text(" ", strip=True)
            author = re.sub(r".*?:", "", author).strip()
        # カテゴリ
        for a in meta.find_all("a"):
            tt = a.get_text(" ", strip=True)
            if tt and tt.lower() not in ["facebook", "x", "instagram"]:
                cats.append(tt)
    # 予備：パンくずやタグブロック
    for a in soup.select(".post-meta a, .entry-meta a, .et_post_meta_wrapper a[rel='category tag']"):
        tt = a.get_text(" ", strip=True)
        if tt and tt.lower() not in ["facebook", "x", "instagram"]:
            cats.append(tt)
    # 正規化
    cats = sorted(set(cats))
    return author, cats


def _extract_audio_links(soup: BeautifulSoup) -> List[str]:
    links = set()
    # audio / mp3 / source
    for sel in ["audio source", "audio", "a"]:
        for el in soup.select(sel):
            href = el.get("src") or el.get("href")
            if href and ("mp3" in href or "audio" in href):
                links.add(href)
    return sorted(links)


def _article_from_feed_entry(entry: FeedEntryData, cfg: ScrapeConfig) -> Optional[Article]:
    html_fragment = entry.content_html or entry.summary_html
    if not html_fragment:
        return None
    soup = BeautifulSoup(html_fragment, "lxml")
    for bad in soup.select("script, style, nav, header, footer, aside, noscript"):
        bad.decompose()

    blocks: List[str] = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
        text = node.get_text(" ", strip=True)
        if text:
            blocks.append(text)
    if not blocks:
        blocks.append(soup.get_text(" ", strip=True))
    content_text = _clean_text("\n\n".join(blocks))
    if not content_text:
        return None

    audio_links: Optional[List[str]] = None
    if cfg.include_audio_links:
        links = set()
        for el in soup.find_all(["a", "audio", "source"]):
            href = el.get("href") or el.get("src")
            if not href:
                continue
            lower = href.lower()
            if "mp3" in lower or "audio" in lower:
                links.add(href)
        if links:
            audio_links = sorted(links)

    categories = sorted({c for c in entry.categories if c}) if entry.categories else None
    return Article(
        url=entry.url,
        title=entry.title or entry.url,
        published=entry.published,
        content_text=content_text,
        author=entry.author,
        categories=categories,
        audio_links=audio_links,
    )


def fetch_article(url: str, cfg: ScrapeConfig, s: Optional[requests.Session] = None) -> Article:
    entry = _FEED_ENTRY_CACHE.get(url)
    if entry:
        article = _article_from_feed_entry(entry, cfg)
        if article and article.published and cfg.start_date and cfg.end_date:
            pub_date = article.published.date()
            if pub_date < cfg.start_date or pub_date > cfg.end_date:
                article = None
        if article:
            return article
    s = s or _session(cfg)
    resp = _get(s, url, cfg)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "lxml")

    title = _extract_title(soup)
    # 公開日：time要素 or メタ or URL/タイトルから推定
    dt: Optional[datetime] = None
    t_el = soup.find("time")
    if t_el:
        # datetime属性 or テキスト
        val = (t_el.get("datetime") or t_el.get_text(" ", strip=True) or "").strip()
        dt = _parse_date_any(val)
    if not dt:
        # ページ内のメタから
        txt = soup.get_text(" ", strip=True)
        # 例: Oktobro 5, 2025 | など
        m = re.search(r"(Januaro|Februaro|Marto|Aprilo|Majo|Junio|Julio|Aŭgusto|Septembro|Oktobro|Novembro|Decembro)\s+\d{1,2},\s+\d{4}", txt, flags=re.I)
        if m:
            dt = _parse_date_any(m.group(0))
    if not dt:
        dt = _extract_date_from_url_or_title(url, title)

    content_text = _extract_main_content(soup)
    author, cats = _extract_author_and_categories(soup)
    audio_links = _extract_audio_links(soup) if cfg.include_audio_links else []

    return Article(
        url=url,
        title=title or url,
        published=dt,
        content_text=content_text,
        author=author,
        categories=cats or None,
        audio_links=audio_links or None
    )


# -------------------- Export helpers --------------------

MD_HEADER_TEMPLATE = """---
source: "{source}"
generated_at: "{generated_at}"
generator: "retradio_lib.py"
time_range: "{start} – {end}"
---

"""

def _default_source_label(cfg: ScrapeConfig) -> str:
    host = urlparse(cfg.base_url).netloc or cfg.base_url
    base = cfg.base_url.lower()
    # 既存の既定値は Pola Retradio を維持
    if "pola-retradio.org" in base:
        return "Pola Retradio (pola-retradio.org)"
    if "eo.globalvoices.org" in base:
        return "Global Voices en Esperanto (eo.globalvoices.org)"
    if "monato.be" in base:
        return "MONATO (monato.be)"
    if "esperanto.china.org.cn" in base:
        return "El Popola Ĉinio (esperanto.china.org.cn)"
    if "scivolemo.com" in base:
        return "Scivolemo (scivolemo.com)"
    return host

def to_markdown(articles: List[Article], cfg: ScrapeConfig) -> str:
    source_label = cfg.source_label or _default_source_label(cfg)
    parts = [MD_HEADER_TEMPLATE.format(
        source=source_label,
        generated_at=datetime.now(tz=tz.gettz("UTC")).isoformat(),
        start=cfg.start_date.isoformat(),
        end=cfg.end_date.isoformat(),
    )]
    for a in articles:
        parts.append(f"# {a.title}\n")
        meta = []
        if a.published:
            meta.append(f"**Published:** {a.published.strftime('%Y-%m-%d')}")
        meta.append(f"**URL:** {a.url}")
        if a.author:
            meta.append(f"**Author:** {a.author}")
        if a.categories:
            meta.append(f"**Categories:** {', '.join(a.categories)}")
        if a.audio_links:
            meta.append(f"**Audio:** {', '.join(a.audio_links)}")
        parts.append("\n\n".join(meta) + "\n")
        parts.append(a.content_text.strip() + "\n")
        parts.append("\n---\n")
    return "\n".join(parts).strip() + "\n"


def to_text(articles: List[Article]) -> str:
    parts = []
    for a in articles:
        parts.append(f"{a.title}")
        if a.published:
            parts.append(f"[{a.published.strftime('%Y-%m-%d')}]")
        parts.append(a.url)
        parts.append("")
        parts.append(a.content_text.strip())
        parts.append("\n" + ("-"*80) + "\n")
    return "\n".join(parts).strip() + "\n"


def to_csv(articles: List[Article]) -> str:
    import io
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["url","title","published","author","categories","audio_links"])
    writer.writeheader()
    for a in articles:
        writer.writerow(a.to_row())
    return output.getvalue()


def to_jsonl(articles: List[Article]) -> str:
    return "\n".join(json.dumps(asdict(a), ensure_ascii=False, default=str) for a in articles) + "\n"


def export_all(articles: List[Article], cfg: ScrapeConfig, out_dir: str, basename: Optional[str] = None) -> Dict[str, str]:
    """
    各形式を書き出してファイルパスを返す。
    """
    os.makedirs(out_dir, exist_ok=True)
    if not basename:
        basename = f"pola_retradio_{cfg.start_date.isoformat()}_{cfg.end_date.isoformat()}"
    paths = {}
    md = to_markdown(articles, cfg)
    txt = to_text(articles)
    csv_str = to_csv(articles)
    jsonl = to_jsonl(articles)

    def write(name, data):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(data)
        return p

    paths["md"] = write(basename + ".md", md)
    paths["txt"] = write(basename + ".txt", txt)
    paths["csv"] = write(basename + ".csv", csv_str)
    paths["jsonl"] = write(basename + ".jsonl", jsonl)
    return paths
