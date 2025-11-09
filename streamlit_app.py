"""
Streamlit アプリ（多言語対応）: エスペラント記事サイト（6媒体）を期間指定で収集し、各種フォーマットでダウンロード
起動:
    streamlit run streamlit_app.py
他言語版（薄いラッパ）:
    streamlit run streamlit_app_ko.py  # 韓国語
    streamlit run streamlit_app_eo.py  # エスペラント
"""
from __future__ import annotations

import io
import os
import re
import sys
import time
import zipfile
import importlib.util
from datetime import date, timedelta, datetime
from typing import Dict, Any

import pandas as pd
import streamlit as st

from retradio_lib import (
    ScrapeConfig,
    collect_urls as retradio_collect_urls,
    fetch_article as retradio_fetch_article,
    _session as retradio_session,
    set_progress_callback as retradio_set_progress,
    to_markdown,
    to_text,
    to_csv,
    to_jsonl,
)


# ---------------------------------------------------------------------------
# i18n strings
# ---------------------------------------------------------------------------
I18N: Dict[str, Dict[str, str]] = {
    "ja": {
        "page_title": "エスペラント記事 期間収集ツール",
        "app_title": "🗞️ エスペラント記事 期間収集ツール（単独コア）",
        "select_site": "対象サイトを選択",
        "site_desc": "サイト説明",
        "base_url": "ベース URL",
        "start": "開始日",
        "end": "終了日",
        "method": "収集方法",
        "method_help": "サイトによって最適な方式が異なります。",
        "method_fixed_fmt": "収集方法: `{method}`（固定）",
        "throttle": "リクエスト間隔（秒）",
        "max_pages": "ページ送りの上限（0 で既定値）",
        "include_audio": "音声・埋め込みリンクも含める",
        "run": "収集を実行する",
        "language_select": "表示言語",
        "spinner_collect": "URL を収集中...",
        "error_collect_fmt": "URL 収集でエラーが発生しました: {exc}",
        "candidates_fmt": "候補 URL: {n} 件",
        "counts_fmt": (
            "rest {rest_used}/{rest_initial}, feed {feed_used}/{feed_initial}, "
            "archive {archive_used}/{archive_initial}, duplicates removed {dups}, "
            "out-of-range skipped {skipped}"
        ),
        "date_range_fmt": "推定公開日範囲: {earliest} ～ {latest}",
        "no_urls": "候補 URL が見つかりませんでした。期間や方法を変更して再度お試しください。",
        "progress_fetch": "本文を取得中...",
        "extracted_fmt": "抽出完了: {n} 本",
        "failures": "取得できなかった URL",
        "no_arts": "期間内の記事は見つかりませんでした。",
        "col_published": "公開日",
        "col_title": "タイトル",
        "col_url": "URL",
        "col_author": "著者",
        "col_categories": "カテゴリ",
        "dl_md": "📄 Markdown をダウンロード",
        "dl_txt": "🗒️ TXT をダウンロード",
        "dl_csv": "🧾 CSV をダウンロード",
        "dl_jsonl": "🧰 JSONL をダウンロード",
        "dl_all": "📦 全フォーマットを一括ダウンロード",
        "params_changed": "入力内容が変更されています。最新の条件で再度「収集を実行する」を押してください。",
        "ready": "開始日・終了日とオプションを選び、「収集を実行する」を押してください。",
    },
    "ko": {
        "page_title": "에스페란토 기사 기간 수집 도구",
        "app_title": "🗞️ 에스페란토 기사 기간 수집 도구 (단일 코어)",
        "select_site": "대상 사이트를 선택하세요",
        "site_desc": "사이트 설명",
        "base_url": "기본 URL",
        "start": "시작일",
        "end": "종료일",
        "method": "수집 방법",
        "method_help": "사이트마다 최적의 수집 방식이 다릅니다.",
        "method_fixed_fmt": "수집 방법: `{method}` (고정)",
        "throttle": "요청 간 간격(초)",
        "max_pages": "페이지 넘김 상한 (0=기본값 사용)",
        "include_audio": "오디오·임베드 링크도 포함",
        "run": "수집 실행하기",
        "language_select": "표시 언어",
        "spinner_collect": "URL을 수집하는 중입니다...",
        "error_collect_fmt": "URL 수집 중 오류가 발생했습니다: {exc}",
        "candidates_fmt": "후보 URL: {n}건",
        "counts_fmt": (
            "REST {rest_used}/{rest_initial}, feed {feed_used}/{feed_initial}, "
            "archive {archive_used}/{archive_initial}, 중복 제거 {dups}, "
            "기간 외 제외 {skipped}"
        ),
        "date_range_fmt": "추정 공개일 범위: {earliest} ~ {latest}",
        "no_urls": "후보 URL이 없습니다. 기간이나 방식을 바꿔 다시 시도하세요.",
        "progress_fetch": "본문을 가져오는 중...",
        "extracted_fmt": "추출 완료: {n}건",
        "failures": "가져오지 못한 URL",
        "no_arts": "기간 내에 수집된 본문이 없습니다.",
        "col_published": "공개일",
        "col_title": "제목",
        "col_url": "URL",
        "col_author": "작성자",
        "col_categories": "카테고리",
        "dl_md": "📄 Markdown 다운로드",
        "dl_txt": "🗒️ TXT 다운로드",
        "dl_csv": "🧾 CSV 다운로드",
        "dl_jsonl": "🧰 JSONL 다운로드",
        "dl_all": "📦 모든 형식을 한 번에 다운로드",
        "params_changed": "입력 값이 바뀌었습니다. 최신 조건으로 다시 \"수집 실행하기\" 버튼을 눌러 주세요.",
        "ready": "시작일·종료일과 옵션을 고른 뒤 \"수집 실행하기\" 버튼을 눌러 주세요.",
    },
    "eo": {
        "page_title": "Ilo por kolekti artikolojn en Esperanto",
        "app_title": "🗞️ Ilo por kolekti artikolojn en Esperanto (unukerna)",
        "select_site": "Elektu celan retejon",
        "site_desc": "Priskribo de retejo",
        "base_url": "Baza URL",
        "start": "Komenca dato",
        "end": "Fina dato",
        "method": "Kolekta metodo",
        "method_help": "La plej taŭga metodo varias laŭ retejo.",
        "method_fixed_fmt": "Kolekta metodo: `{method}` (fiksa)",
        "throttle": "Intertempo inter petoj (sek.)",
        "max_pages": "Maks. paĝoj por paĝumo (0 = defaŭlta)",
        "include_audio": "Inkluzivi ankaŭ sonajn/enkorpigitajn ligilojn",
        "run": "Lanĉi kolekton",
        "language_select": "Lingvo",
        "spinner_collect": "Kolektante URL-ojn...",
        "error_collect_fmt": "Eraro dum kolektado de URL-oj: {exc}",
        "candidates_fmt": "Kandidat-URL-oj: {n}",
        "counts_fmt": (
            "rest {rest_used}/{rest_initial}, feed {feed_used}/{feed_initial}, "
            "archive {archive_used}/{archive_initial}, forigitaj duplikatoj {dups}, "
            "ekskluditaj ekster periodo {skipped}"
        ),
        "date_range_fmt": "Proksimuma publikiga intervalo: {earliest} – {latest}",
        "no_urls": "Neniuj kandidat-URL-oj trovitaj. Ŝanĝu periodon aŭ metodon kaj reprovu.",
        "progress_fetch": "Elŝutante ĉeftekstojn...",
        "extracted_fmt": "Pretigita: {n} artikoloj",
        "failures": "Ne akiritaj URL-oj",
        "no_arts": "Neniuj artikoloj trovitaj en la intervalo.",
        "col_published": "publikigita",
        "col_title": "titolo",
        "col_url": "URL",
        "col_author": "aŭtoro",
        "col_categories": "kategorioj",
        "dl_md": "📄 Elŝuti Markdown",
        "dl_txt": "🗒️ Elŝuti TXT",
        "dl_csv": "🧾 Elŝuti CSV",
        "dl_jsonl": "🧰 Elŝuti JSONL",
        "dl_all": "📦 Elŝuti ĉiujn formatojn kune",
        "params_changed": "La enigoj ŝanĝiĝis. Bonvolu re-premi ‘Lanĉi kolekton’ kun la novaj agordoj.",
        "ready": "Elektu datojn kaj opciojn, poste alklaku ‘Lanĉi kolekton’.",
    },
}


