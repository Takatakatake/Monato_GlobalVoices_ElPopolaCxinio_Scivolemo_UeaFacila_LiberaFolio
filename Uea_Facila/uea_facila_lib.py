# -*- coding: utf-8 -*-
"""
uea_facila_lib.py

Helper utilities to scrape articles from uea.facila.org.
The site runs on Invision Community, so we cannot rely on the WordPress
helpers provided in retradio_lib.  Instead we scrape the public "Ĉiu aktivado"
stream (https://uea.facila.org/malkovri/) and fetch individual article pages.
"""
from __future__ import annotations

import logging
import time
import os
from dataclasses import dataclass
from datetime import datetime, timezone, date
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
import dateparser

from retradio_lib import (  # type: ignore
    Article,
    ScrapeConfig,
    URLCollectionResult,
    _clean_text as base_clean_text,
    _session as shared_session,
    set_progress_callback,
)

USER_AGENT = "Mozilla/5.0 (compatible; UEAFacilaScraper/1.0; +https://uea.facila.org)"
STREAM_PATH = "/malkovri/"
VALID_PATH_SEGMENTS = (
    "/artikoloj/",
    "/filmetoj/",
    "/niaj-legantoj/",
    "/loke/",
)
CATEGORY_PATHS = VALID_PATH_SEGMENTS
LOGIN_USER = os.environ.get("UEA_FACILA_USER", "MontaInterno")
LOGIN_PASS = os.environ.get("UEA_FACILA_PASS", "Takashi12345")
_LOGGED_IN = False
_LOGIN_ATTEMPTED = False

UEA_META: Dict[str, Dict[str, object]] = {}


def _session(cfg: ScrapeConfig) -> requests.Session:
    sess = shared_session(cfg)
    sess.headers.update({"User-Agent": USER_AGENT})
    return sess


def _canonicalize_url(base_url: str, href: str) -> Optional[str]:
    if not href:
        return None
    url = href.split("?", 1)[0]
    url = urljoin(base_url.rstrip("/") + "/", url)
    parts = urlsplit(url)
    # Ignore fragments and queries
    url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    if not any(segment in parts.path for segment in VALID_PATH_SEGMENTS):
        return None
    return url


def _parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.isdigit():
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).debug("failed to parse timestamp %s", value, exc_info=True)
    return None


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).debug("iso parse failed for %s", value, exc_info=True)
        return None


def _fetch_listing_page(session: requests.Session, url: str, cfg: ScrapeConfig) -> BeautifulSoup:
    attempt = 1
    while True:
        try:
            resp = session.get(url, timeout=cfg.timeout_sec)
            resp.raise_for_status()
            return BeautifulSoup(resp.content, "lxml")
        except requests.RequestException as exc:
            if attempt >= cfg.max_retries:
                raise
            backoff = min(5.0 * attempt, 30.0)
            time.sleep(backoff)
            attempt += 1


def _stream_page_urls(cfg: ScrapeConfig, session: requests.Session) -> Iterable[BeautifulSoup]:
    base = cfg.base_url.rstrip("/")
    page = 1
    max_pages = cfg.max_pages or 50

    while page <= max_pages:
        url = f"{base}{STREAM_PATH}"
        if page > 1:
            url = f"{url}?page={page}"
        soup = _fetch_listing_page(session, url, cfg)
        yield soup
        page += 1
        if cfg.throttle_sec:
            time.sleep(cfg.throttle_sec)


def _extract_listing_items(container: BeautifulSoup) -> List[tuple[str, Optional[datetime]]]:
    items: List[tuple[str, Optional[datetime]]] = []
    cards = container.select(".ipsDataItem")
    if not cards:
        cards = container.select(".ipsStreamItem")
    if not cards:
        cards = container.select("article.cCmsRecord, li.cCmsRecord")
    for card in cards:
        title_el = card.select_one(".ipsDataItem_title a, .ipsStreamItem_title a")
        if not title_el or not title_el.get("href"):
            continue
        href = title_el["href"]
        dt = None
        time_el = card.find("time")
        if time_el and time_el.get("datetime"):
            dt = _parse_iso_datetime(time_el["datetime"])
        if not dt and card.has_attr("data-timestamp"):
            dt = _parse_timestamp(card["data-timestamp"])
        if not dt:
            date_el = card.select_one("[data-role='recordDate'], .cCmsRecord_meta time")
            if date_el:
                dt = dateparser.parse(date_el.get_text(" ", strip=True), languages=["eo", "en"])
        if not dt:
            text = card.get_text(" ", strip=True)
            dt = dateparser.parse(text, languages=["eo", "en"])
        items.append((href, dt))
    return items


