# -*- coding: utf-8 -*-
"""
CLI ツール：指定期間に公開された MONATO の記事 URL と本文を収集して書き出し
既存の Pola Retradio スクレイパー実装を踏襲し、サイト情報や出力名だけを調整。
"""
import argparse
import os
import sys
import time
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple

# 親ディレクトリから shared lib を import できるようにする
HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from retradio_lib import ScrapeConfig, export_all  # noqa: E402
from Monato.monato_lib import collect_urls, fetch_article, shared_session as _session, set_progress_callback  # noqa: E402

DEFAULT_BASE_URL = "https://www.monato.be"
SOURCE_LABEL = "MONATO (monato.be)"
PREFIX = "monato"


def parse_args():
    p = argparse.ArgumentParser(description="MONATO 期間指定スクレイパー")
    p.add_argument("--start", help="開始日 YYYY-MM-DD")
    p.add_argument("--end", help="終了日 YYYY-MM-DD")
    p.add_argument("--days", type=int, help="終了日から遡った直近N日間を収集（--end 未指定時は今日を終了日にします）")
    p.add_argument("--out", default="output", help="書き出し先ディレクトリ")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="対象サイトのベース URL")
    p.add_argument("--method", default="feed", choices=["auto","rest","both","feed","archive"], help="URL収集方法（Monato は feed 推奨）")
    p.add_argument("--throttle", type=float, default=1.0, help="1リクエスト毎の遅延秒数")
    p.add_argument("--max-pages", type=int, default=None, help="ページ送りの最大回数（Noneは制限なし）")
    p.add_argument("--include-audio", action="store_true", help="本文メタに MP3 等の音声リンクも含める")
    p.add_argument("--no-cache", action="store_true", help="requests-cache を使わない")
    p.add_argument("--feed-url", help="RSS/Atom フィード URL を直接指定（非 WordPress サイト向け）")
    p.add_argument(
        "--split-by",
        choices=["none", "year", "month"],
        default="none",
        help="大きな期間を扱う際に出力ファイルを年別または月別で分割",
    )
    return p.parse_args()


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
        if key not in groups:
            groups[key] = []
        groups[key].append(art)
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
        method=args.method,
        include_audio_links=args.include_audio,
        use_cache=not args.no_cache,
        source_label=SOURCE_LABEL,
        feed_url_override=args.feed_url,
    )

    set_progress_callback(lambda msg: print(msg))
    print(f"[INFO] URL 収集中: {cfg.start_date} ～ {cfg.end_date} ({cfg.method})")
    timer_start = time.perf_counter()
    result = collect_urls(cfg)
    timer_after_collect = time.perf_counter()
    urls = result.urls
    print(
        "[INFO] 候補 URL: {total} 件 "
        "(rest {rest_used}/{rest_initial}, feed {feed_used}/{feed_initial}, archive {archive_used}/{archive_initial}, "
        "duplicates removed {dups}, out-of-range skipped {skipped})".format(
            total=result.total,
            rest_used=result.rest_used,
            rest_initial=result.rest_initial,
            feed_used=result.feed_used,
            feed_initial=result.feed_initial,
            archive_used=result.archive_used,
            archive_initial=result.archive_initial,
            dups=result.duplicates_removed,
            skipped=result.out_of_range_skipped,
        )
    )
    if result.earliest_date and result.latest_date:
        print(f"[INFO] URL 範囲（推定公開日）: {result.earliest_date} ～ {result.latest_date}")

    s = _session(cfg)
    arts = []
    failures: List[str] = []
    for i, u in enumerate(urls, 1):
        try:
            print(f"[{i}/{len(urls)}] Fetch: {u}")
            a = fetch_article(u, cfg, s)
            if a.published and not (cfg.start_date <= a.published.date() <= cfg.end_date):
                print(f"  -> skip (date {a.published.date()} is out of range)")
                continue
            arts.append(a)
        except Exception as e:
            print(f"[WARN] 取得失敗: {u} ({e})")
            failures.append(f"{u} ({e})")
        finally:
            time.sleep(cfg.throttle_sec)

    def sort_key(a):
        if a.published:
            pub_naive = a.published.replace(tzinfo=None) if a.published.tzinfo else a.published
            return (pub_naive, a.url)
        return (datetime.max, a.url)
    arts.sort(key=sort_key)
    print(f"[INFO] 抽出完了: {len(arts)} 本")
    timer_after_fetch = time.perf_counter()
    print(f"[INFO] 処理時間: URL収集 {timer_after_collect - timer_start:.1f}s / 本文取得 {timer_after_fetch - timer_after_collect:.1f}s / 合計 {timer_after_fetch - timer_start:.1f}s")
    if failures:
        print("[WARN] 取得失敗一覧:")
        for failed in failures:
            print(f"  - {failed}")

    groups = _group_articles(arts, args.split_by)
    os.makedirs(args.out, exist_ok=True)
    if args.split_by == "none":
        basename = f"{PREFIX}_{cfg.start_date.isoformat()}_{cfg.end_date.isoformat()}"
        paths = export_all(arts, cfg, args.out, basename=basename)
        for k, p in paths.items():
            print(f"[DONE] {k.upper()}: {p}")
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
            for k, p in paths.items():
                print(f"[DONE] {label} {k.upper()}: {p}")


if __name__ == "__main__":
    main()
