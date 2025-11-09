# -*- coding: utf-8 -*-
"""
CLI ツール：指定期間に公開された uea.facila.org の記事 URL と本文を収集して書き出し
"""
import argparse
import os
import time
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple

HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
import sys

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from retradio_lib import ScrapeConfig, export_all, set_progress_callback, _session  # noqa: E402
from Uea_Facila.uea_facila_lib import collect_urls, fetch_article  # noqa: E402

DEFAULT_BASE_URL = "https://uea.facila.org"
SOURCE_LABEL = "UEA Facila (uea.facila.org)"
PREFIX = "uea_facila"


def parse_args():
    parser = argparse.ArgumentParser(description="UEA Facila 期間指定スクレイパー")
    parser.add_argument("--start", help="開始日 YYYY-MM-DD")
    parser.add_argument("--end", help="終了日 YYYY-MM-DD")
    parser.add_argument("--days", type=int, help="終了日から遡った直近N日間を収集（--end 未指定時は今日を終了日にします）")
    parser.add_argument("--out", default="output", help="書き出し先ディレクトリ")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="対象サイトのベース URL")
    parser.add_argument("--throttle", type=float, default=1.0, help="1リクエスト毎の遅延秒数")
    parser.add_argument("--max-pages", type=int, default=None, help="ストリームの最大ページ数（None は制限なし）")
    parser.add_argument("--no-cache", action="store_true", help="requests-cache を使わない")
    parser.add_argument(
        "--split-by",
        choices=["none", "year", "month"],
        default="none",
        help="大きな期間を扱う際に出力ファイルを年別または月別で分割",
    )
    return parser.parse_args()


def _group_articles(articles, mode: str) -> List[Tuple[str, list]]:
    if mode == "none":
        return [("all", articles)]

    groups: Dict[str, List] = OrderedDict()
    for art in articles:
        if art.published:
            d = art.published.date()
            if mode == "year":
                key = f"{d.year}"
            else:
                key = f"{d.year}-{d.month:02d}"
        else:
            key = "unknown"
        groups.setdefault(key, []).append(art)
    return list(groups.items())


def main():
    args = parse_args()
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

    cfg = ScrapeConfig(
        base_url=args.base_url,
        start_date=start_d,
        end_date=end_d,
        throttle_sec=args.throttle,
        max_pages=args.max_pages,
        method="feed",  # dummy (not used in custom lib)
        include_audio_links=True,
        use_cache=not args.no_cache,
        source_label=SOURCE_LABEL,
    )

    set_progress_callback(lambda msg: print(msg))
    print(f"[INFO] URL 収集中: {cfg.start_date} ～ {cfg.end_date}")
    timer_start = time.perf_counter()
    result = collect_urls(cfg)
    timer_after_collect = time.perf_counter()
    urls = result.urls
    print(
        "[INFO] 候補 URL: {total} 件 (feed {feed_used}/{feed_initial}, duplicates removed {dups})".format(
            total=result.total,
            feed_used=result.feed_used,
            feed_initial=result.feed_initial,
            dups=result.duplicates_removed,
        )
    )
    if result.earliest_date and result.latest_date:
        print(f"[INFO] URL 範囲（推定公開日）: {result.earliest_date} ～ {result.latest_date}")

    session = _session(cfg)
    articles = []
    failures: List[str] = []
    for i, url in enumerate(urls, 1):
        try:
            print(f"[{i}/{len(urls)}] Fetch: {url}")
            article = fetch_article(url, cfg, session)
            if article.published and not (cfg.start_date <= article.published.date() <= cfg.end_date):
                print(f"  -> skip (date {article.published.date()} is out of range)")
                continue
            articles.append(article)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] 取得失敗: {url} ({exc})")
            failures.append(f"{url} ({exc})")
        finally:
            time.sleep(cfg.throttle_sec)

    def sort_key(art):
        if art.published:
            pub_naive = art.published.replace(tzinfo=None) if art.published.tzinfo else art.published
            return (pub_naive, art.url)
        return (datetime.max, art.url)

    articles.sort(key=sort_key)
    print(f"[INFO] 抽出完了: {len(articles)} 本")
    timer_after_fetch = time.perf_counter()
    print(f"[INFO] 処理時間: URL収集 {timer_after_collect - timer_start:.1f}s / 本文取得 {timer_after_fetch - timer_after_collect:.1f}s / 合計 {timer_after_fetch - timer_start:.1f}s")

    if failures:
        print("[WARN] 取得失敗一覧:")
        for failed in failures:
            print(f"  - {failed}")

    groups = _group_articles(articles, args.split_by)
    os.makedirs(args.out, exist_ok=True)
    if args.split_by == "none":
        basename = f"{PREFIX}_{cfg.start_date.isoformat()}_{cfg.end_date.isoformat()}"
        paths = export_all(articles, cfg, args.out, basename=basename)
        for key, path in paths.items():
            print(f"[DONE] {key.upper()}: {path}")
    else:
        for label, subset in groups:
            if not subset:
                continue
            dates = [a.published.date() for a in subset if a.published]
            chunk_start = min(dates) if dates else cfg.start_date
            chunk_end = max(dates) if dates else cfg.end_date
            chunk_cfg = replace(cfg, start_date=chunk_start, end_date=chunk_end)
            safe_label = label.replace("/", "-")
            basename = f"{PREFIX}_{safe_label}"
            print(f"[INFO] 書き出し中: {label} ({len(subset)} 本, {chunk_start} ～ {chunk_end})")
            paths = export_all(subset, chunk_cfg, args.out, basename=basename)
            for key, path in paths.items():
                print(f"[DONE] {label} {key.upper()}: {path}")


if __name__ == "__main__":
    main()