def _ensure_logged_in(session: requests.Session, cfg: ScrapeConfig) -> None:
    """
    Attempt to sign in if credentials are provided. Newer deployments of
    uea.facila.org intermittently reject the scraper account, so we treat
    authentication failures as non-fatal and continue with a public session.
    """
    global _LOGGED_IN, _LOGIN_ATTEMPTED
    if _LOGGED_IN or _LOGIN_ATTEMPTED or not LOGIN_USER or not LOGIN_PASS:
        return
    if session.cookies.get("ips4_member_id"):
        _LOGGED_IN = True
        _LOGIN_ATTEMPTED = True
        return
    _LOGIN_ATTEMPTED = True
    login_url = urljoin(cfg.base_url.rstrip("/") + "/", "ensaluti/")
    try:
        resp = session.get(login_url, timeout=cfg.timeout_sec)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logging.warning("UEA Facila login page request failed: %s. Continuing anonymously.", exc)
        return
    soup = BeautifulSoup(resp.content, "lxml")
    csrf = soup.select_one("input[name='csrfKey']")
    if not csrf or not csrf.get("value"):
        logging.warning("UEA Facila login page did not provide csrfKey; continuing without login.")
        return
    payload = {
        "auth": LOGIN_USER,
        "password": LOGIN_PASS,
        "remember_me": "1",
        "csrfKey": csrf["value"],
        "ref": soup.select_one("input[name='ref']")["value"] if soup.select_one("input[name='ref']") else "",
    }
    try:
        post = session.post(login_url, data=payload, timeout=cfg.timeout_sec)
        post.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logging.warning("UEA Facila login request failed: %s. Continuing anonymously.", exc)
        return
    if session.cookies.get("ips4_member_id"):
        _LOGGED_IN = True
    else:
        logging.warning("UEA Facila login credentials were rejected; continuing with public session.")


def _collect_from_stream(cfg: ScrapeConfig, session: requests.Session, aggregated: Dict[str, datetime]) -> None:
    reached_older_than_start = False
    for soup in _stream_page_urls(cfg, session):
        stream_items = soup.select(".ipsStreamItem")
        if not stream_items:
            break

        min_timestamp_on_page: Optional[datetime] = None
        for href, dt in _extract_listing_items(soup):
            canonical = _canonicalize_url(cfg.base_url, href)
            if not canonical:
                continue
            if not dt:
                continue
            dt = dt.astimezone(timezone.utc)
            item_date = dt.date()
            if item_date > cfg.end_date:
                continue
            if min_timestamp_on_page is None or dt < min_timestamp_on_page:
                min_timestamp_on_page = dt
            if item_date < cfg.start_date:
                reached_older_than_start = True
                continue
            existing = aggregated.get(canonical)
            if existing and existing >= dt:
                continue
            aggregated[canonical] = dt
        if reached_older_than_start and min_timestamp_on_page and min_timestamp_on_page.date() < cfg.start_date:
            break


def _collect_from_categories(cfg: ScrapeConfig, session: requests.Session, aggregated: Dict[str, datetime]) -> None:
    base = cfg.base_url.rstrip("/")
    max_pages = cfg.max_pages or 50
    for path in CATEGORY_PATHS:
        reached_older_than_start = False
        for page in range(1, max_pages + 1):
            url = f"{base}{path}"
            if page > 1:
                url = f"{url}?page={page}"
            soup = _fetch_listing_page(session, url, cfg)
            items = _extract_listing_items(soup)
            if not items:
                break
            min_timestamp_on_page: Optional[datetime] = None
            for href, dt in items:
                canonical = _canonicalize_url(cfg.base_url, href)
                if not canonical:
                    continue
                if not dt:
                    continue
                dt = dt.astimezone(timezone.utc)
                item_date = dt.date()
                if item_date > cfg.end_date:
                    continue
                if min_timestamp_on_page is None or dt < min_timestamp_on_page:
                    min_timestamp_on_page = dt
                if item_date < cfg.start_date:
                    reached_older_than_start = True
                    continue
                existing = aggregated.get(canonical)
                if existing and existing >= dt:
                    continue
                aggregated[canonical] = dt
            if reached_older_than_start and min_timestamp_on_page and min_timestamp_on_page.date() < cfg.start_date:
                break
            if cfg.throttle_sec:
                time.sleep(cfg.throttle_sec)