def _t(lang: str, key: str, **kwargs) -> str:
    text = I18N.get(lang, I18N["ja"]).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


# ---------------------------------------------------------------------------
# 動的モジュールの読み込み
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load_module(module_name: str, relative_path: str):
    """アクセントや空白を含むディレクトリのモジュールを動的に読み込む。"""
    full_path = os.path.join(ROOT, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, full_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load module {module_name} from {full_path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec for dataclass/type resolution
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "El Popola Ĉinio": {
        "ja": "中国政府系ポータルのエスペラント版。独自HTML構造のためカスタムスクレイパーを使用します。",
        "ko": "중국 정부계 포털의 에스페란토판입니다. 독자적인 HTML 구조 때문에 전용 스크레이퍼를 사용합니다.",
        "eo": "Esperantlingva versio de ĉina registara portalo. Pro propra HTML-strukturo ni uzas adaptitan skrapilon.",
    },
    "Global Voices en Esperanto": {
        "ja": "Global Voices のエスペラント版（WordPress）。REST API を利用できます。",
        "ko": "WordPress 기반의 Global Voices 에스페란토판입니다. REST API를 사용할 수 있습니다.",
        "eo": "Esperantlingva versio de Global Voices (WordPress). Eblas uzi la REST-API-on.",
    },
    "Monato": {
        "ja": "エスペラント月刊誌 MONATO の一般公開記事。サイト独自HTMLを解析します。",
        "ko": "에스페란토 월간지 MONATO의 공개 기사입니다. 사이트 고유 HTML을 파싱합니다.",
        "eo": "Publikaj artikoloj el la esperantlingva monata revuo MONATO. Ni analizas la propran HTML-strukturon de la retejo.",
    },
    "Scivolemo": {
        "ja": "科学読み物ブログ Scivolemo（WordPress.com）。最近は新規記事が少なく、RSSのみ提供。",
        "ko": "과학 읽을거리 블로그 Scivolemo(WordPress.com)입니다. 최근에는 신규 글이 적으며 RSS만 제공합니다.",
        "eo": "Scienca blogo Scivolemo (WordPress.com). Lastatempe malmultaj artikoloj, disponeblas nur RSS.",
    },
    "Pola Retradio": {
        "ja": "ポーランドのエスペラント放送『Pola Retradio』。REST/RSS/アーカイブ選択可。",
        "ko": "폴란드의 에스페란토 방송 'Pola Retradio'입니다. REST/RSS/아카이브 방식을 선택할 수 있습니다.",
        "eo": "La pola esperantlingva elsendservo 'Pola Retradio'. Elektebla inter REST/RSS/arkivo.",
    },
    "UEA Facila": {
        "ja": "UEA.facila.org の記事・動画。Invision Community ベースのカスタムスクレイパーを使用します。",
        "ko": "UEA.facila.org의 기사와 동영상입니다. Invision Community 기반이라 맞춤형 스크레이퍼를 사용합니다.",
        "eo": "Artikoloj kaj filmetoj el UEA.facila.org. Baziĝas sur Invision Community, tial ni uzas adaptitan skrapilon.",
    },
    "Libera Folio": {
        "ja": "エスペラント界のニュースサイト Libera Folio（多くは WordPress）。REST/RSS/アーカイブ対応。",
        "ko": "에스페란토계 뉴스 사이트 Libera Folio(대부분 WordPress). REST/RSS/아카이브 지원.",
        "eo": "Novaĵretejo pri la Esperantujo, Libera Folio (WordPress). Subtenas REST/RSS/arkivon.",
    },
}


def _build_sources(lang: str):
    """サイトごとの設定辞書を構築して返す。"""
    elpopola_module = load_module("elpopola_lib", os.path.join("El Popola Ĉinio", "elpopola_lib.py"))
    from Monato.monato_lib import (
        collect_urls as monato_collect_urls,
        fetch_article as monato_fetch_article,
        shared_session as monato_session,
        set_progress_callback as monato_set_progress,
    )
    from Uea_Facila.uea_facila_lib import (
        collect_urls as uea_collect_urls,
        fetch_article as uea_fetch_article,
        shared_session as uea_session,
        set_progress_callback as uea_set_progress,
    )

    SOURCES: Dict[str, Dict[str, Any]] = {
        "El Popola Ĉinio": {
            "description": DESCRIPTIONS["El Popola Ĉinio"].get(lang, DESCRIPTIONS["El Popola Ĉinio"]["ja"]),
            "base_url": "http://esperanto.china.org.cn",
            "collect": elpopola_module.collect_urls,
            "fetch": elpopola_module.fetch_article,
            "session": elpopola_module.shared_session,
            "set_progress": elpopola_module.set_progress_callback,
            "methods": ["feed"],
            "default_method": "feed",
            "supports_max_pages": True,
            "include_audio_option": False,
            "throttle_default": 1.0,
            "min_date": date(2005, 1, 1),
            "source_label": "El Popola Ĉinio (esperanto.china.org.cn)",
        },
        "Global Voices en Esperanto": {
            "description": DESCRIPTIONS["Global Voices en Esperanto"].get(lang, DESCRIPTIONS["Global Voices en Esperanto"]["ja"]),
            "base_url": "https://eo.globalvoices.org",
            "collect": retradio_collect_urls,
            "fetch": retradio_fetch_article,
            "session": retradio_session,
            "set_progress": retradio_set_progress,
            "methods": ["auto", "rest", "feed", "archive", "both"],
            "default_method": "rest",
            "supports_max_pages": True,
            "include_audio_option": False,
            "throttle_default": 0.5,
            "min_date": date(2006, 1, 1),
            "source_label": "Global Voices en Esperanto (eo.globalvoices.org)",
        },
        "Monato": {
            "description": DESCRIPTIONS["Monato"].get(lang, DESCRIPTIONS["Monato"]["ja"]),
            "base_url": "https://www.monato.be",
            "collect": monato_collect_urls,
            "fetch": monato_fetch_article,
            "session": monato_session,
            "set_progress": monato_set_progress,
            "methods": ["feed"],
            "default_method": "feed",
            "supports_max_pages": False,
            "include_audio_option": False,
            "throttle_default": 1.0,
            "min_date": date(2000, 1, 1),
            "source_label": "MONATO (monato.be)",
        },
        "Scivolemo": {
            "description": DESCRIPTIONS["Scivolemo"].get(lang, DESCRIPTIONS["Scivolemo"]["ja"]),
            "base_url": "https://scivolemo.wordpress.com",
            "collect": retradio_collect_urls,
            "fetch": retradio_fetch_article,
            "session": retradio_session,
            "set_progress": retradio_set_progress,
            "methods": ["feed"],
            "default_method": "feed",
            "supports_max_pages": False,
            "include_audio_option": False,
            "throttle_default": 0.5,
            "min_date": date(2017, 1, 1),
            "source_label": "Scivolemo (scivolemo.wordpress.com)",
        },
        "Pola Retradio": {
            "description": DESCRIPTIONS["Pola Retradio"].get(lang, DESCRIPTIONS["Pola Retradio"]["ja"]),
            "base_url": "https://pola-retradio.org",
            "collect": retradio_collect_urls,
            "fetch": retradio_fetch_article,
            "session": retradio_session,
            "set_progress": retradio_set_progress,
            "methods": ["auto", "rest", "both", "feed", "archive"],
            "default_method": "auto",
            "supports_max_pages": True,
            "include_audio_option": True,
            "throttle_default": 1.0,
            "min_date": date(2011, 1, 1),
            "source_label": "Pola Retradio (pola-retradio.org)",
        },
        "UEA Facila": {
            "description": DESCRIPTIONS["UEA Facila"].get(lang, DESCRIPTIONS["UEA Facila"]["ja"]),
            "base_url": "https://uea.facila.org",
            "collect": uea_collect_urls,
            "fetch": uea_fetch_article,
            "session": uea_session,
            "set_progress": uea_set_progress,
            "methods": ["feed"],
            "default_method": "feed",
            "supports_max_pages": True,
            "include_audio_option": True,
            "throttle_default": 0.5,
            "min_date": date(2017, 1, 1),
            "source_label": "UEA Facila (uea.facila.org)",
        },
        "Libera Folio": {
            "description": DESCRIPTIONS["Libera Folio"].get(lang, DESCRIPTIONS["Libera Folio"]["ja"]),
            "base_url": "https://www.liberafolio.org",
            "collect": retradio_collect_urls,
            "fetch": retradio_fetch_article,
            "session": retradio_session,
            "set_progress": retradio_set_progress,
            "methods": ["auto", "rest", "both", "feed", "archive"],
            "default_method": "rest",
            "supports_max_pages": True,
            "include_audio_option": False,
            "throttle_default": 0.5,
            "min_date": date(2003, 1, 1),
            "source_label": "Libera Folio (liberafolio.org)",
        },
    }
    return SOURCES


def run_app(lang: str = "ja") -> None:
    """メイン UI（多言語）。lang は 'ja' | 'ko' | 'eo'。"""
    if "lang" not in st.session_state:
        st.session_state["lang"] = lang

    lang_order = ["ja", "ko", "eo"]
    lang_labels = {"ja": "日本語", "ko": "한국어", "eo": "Esperanto"}
    current_lang = st.session_state["lang"]
    if current_lang not in lang_order:
        current_lang = lang
        st.session_state["lang"] = current_lang

    st.set_page_config(page_title=_t(current_lang, "page_title"), layout="wide")

    qp_value = st.query_params.get("lang")
    if isinstance(qp_value, list):
        qp_lang = qp_value[0] if qp_value else None
    else:
        qp_lang = qp_value
    if qp_lang in lang_order and qp_lang != current_lang:
        st.session_state["lang"] = qp_lang
        st.rerun()
    current_lang = st.session_state["lang"]

    lang_display = [lang_labels[code] for code in lang_order]
    lang_index = lang_order.index(current_lang)
    lang_col, _ = st.columns([1, 4])
    with lang_col:
        selected_label = st.selectbox(
            _t(current_lang, "language_select"),
            options=lang_display,
            index=lang_index,
        )
    selected_lang = lang_order[lang_display.index(selected_label)]
    if selected_lang != current_lang:
        st.session_state["lang"] = selected_lang
        st.query_params["lang"] = selected_lang
        st.rerun()

    current_lang = st.session_state["lang"]

    st.title(_t(current_lang, "app_title"))

    SOURCES = _build_sources(current_lang)

    source_name = st.selectbox(_t(current_lang, "select_site"), list(SOURCES.keys()))
    source_cfg = SOURCES[source_name]

    st.markdown(f"**{_t(current_lang, 'site_desc')}**: {source_cfg['description']}")
    st.caption(f"{_t(current_lang, 'base_url')}: {source_cfg['base_url']}")

    min_supported = source_cfg.get("min_date", date(2000, 1, 1))
    today = date.today()
    default_start = max(min_supported, today - timedelta(days=14))

    col1, col2, col3 = st.columns(3)
    with col1:
        start = st.date_input(
            _t(current_lang, "start"),
            value=default_start,
            min_value=min_supported,
            max_value=today,
        )
    with col2:
        end = st.date_input(
            _t(current_lang, "end"),
            value=today,
            min_value=min_supported,
            max_value=today,
        )
    with col3:
        method_options = source_cfg["methods"]
        if len(method_options) == 1:
            method = method_options[0]
            st.write(_t(current_lang, "method_fixed_fmt", method=method))
        else:
            default_index = method_options.index(source_cfg["default_method"])
            method = st.selectbox(
                _t(current_lang, "method"),
                options=method_options,
                index=default_index,
                help=_t(current_lang, "method_help"),
            )

    throttle = st.slider(
        _t(current_lang, "throttle"),
        min_value=0.0,
        max_value=5.0,
        value=float(source_cfg["throttle_default"]),
        step=0.1,
    )

    max_pages_value = None
    if source_cfg.get("supports_max_pages", False):
        max_pages_input = st.number_input(
            _t(current_lang, "max_pages"),
            min_value=0,
            value=0,
            step=1,
        )
        max_pages_value = None if max_pages_input == 0 else int(max_pages_input)

    include_audio = False
    if source_cfg.get("include_audio_option", False):
        include_audio = st.checkbox(_t(current_lang, "include_audio"), value=True)

    current_signature = (
        source_name,
        start,
        end,
        method,
        float(throttle),
        max_pages_value,
        include_audio,
    )

    def render_results(state: Dict[str, Any]) -> None:
        cfg = state["cfg"]
        arts = state["arts"]

        if state.get("params_signature") and state["params_signature"] != current_signature:
            st.info(_t(current_lang, "params_changed"))

        st.success(_t(current_lang, "candidates_fmt", n=state["total"]))

        if state["has_counts"]:
            counts = state["counts"]
            st.caption(
                _t(
                    current_lang,
                    "counts_fmt",
                    rest_used=counts["rest_used"],
                    rest_initial=counts["rest_initial"],
                    feed_used=counts["feed_used"],
                    feed_initial=counts["feed_initial"],
                    archive_used=counts["archive_used"],
                    archive_initial=counts["archive_initial"],
                    dups=counts["duplicates_removed"],
                    skipped=counts["out_of_range_skipped"],
                )
            )

        if state["earliest_date"] and state["latest_date"]:
            st.caption(
                _t(
                    current_lang,
                    "date_range_fmt",
                    earliest=state["earliest_date"],
                    latest=state["latest_date"],
                )
            )

        st.success(_t(current_lang, "extracted_fmt", n=len(arts)))

        if state["failures"]:
            with st.expander(_t(current_lang, "failures")):
                for failure in state["failures"]:
                    st.write(failure)

        if not arts:
            st.info(_t(current_lang, "no_arts"))
            return

        df = pd.DataFrame(
            [
                {
                    _t(current_lang, "col_published"): (a.published.strftime("%Y-%m-%d") if a.published else ""),
                    _t(current_lang, "col_title"): a.title,
                    _t(current_lang, "col_url"): a.url,
                    _t(current_lang, "col_author"): a.author or "",
                    _t(current_lang, "col_categories"): ", ".join(a.categories or []),
                }
                for a in arts
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

        slug = re.sub(r"[^a-z0-9]+", "_", state["source_name"].lower()).strip("_") or "export"
        start_date = state["start"]
        end_date = state["end"]

        md = to_markdown(arts, cfg)
        txt = to_text(arts)
        csv_str = to_csv(arts)
        jsonl = to_jsonl(arts)

        st.download_button(
            _t(current_lang, "dl_md"),
            md,
            file_name=f"{slug}_{start_date}_{end_date}.md",
            mime="text/markdown",
        )
        st.download_button(
            _t(current_lang, "dl_txt"),
            txt,
            file_name=f"{slug}_{start_date}_{end_date}.txt",
            mime="text/plain",
        )
        st.download_button(
            _t(current_lang, "dl_csv"),
            csv_str,
            file_name=f"{slug}_{start_date}_{end_date}.csv",
            mime="text/csv",
        )
        st.download_button(
            _t(current_lang, "dl_jsonl"),
            jsonl,
            file_name=f"{slug}_{start_date}_{end_date}.jsonl",
            mime="application/json",
        )

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{slug}_{start_date}_{end_date}.md", md.encode("utf-8"))
            archive.writestr(f"{slug}_{start_date}_{end_date}.txt", txt.encode("utf-8"))
            archive.writestr(f"{slug}_{start_date}_{end_date}.csv", csv_str.encode("utf-8"))
            archive.writestr(f"{slug}_{start_date}_{end_date}.jsonl", jsonl.encode("utf-8"))
        zip_buffer.seek(0)

        st.download_button(
            _t(current_lang, "dl_all"),
            zip_buffer.getvalue(),
            file_name=f"{slug}_{start_date}_{end_date}_all.zip",
            mime="application/zip",
        )

    run_clicked = st.button(_t(current_lang, "run"), type="primary")

    result_payload = st.session_state.get("last_result")

    if run_clicked:
        cfg = ScrapeConfig(
            base_url=source_cfg["base_url"],
            start_date=start,
            end_date=end,
            method=method,
            throttle_sec=throttle,
            max_pages=max_pages_value,
            include_audio_links=include_audio,
            use_cache=True,
            source_label=source_cfg["source_label"],
        )

        source_cfg["set_progress"](None)

        try:
            with st.spinner(_t(current_lang, "spinner_collect")):
                result = source_cfg["collect"](cfg)
        except Exception as exc:  # noqa: BLE001
            st.error(_t(current_lang, "error_collect_fmt", exc=exc))
            st.stop()

        urls = result.urls
        if not urls:
            st.warning(_t(current_lang, "no_urls"))
            st.stop()

        arts = []
        session = source_cfg["session"](cfg)
        failures = []
        progress = st.progress(0.0, _t(current_lang, "progress_fetch"))
        for i, url in enumerate(urls, 1):
            try:
                article = source_cfg["fetch"](url, cfg, session)
                if article.published and not (cfg.start_date <= article.published.date() <= cfg.end_date):
                    pass
                else:
                    arts.append(article)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{url} ({exc})")
            finally:
                progress.progress(i / len(urls), f"{_t(current_lang, 'progress_fetch')} {i}/{len(urls)}")
                time.sleep(cfg.throttle_sec)

        def sort_key(article):
            if article.published:
                pub_naive = article.published.replace(tzinfo=None) if article.published.tzinfo else article.published
                return (pub_naive, article.url)
            return (datetime.max, article.url)

        arts.sort(key=sort_key)

        progress.empty()

        if not arts:
            st.info(_t(current_lang, "no_arts"))
            st.stop()

        counts = {
            "rest_used": getattr(result, "rest_used", 0),
            "rest_initial": getattr(result, "rest_initial", 0),
            "feed_used": getattr(result, "feed_used", 0),
            "feed_initial": getattr(result, "feed_initial", 0),
            "archive_used": getattr(result, "archive_used", 0),
            "archive_initial": getattr(result, "archive_initial", 0),
            "duplicates_removed": getattr(result, "duplicates_removed", 0),
            "out_of_range_skipped": getattr(result, "out_of_range_skipped", 0),
        }

        result_payload = {
            "cfg": cfg,
            "arts": arts,
            "failures": failures,
            "has_counts": hasattr(result, "rest_used"),
            "counts": counts,
            "earliest_date": getattr(result, "earliest_date", None),
            "latest_date": getattr(result, "latest_date", None),
            "total": result.total,
            "source_name": source_name,
            "start": start,
            "end": end,
            "params_signature": current_signature,
        }

        st.session_state["last_result"] = result_payload

    if result_payload:
        render_results(result_payload)
    else:
        st.info(_t(current_lang, "ready"))


if __name__ == "__main__":
    run_app("ja")
