#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parallel_scraper.py

Pola Retradio の記事収集を複数プロセスで分割実行し、最後に結合して書き出す CLI。
長期間（例: 2011-01-01 ～ 2025-10-20）の処理を複数コアで加速する用途を想定。

使い方（例）:
    python parallel_scraper.py --start 2011-01-01 --end 2025-10-20 --workers 16 --out output_parallel
"""

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Iterable, List, Tuple

HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from retradio_lib import (  # noqa: E402
    ScrapeConfig,
    URLCollectionResult,
    Article,
    collect_urls,
    export_all,
    fetch_article,
    set_progress_callback,
    _session,
)
from scraper import _group_articles


@dataclass
class WorkerArgs:
    index: int
    cfg: ScrapeConfig


@dataclass
class WorkerResult:
    index: int
    start_date: date
    end_date: date
    urls: URLCollectionResult
    articles: List[Article]
    failures: List[str]
    timer_collect: float
    timer_fetch: float


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pola Retradio 期間指定スクレイパー (並列版)"
    )
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
        default="https://pola-retradio.org",
        help="対象サイトのベース URL",
    )
    p.add_argument(
        "--method",
        default="auto",
        choices=["auto", "rest", "both", "feed", "archive"],
        help="URL収集方法（auto は REST API 優先で失敗時にフォールバック）",
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


def split_date_range(start: date, end: date, segments: int) -> List[Tuple[date, date]]:
    total_days = (end - start).days + 1
    segments = max(1, min(segments, total_days))
    base_span = total_days // segments
    remainder = total_days % segments
    result: List[Tuple[date, date]] = []
    current = start
    for idx in range(segments):
        span_days = base_span + (1 if idx < remainder else 0)
        if span_days <= 0:
            continue
        chunk_end = current + timedelta(days=span_days - 1)
        result.append((current, min(chunk_end, end)))
        current = chunk_end + timedelta(days=1)
        if current > end:
            break
    return result


def worker_task(args: WorkerArgs) -> WorkerResult:
    cfg = args.cfg
    cfg.normalize()

    timer_start = time.perf_counter()
    urls = collect_urls(cfg)
    timer_after_collect = time.perf_counter()

    session = _session(cfg)
    articles: List[Article] = []
    failures: List[str] = []

    for url in urls.urls:
        try:
            article = fetch_article(url, cfg, session)
            if article.published:
                pub_date = article.published.date()
                if pub_date < cfg.start_date or pub_date > cfg.end_date:
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
        start_date=cfg.start_date,
        end_date=cfg.end_date,
        urls=urls,
        articles=articles,
        failures=failures,
        timer_collect=timer_after_collect - timer_start,
        timer_fetch=timer_after_fetch - timer_after_collect,
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

    chunks = split_date_range(start_d, end_d, args.workers)
    actual_workers = len(chunks)
    if actual_workers < args.workers:
        print(f"[INFO] 期間が短いためワーカー数を {actual_workers} に調整しました。")

    cfg_base = ScrapeConfig(
        base_url=args.base_url,
        start_date=start_d,
        end_date=end_d,
        throttle_sec=args.throttle,
        max_pages=args.max_pages,
        method=args.method,
        include_audio_links=args.include_audio,
        use_cache=not args.no_cache,
    )
    if actual_workers > 1 and cfg_base.use_cache:
        cfg_base.use_cache = False
        print("[INFO] 並列実行では requests-cache を無効化しました（SQLite のロック競合回避）。")

    set_progress_callback(None)

    print(
        f"[INFO] 並列スクレイプ開始: {start_d} ～ {end_d} "
        f"(workers={actual_workers}, method={cfg_base.method})"
    )

    workers: List[WorkerArgs] = [
        WorkerArgs(
            index=i,
            cfg=replace(
                cfg_base,
                start_date=chunk_start,
                end_date=chunk_end,
            ),
        )
        for i, (chunk_start, chunk_end) in enumerate(chunks, start=1)
    ]

    results: List[WorkerResult] = []
    total_collect = 0.0
    total_fetch = 0.0

    overall_failures: List[str] = []
    combined_stats = dict(
        feed_initial=0,
        archive_initial=0,
        rest_initial=0,
        feed_used=0,
        archive_used=0,
        rest_used=0,
        duplicates_removed=0,
        out_of_range_skipped=0,
    )
    earliest_dates: List[date] = []
    latest_dates: List[date] = []

    if actual_workers == 1:
        result = worker_task(workers[0])
        results.append(result)
    else:
        with ProcessPoolExecutor(max_workers=actual_workers) as executor:
            future_map = {
                executor.submit(worker_task, worker): worker for worker in workers
            }
            for future in as_completed(future_map):
                worker = future_map[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[ERROR] ワーカー #{worker.index} ({worker.cfg.start_date}～{worker.cfg.end_date}) が失敗: {exc}"
                    )
                    raise

    results.sort(key=lambda r: r.index)

    all_articles: List[Article] = []
    for result in results:
        total_collect += result.timer_collect
        total_fetch += result.timer_fetch
        overall_failures.extend(result.failures)
        urls = result.urls
        combined_stats["feed_initial"] += urls.feed_initial
        combined_stats["archive_initial"] += urls.archive_initial
        combined_stats["rest_initial"] += urls.rest_initial
        combined_stats["feed_used"] += urls.feed_used
        combined_stats["archive_used"] += urls.archive_used
        combined_stats["rest_used"] += urls.rest_used
        combined_stats["duplicates_removed"] += urls.duplicates_removed
        combined_stats["out_of_range_skipped"] += urls.out_of_range_skipped
        if urls.earliest_date:
            earliest_dates.append(urls.earliest_date)
        if urls.latest_date:
            latest_dates.append(urls.latest_date)
        all_articles.extend(result.articles)
        print(
            f"[INFO] ワーカー #{result.index}: "
            f"{result.start_date} ～ {result.end_date} | "
            f"URL {len(result.urls.urls)} 件 | 本文 {len(result.articles)} 本 | "
            f"URL収集 {result.timer_collect:.1f}s / 本文取得 {result.timer_fetch:.1f}s"
        )

    all_articles = _sort_articles(all_articles)
    print(f"[INFO] 抽出完了: {len(all_articles)} 本")
    if earliest_dates and latest_dates:
        print(
            f"[INFO] URL 範囲（推定公開日）: "
            f"{min(earliest_dates)} ～ {max(latest_dates)}"
        )
    print(
        "[INFO] 集計: "
        f"feed {combined_stats['feed_used']}/{combined_stats['feed_initial']} | "
        f"archive {combined_stats['archive_used']}/{combined_stats['archive_initial']} | "
        f"rest {combined_stats['rest_used']}/{combined_stats['rest_initial']} | "
        f"duplicates removed {combined_stats['duplicates_removed']} | "
        f"out-of-range skipped {combined_stats['out_of_range_skipped']}"
    )
    print(
        f"[INFO] 累計時間: URL収集 {total_collect:.1f}s / 本文取得 {total_fetch:.1f}s"
    )

    if overall_failures:
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
            basename = None
        else:
            safe_label = label.replace("/", "-")
            basename = f"pola_retradio_{safe_label}"
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