def collect_urls(cfg: ScrapeConfig) -> URLCollectionResult:
    cfg.normalize()
    session = _session(cfg)

    aggregated: Dict[str, datetime] = {}
    _ensure_logged_in(session, cfg)
    _collect_from_stream(cfg, session, aggregated)
    _collect_from_categories(cfg, session, aggregated)

    entries = sorted(aggregated.items(), key=lambda pair: (pair[1], pair[0]))

    urls = [url for url, _ in entries]
    earliest: Optional[date] = None
    latest: Optional[date] = None
    UEA_META.clear()
    for url, dt in entries:
        if dt:
            d = dt.date()
            if earliest is None or d < earliest:
                earliest = d
            if latest is None or d > latest:
                latest = d
        UEA_META[url] = {"published": dt}

    return URLCollectionResult(
        urls=urls,
        feed_initial=len(urls),
        archive_initial=0,
        rest_initial=0,
        feed_used=len(urls),
        archive_used=0,
        rest_used=0,
        duplicates_removed=0,
        out_of_range_skipped=0,
        earliest_date=earliest,
        latest_date=latest,
    )


def _extract_article_paragraphs(article: BeautifulSoup) -> List[str]:
    paragraphs: List[str] = []
    for iframe in article.find_all("iframe"):
        src = iframe.get("src")
        if src:
            paragraphs.append(f"[Embed] {src}")
    for node in article.find_all(["p", "li", "blockquote", "h2", "h3"]):
        text = base_clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        paragraphs.append(text)
    return paragraphs


def _extract_categories(soup: BeautifulSoup) -> List[str]:
    crumbs = [base_clean_text(li.get_text(" ", strip=True)) for li in soup.select("nav.ipsBreadcrumb li")]
    filtered: List[str] = []
    skip_tokens = {"Hejmo", "Ĉiu aktivado", "Artikoloj", "Artikola fluo", ""}
    title_el = soup.find("h1", class_="ipsType_pageTitle")
    title_text = base_clean_text(title_el.get_text(" ", strip=True)) if title_el else None
    for crumb in crumbs:
        if crumb in skip_tokens:
            continue
        if title_text and crumb == title_text:
            continue
        if crumb not in filtered:
            filtered.append(crumb)
    return filtered


def _extract_author(soup: BeautifulSoup) -> Optional[str]:
    author_box = soup.select_one(".gastautoraj-detaloj")
    if author_box:
        primary = author_box.get_text("\n", strip=True).split("\n", 1)[0]
        return base_clean_text(primary)
    meta_author = soup.select_one(".ipsType_author")
    if meta_author:
        return base_clean_text(meta_author.get_text(" ", strip=True))
    return None


def _extract_audio_links(article: BeautifulSoup) -> List[str]:
    links = set()
    for el in article.find_all(["audio", "source", "a"]):
        href = el.get("src") or el.get("href")
        if not href:
            continue
        lower = href.lower()
        if "mp3" in lower or "audio" in lower:
            links.add(href)
    return sorted(links)


def fetch_article(url: str, cfg: ScrapeConfig, session: Optional[requests.Session] = None) -> Article:
    cfg.normalize()
    sess = session or _session(cfg)
    resp = sess.get(url, timeout=cfg.timeout_sec)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "lxml")

    title_el = soup.find("h1", class_="ipsType_pageTitle")
    title = base_clean_text(title_el.get_text(" ", strip=True) if title_el else url)

    article_el = soup.select_one("article.artikolo") or soup.select_one("article")
    if not article_el:
        raise ValueError(f"article content not found: {url}")

    paragraphs = _extract_article_paragraphs(article_el)
    content_text = "\n\n".join(paragraphs)
    if not content_text:
        fallback = base_clean_text(article_el.get_text(" ", strip=True))
        content_text = fallback

    published: Optional[datetime] = None
    meta_time = soup.find("time", attrs={"itemprop": "datePublished"}) or soup.find("time")
    if meta_time and meta_time.get("datetime"):
        published = _parse_iso_datetime(meta_time["datetime"])
    if not published:
        cached = UEA_META.get(url, {}).get("published")
        if isinstance(cached, datetime):
            published = cached

    author = _extract_author(soup)
    categories = _extract_categories(soup) or None
    audio_links = _extract_audio_links(article_el)

    return Article(
        url=url,
        title=title,
        published=published,
        content_text=content_text,
        author=author,
        categories=categories,
        audio_links=audio_links or None,
    )


__all__ = [
    "collect_urls",
    "fetch_article",
    "shared_session",
    "set_progress_callback",
]
