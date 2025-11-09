# -*- coding: utf-8 -*-
"""
elpopola_lib.py

Custom scraper helpers for El Popola Ĉinio (esperanto.china.org.cn).
The site predates WordPress and exposes lists via numerous `node_*.htm`
pages. Articles live at URLs like `/YYYY-MM/DD/content_<id>.htm`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from retradio_lib import (  # type: ignore
    Article,
    ScrapeConfig,
    URLCollectionResult,
    _clean_text as base_clean_text,
    _session as shared_session,
    set_progress_callback,
)

USER_AGENT = "Mozilla/5.0 (compatible; ElPopolaScraper/1.0; +http://esperanto.china.org.cn)"
DEFAULT_NODE_IDS = [
    "7117770",  # Plej freŝaj
    "7117772",  # Novaĵoj
    "7117773",
    "7117774",
    "7117775",
    "7117776",
    "7117777",
    "7117778",
    "7117779",
    "7117780",
    "7117782",
    "7117783",
    "7117784",
    "7117785",
    "7117786",
    "7117787",
    "7117788",
    "7117969",
    "8007437",
    "8019218",
    "8019350",
    "8022718",
    "8028194",
    "9003653",
]
MAX_NODE_PAGES = 20

EPC_META: Dict[str, Dict[str, object]] = {}


@dataclass
class _CollectedEntry:
    url: str
    title: str
    published: Optional[datetime]
    section: Optional[str]


def _normalize_base(base_url: str) -> str:
    base = base_url.strip()
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    return base.rstrip("/")


def _session(cfg: ScrapeConfig) -> requests.Session:
    s = shared_session(cfg)
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _parse_date_from_url(url: str) -> Optional[datetime]:
    m = re.search(r"/(20\d{2})-(\d{2})/(\d{2})/", url)
    if not m:
        return None
    year, month, day = map(int, m.groups())
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _extract_section_name(soup: BeautifulSoup) -> Optional[str]:
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if "-" in title:
            return title.split("-", 1)[0].strip()
        return title
    heading = soup.find(["h1", "h2"])
    if heading:
        return heading.get_text(" ", strip=True)
    return None


def _collect_from_node(
    node_id: str,
    cfg: ScrapeConfig,
    session: requests.Session,
    base_url: str,
    base_host: str,
) -> List[_CollectedEntry]:
    entries: List[_CollectedEntry] = []
    seen_on_node: set[str] = set()
    max_pages = cfg.max_pages or MAX_NODE_PAGES

    for page in range(1, max_pages + 1):
        if page == 1:
            page_url = f"{base_url}/node_{node_id}.htm"
        else:
            page_url = f"{base_url}/node_{node_id}_{page}.htm"
        try:
            resp = session.get(page_url, timeout=cfg.timeout_sec)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("failed to load node page %s: %s", page_url, exc)
            break
        if resp.status_code != 200:
            break
        soup = BeautifulSoup(resp.content, "lxml")
        section_name = _extract_section_name(soup)
        links = soup.select("a[href*='content_']")
        if not links:
            break

        page_dates: List[date] = []
        page_added = False

        for link in links:
            href = link.get("href")
            if not href:
                continue
            url = urljoin(base_url + "/", href)
            parsed = urlparse(url)
            if parsed.netloc and parsed.netloc != base_host:
                continue
            if url in seen_on_node:
                continue
            dt = _parse_date_from_url(url)
            if dt:
                page_dates.append(dt.date())
                if dt.date() > cfg.end_date:
                    continue
                if dt.date() < cfg.start_date:
                    continue
            else:
                # Skip items that do not follow the standard pattern.
                continue

            title = link.get_text(" ", strip=True)
            if not title:
                continue

            entries.append(_CollectedEntry(url=url, title=title, published=dt, section=section_name))
            seen_on_node.add(url)
            page_added = True

        if not page_added and page_dates:
            latest = max(page_dates)
            if latest < cfg.start_date:
                break

    return entries


def _discover_nodes(cfg: ScrapeConfig, session: requests.Session, base_url: str) -> List[str]:
    nodes = set(DEFAULT_NODE_IDS)
    try:
        resp = session.get(base_url, timeout=cfg.timeout_sec)
        resp.raise_for_status()
        matches = re.findall(r"node_(\d+)\.htm", resp.text)
        nodes.update(matches)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("failed to discover nodes dynamically", exc_info=True)
    return sorted(nodes)


def collect_urls(cfg: ScrapeConfig) -> URLCollectionResult:
    cfg.normalize()
    base_url = _normalize_base(cfg.base_url)
    session = _session(cfg)

    aggregated: Dict[str, _CollectedEntry] = {}
    nodes = _discover_nodes(cfg, session, base_url)
    base_host = urlparse(base_url).netloc

    for node_id in nodes:
        node_entries = _collect_from_node(node_id, cfg, session, base_url, base_host)
        for entry in node_entries:
            existing = aggregated.get(entry.url)
            if existing:
                # Prefer entry with earlier publication (more precise metadata)
                if existing.published and entry.published:
                    if entry.published < existing.published:
                        aggregated[entry.url] = entry
                elif entry.published and not existing.published:
                    aggregated[entry.url] = entry
                continue
            aggregated[entry.url] = entry

    urls = []
    earliest: Optional[date] = None
    latest: Optional[date] = None
    EPC_META.clear()

    for url, entry in sorted(
        aggregated.items(),
        key=lambda item: ((item[1].published or datetime.max).date(), item[0]),
    ):
        urls.append(url)
        EPC_META[url] = {
            "published": entry.published,
            "section": entry.section,
            "title": entry.title,
        }
        if entry.published:
            d = entry.published.date()
            if earliest is None or d < earliest:
                earliest = d
            if latest is None or d > latest:
                latest = d

    total = len(urls)
    return URLCollectionResult(
        urls=urls,
        feed_initial=total,
        archive_initial=0,
        rest_initial=0,
        feed_used=total,
        archive_used=0,
        rest_used=0,
        duplicates_removed=0,
        out_of_range_skipped=0,
        earliest_date=earliest,
        latest_date=latest,
    )


NOISE_SNIPPETS = [
    "视频播放位置",
    "下载安装Flash播放器",
    "Facebook",
    "Twitter",
    "WeChat",
    "Ĉina Fokuso",
    "China Focus",
    "Skani la du-dimensian kodon",
]

FALLBACK_SELECTORS = (
    "#content",
    "#contentArea",
    "#main",
    "#center",
    ".content",
    ".article",
    ".article-content",
    ".main",
    "article",
)

DATE_PATTERNS = [
    re.compile(r"(20\d{2})-(\d{2})-(\d{2})"),
    re.compile(r"(20\d{2})/(\d{2})/(\d{2})"),
]


def _clean_paragraphs(lines: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if any(noise in text for noise in NOISE_SNIPPETS):
            continue
        cleaned.append(base_clean_text(text))
    return cleaned


def _extract_author(html: str) -> Optional[str]:
    patterns = [
        r"Verkis[:：]\s*([^\n<]+)",
        r"Verkinto[:：]\s*([^\n<]+)",
        r"Aŭtoro[:：]\s*([^\n<]+)",
        r"Teksto[:：]\s*([^\n<]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, html, flags=re.IGNORECASE)
        if m:
            author = base_clean_text(m.group(1))
            if author:
                return author
    return None


def fetch_article(url: str, cfg: ScrapeConfig, session: Optional[requests.Session] = None) -> Article:
    cfg.normalize()
    s = session or _session(cfg)
    resp = s.get(url, timeout=cfg.timeout_sec)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    meta = EPC_META.get(url, {})
    published = meta.get("published")

    legacy = _extract_legacy_article(soup)
    if legacy:
        title, date_str, content_node = legacy
        if not published:
            published = _parse_explicit_date(date_str) or _parse_date_from_url(url)
        raw_lines = [line for line in content_node.get_text("\n").split("\n")]
        paragraphs = _clean_paragraphs(raw_lines)
    else:
        title = base_clean_text(meta.get("title") or _fallback_title(soup)) or url
        if not published:
            published = _extract_date_from_document(soup) or _parse_date_from_url(url)
        content_node = _fallback_article_root(soup)
        raw_lines = [line for line in content_node.get_text("\n").split("\n")]
        paragraphs = _clean_paragraphs(raw_lines)
        if not paragraphs:
            paragraphs = [base_clean_text(content_node.get_text(" ", strip=True))]

    content_text = "\n\n".join(paragraphs)

    author = _extract_author(html)
    section = base_clean_text(meta.get("section") or "") or None

    categories = [section] if section else None

    return Article(
        url=url,
        title=title or meta.get("title", url),
        published=published,
        content_text=content_text,
        author=author,
        categories=categories,
        audio_links=None,
    )


def _extract_legacy_article(soup: BeautifulSoup) -> Optional[tuple[str, str, BeautifulSoup]]:
    first_table = soup.find("table")
    if not first_table:
        return None
    rows = first_table.find_all("tr")
    if len(rows) < 2:
        return None
    title = base_clean_text(rows[0].get_text(" ", strip=True))
    date_str = rows[1].get_text(" ", strip=True)
    content_td = rows[3].find("td") if len(rows) > 3 else rows[-1].find("td")
    if not content_td:
        content_td = first_table
    return title, date_str, content_td


def _parse_explicit_date(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except Exception:
        match = DATE_PATTERNS[0].search(text)
        if match:
            year, month, day = map(int, match.groups())
            try:
                return datetime(year, month, day)
            except ValueError:
                return None
    return None


def _fallback_article_root(soup: BeautifulSoup) -> BeautifulSoup:
    for selector in FALLBACK_SELECTORS:
        node = soup.select_one(selector)
        if node:
            for bad in node.select("script, style, nav, header, footer, aside, noscript"):
                bad.decompose()
            return node
    body = soup.body or soup
    for bad in body.select("script, style, nav, header, footer, aside, noscript"):
        bad.decompose()
    return body


def _fallback_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    if soup.title:
        return soup.title.get_text(" ", strip=True)
    return ""


def _extract_date_from_document(soup: BeautifulSoup) -> Optional[datetime]:
    for selector in ["time", ".publish-time", ".pubtime", ".date", ".info"]:
        node = soup.select_one(selector)
        if not node:
            continue
        candidate = node.get("datetime") or node.get_text(" ", strip=True)
        parsed = _parse_explicit_date(candidate or "")
        if parsed:
            return parsed
    text_sample = soup.get_text(" ", strip=True)
    for pattern in DATE_PATTERNS:
        match = pattern.search(text_sample)
        if match:
            year, month, day = map(int, match.groups())
            try:
                return datetime(year, month, day)
            except ValueError:
                continue
    return None


__all__ = [
    "collect_urls",
    "fetch_article",
    "shared_session",
    "set_progress_callback",
]
