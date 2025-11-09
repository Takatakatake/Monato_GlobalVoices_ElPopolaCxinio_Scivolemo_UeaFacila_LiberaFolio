#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MONATO の記事収集を複数プロセスで分割実行し、最後に結合して書き出す CLI。
既存の parallel_scraper.py の手順を踏襲しつつ、サイト情報と出力名を調整。
"""

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Tuple

# 親ディレクトリから shared lib を import できるようにする
HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from retradio_lib import ScrapeConfig, Article, export_all  # noqa: E402
from Monato import monato_lib  # noqa: E402
from Monato.monato_lib import collect_urls, fetch_article, shared_session as _session, set_progress_callback  # noqa: E402
from Monato.scraper import _group_articles  # type: ignore  # noqa: E402

DEFAULT_BASE_URL = "https://www.monato.be"
SOURCE_LABEL = "MONATO (monato.be)"
PREFIX = "monato"


@dataclass
class WorkerArgs:
    index: int
    cfg: ScrapeConfig
    urls: List[str]
    meta: Dict[str, Dict[str, object]]


@dataclass
class WorkerResult:
    index: int
    processed_urls: List[str]
    articles: List[Article]
    failures: List[str]
    timer_fetch: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MONATO 期間指定スクレイパー (並列版)")
    p.add_argument("--start", help="開始日 YYYY-MM-DD")
    p.add_argument("--end", help="終了日 YYYY-MM-DD")
    p.add_argument(
        "--days",
        type=int,
        help="終了日から遡った直近N日間を収集（--end 未指定時は今日を終了日にします）",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=4,
        help="並列実行するワーカー数（期間の分割数、1以上）",
    )
    p.add_argument(
        "--out",
        default="output",
        help="書き出し先ディレクトリ",
    )
    p.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="対象サイトのベース URL",
    )
    p.add_argument(
        "--method",
        default="feed",
        choices=["auto", "rest", "both", "feed", "archive"],
        help="URL収集方法（Monato は feed 推奨）",
    )
    p.add_argument(
        "--throttle",
        type=float,
        default=1.0,
        help="1リクエスト毎の遅延秒数（並列数に応じて適宜調整してください）",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="ページ送りの最大回数（Noneは制限なし）",
    )
    p.add_argument(
        "--include-audio",
        action="store_true",
        help="本文メタに MP3 等の音声リンクも含める",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="requests-cache を使わない（並列実行時は自動で無効化されます）",
    )
    p.add_argument(
        "--feed-url",
        help="RSS/Atom フィード URL を直接指定（非 WordPress サイト向け）",
    )
    p.add_argument(
        "--split-by",
        choices=["none", "year", "month"],
        default="none",
        help="最終的な出力ファイルを年単位または月単位で分割",
    )
    return p.parse_args()


def resolve_date_range(args: argparse.Namespace) -> Tuple[date, date]:
    if args.start is None and args.days is None:
        raise SystemExit("--start もしくは --days の指定が必要です。")
    if args.days is not None and args.start:
        raise SystemExit("--start と --days は同時に指定できません。どちらか一方を使ってください。")
    if args.start:
        if not args.end:
            raise SystemExit("--start を指定する場合は --end も指定してください。")
        start_d = datetime.fromisoformat(args.start).date()
        end_d = datetime.fromisoformat(args.end).date()
    else:
        end_raw = args.end or date.today().isoformat()
        end_d = datetime.fromisoformat(end_raw).date()
        days = args.days if args.days is not None else 30
        if days <= 0:
            raise SystemExit("--days は正の整数で指定してください。")
        start_d = end_d - timedelta(days=days - 1)
    if end_d < start_d:
        raise SystemExit("終了日は開始日以降である必要があります。")
    return start_d, end_d


def worker_task(args: WorkerArgs) -> WorkerResult:
    cfg = args.cfg
    cfg.normalize()

    session = _session(cfg)
    articles: List[Article] = []
    failures: List[str] = []

    if args.meta:
        monato_lib.MONATO_META.clear()
        monato_lib.MONATO_META.update(args.meta)

    timer_start = time.perf_counter()
    for url in args.urls:
        try:
            article = fetch_article(url, cfg, session)
            if article.published and not (cfg.start_date <= article.published.date() <= cfg.end_date):
                continue
            articles.append(article)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{url} ({exc})")
        finally:
            if cfg.throttle_sec > 0:
                time.sleep(cfg.throttle_sec)

    timer_after_fetch = time.perf_counter()
    return WorkerResult(
        index=args.index,
        processed_urls=args.urls,
        articles=articles,
        failures=failures,
        timer_fetch=timer_after_fetch - timer_start,
    )


def _sort_articles(articles: Iterable[Article]) -> List[Article]:
    def sort_key(article: Article):
        if article.published:
            pub_naive = (
                article.published.replace(tzinfo=None)
                if article.published.tzinfo
                else article.published
            )
            return (pub_naive, article.url)
        return (datetime.max, article.url)

    return sorted(articles, key=sort_key)


def main() -> None:
    args = parse_args()
    start_d, end_d = resolve_date_range(args)

    if args.workers <= 0:
        raise SystemExit("--workers には 1 以上の整数を指定してください。")

    cfg_base = ScrapeConfig(
        base_url=args.base_url,
        start_date=start_d,
        end_date=end_d,
        throttle_sec=args.throttle,
        max_pages=args.max_pages,
        method=args.method,
        include_audio_links=args.include_audio,
        use_cache=not args.no_cache,
        source_label=SOURCE_LABEL,
        feed_url_override=args.feed_url,
    )
    set_progress_callback(None)

    timer_collect_start = time.perf_counter()
    url_result = collect_urls(cfg_base)
    total_collect = time.perf_counter() - timer_collect_start

    urls = url_result.urls
    total_urls = len(urls)
    if total_urls == 0:
        print(
            f"[INFO] 並列スクレイプ開始: {start_d} ～ {end_d} "
            f"(workers=0, method={cfg_base.method})"
        )
        print("[INFO] URL が見つかりませんでした。")
        all_articles: List[Article] = []
        overall_failures: List[str] = []
        total_fetch = 0.0
    else:
        actual_workers = min(args.workers, total_urls)
        if actual_workers < args.workers:
            print(f"[INFO] 取得件数に合わせてワーカー数を {actual_workers} に調整しました。")
        if actual_workers > 1 and cfg_base.use_cache:
            cfg_base.use_cache = False
            print("[INFO] 並列実行では requests-cache を無効化しました（SQLite のロック競合回避）。")

        print(
            f"[INFO] 並列スクレイプ開始: {start_d} ～ {end_d} "
            f"(workers={actual_workers}, method={cfg_base.method})"
        )

        def chunk_urls(data: List[str], chunks: int) -> List[List[str]]:
            size, remainder = divmod(len(data), chunks)
            out: List[List[str]] = []
            start = 0
            for idx in range(chunks):
                extra = 1 if idx < remainder else 0
                end = start + size + extra
                out.append(data[start:end])
                start = end
            return [chunk for chunk in out if chunk]

        meta_snapshot = monato_lib.MONATO_META.copy()
        chunks = chunk_urls(urls, actual_workers)
        workers: List[WorkerArgs] = [
            WorkerArgs(index=i, cfg=cfg_base, urls=chunk, meta=meta_snapshot)
            for i, chunk in enumerate(chunks, start=1)
        ]

        results: List[WorkerResult] = []
        total_fetch = 0.0
        overall_failures = []

        if actual_workers == 1:
            results.append(worker_task(workers[0]))
        else:
            with ProcessPoolExecutor(max_workers=actual_workers) as executor:
                future_map = {executor.submit(worker_task, worker): worker for worker in workers}
                for future in as_completed(future_map):
                    worker = future_map[future]
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[ERROR] ワーカー #{worker.index} が失敗: {exc}")
                        raise

        results.sort(key=lambda r: r.index)
        all_articles = []
        for result in results:
            total_fetch += result.timer_fetch
            overall_failures.extend(result.failures)
            all_articles.extend(result.articles)
            print(
                f"[INFO] ワーカー #{result.index}: "
                f"URL {len(result.processed_urls)} 件 | 本文 {len(result.articles)} 本 | "
                f"本文取得 {result.timer_fetch:.1f}s"
            )

    all_articles = _sort_articles(all_articles)
    print(f"[INFO] 抽出完了: {len(all_articles)} 本")
    if url_result.earliest_date and url_result.latest_date:
        print(
            f"[INFO] URL 範囲（推定公開日）: "
            f"{url_result.earliest_date} ～ {url_result.latest_date}"
        )
    print(
        "[INFO] 集計: "
        f"feed {url_result.feed_used}/{url_result.feed_initial} | "
        f"archive {url_result.archive_used}/{url_result.archive_initial} | "
        f"rest {url_result.rest_used}/{url_result.rest_initial} | "
        f"duplicates removed {url_result.duplicates_removed} | "
        f"out-of-range skipped {url_result.out_of_range_skipped}"
    )
    print(f"[INFO] 累計時間: URL収集 {total_collect:.1f}s / 本文取得 {total_fetch:.1f}s")

    if total_urls > 0 and overall_failures:
        print("[WARN] 取得失敗一覧:")
        for fail in overall_failures:
            print(f"  - {fail}")

    groups = _group_articles(all_articles, args.split_by)
    os.makedirs(args.out, exist_ok=True)
    for label, subset in groups:
        if not subset:
            continue
        dates = [a.published.date() for a in subset if a.published]
        chunk_start = min(dates) if dates else start_d
        chunk_end = max(dates) if dates else end_d
        cfg_chunk = replace(cfg_base, start_date=chunk_start, end_date=chunk_end)
        if args.split_by == "none":
            basename = f"{PREFIX}_{cfg_chunk.start_date.isoformat()}_{cfg_chunk.end_date.isoformat()}"
        else:
            safe_label = label.replace("/", "-")
            basename = f"{PREFIX}_{safe_label}"
        paths = export_all(
            subset,
            cfg_chunk,
            args.out,
            basename=basename,
        )
        for kind, path in paths.items():
            if args.split_by == "none":
                print(f"[DONE] {kind.upper()}: {path}")
            else:
                print(f"[DONE] {label} {kind.upper()}: {path}")


if __name__ == "__main__":
    main()
