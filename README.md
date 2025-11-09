# エスペラント記事収集ツール - Streamlit アプリケーション

## 概要

このプロジェクトは、エスペラント語で書かれた記事を複数のウェブサイトから期間指定で収集し、様々なフォーマット（Markdown、テキスト、CSV、JSONL）でダウンロードできるStreamlitベースのWebアプリケーションです。

### 対応サイト

このツールは、以下のエスペラント関連ウェブサイトからの記事収集をサポートしています：

1. **El Popola Ĉinio** (esperanto.china.org.cn) - 中国政府系ポータルのエスペラント版
2. **Global Voices en Esperanto** (eo.globalvoices.org) - 多言語市民メディアのエスペラント版
3. **Monato** (monato.be) - エスペラント月刊誌の公開記事
4. **Scivolemo** (scivolemo.wordpress.com) - 科学読み物ブログ
5. **Pola Retradio** (pola-retradio.org) - ポーランドのエスペラント放送
6. **UEA Facila** (uea.facila.org) - 世界エスペラント協会の記事・動画プラットフォーム
7. **Libera Folio** (liberafolio.org) - エスペラント界のニュースサイト

---

## Streamlit アプリケーション

### 3つのアプリケーションファイル

このプロジェクトには、3つの言語に対応したStreamlitアプリケーションが用意されています：

| ファイル名 | 対応言語 | 起動コマンド |
|-----------|---------|------------|
| [`streamlit_app.py`](streamlit_app.py) | 日本語（デフォルト） | `streamlit run streamlit_app.py` |
| [`streamlit_app_ko.py`](streamlit_app_ko.py) | 韓国語 | `streamlit run streamlit_app_ko.py` |
| [`streamlit_app_eo.py`](streamlit_app_eo.py) | エスペラント | `streamlit run streamlit_app_eo.py` |

**注意**: `streamlit_app_ko.py` と `streamlit_app_eo.py` は、`streamlit_app.py` の薄いラッパーです。メインロジックはすべて `streamlit_app.py` に実装されており、言語固有のラッパーはUIの表示言語を切り替えるだけです。

---

## 主要機能

### 1. 多言語対応UI

アプリケーションは3つの言語で完全にローカライズされています：

- **日本語 (ja)**: デフォルト言語
- **韓国語 (ko)**: 韓国語話者向け
- **エスペラント (eo)**: エスペラント話者向け

UIの言語は、アプリケーション内のセレクトボックスで動的に切り替えることができ、選択した言語はURLクエリパラメータ（`?lang=ja`など）に反映されます。

### 2. サイト選択

ドロップダウンメニューから収集対象のサイトを選択できます。各サイトには以下の情報が表示されます：

- **サイト説明**: サイトの概要と特徴
- **ベースURL**: サイトのベースアドレス
- **対応収集方法**: サイトごとに最適な収集方式

### 3. 期間指定

カレンダーUIで、記事の収集期間を指定できます：

- **開始日**: 収集開始日（各サイトで最小サポート日が異なります）
- **終了日**: 収集終了日（通常は今日まで）
- **サイト別の最小日付**:
  - El Popola Ĉinio: 2005年1月1日以降
  - Global Voices: 2006年1月1日以降
  - Monato: 2000年1月1日以降
  - Scivolemo: 2017年1月1日以降
  - Pola Retradio: 2011年1月1日以降
  - UEA Facila: 2017年1月1日以降
  - Libera Folio: 2003年1月1日以降（WordPress REST API ベース）

### 4. 収集方法の選択

サイトによって、以下の収集方法が選択可能です：

| 収集方法 | 説明 |
|---------|------|
| `auto` | 自動選択（REST API → Feed → Archive の順で試行） |
| `rest` | WordPress REST API を使用（高速・正確） |
| `feed` | RSS/Atom フィードから収集 |
| `archive` | 月別アーカイブページをクロール |
| `both` | Feed と Archive を併用 |

**注意**: サイトによっては固定の収集方法のみ対応している場合があります。El Popola ĈinioとMonatoは独自の収集方式（それぞれnode_*.htmページ、年次インデックスページからの収集）を使用し、Scivolemoは `feed` のみに対応しています。

### 5. 詳細オプション

#### リクエスト間隔（Throttle）

サーバーへの負荷を軽減するため、リクエスト間の待機時間を0.0〜5.0秒の範囲で設定できます。各サイトにはデフォルト値が設定されています：

- El Popola Ĉinio: 1.0秒
- Global Voices: 0.5秒
- Monato: 1.0秒
- Scivolemo: 0.5秒
- Pola Retradio: 1.0秒
- UEA Facila: 0.5秒

#### ページ送りの上限

一部のサイトでは、フィードやアーカイブのページ送り回数を制限できます：

- 0を指定すると無制限（デフォルト）
- 1以上を指定すると、その回数までページをクロール

**対応サイト**: Global Voices、Pola Retradio、UEA Facila、El Popola Ĉinio、Libera Folio

#### 音声・埋め込みリンクの取得

一部のサイトでは、記事内の音声ファイル（MP3など）や埋め込みコンテンツのリンクを抽出できます：

- **対応サイト**: Pola Retradio、UEA Facila

### 6. 収集実行

「収集を実行する」ボタンをクリックすると、以下の処理が実行されます：

1. **URL収集フェーズ**:
   - 指定された収集方法で記事URLを収集
   - 進捗状況がスピナーで表示
   - 収集統計（REST/Feed/Archive別の初期取得数と最終使用数、重複除去数、範囲外除外数）を表示

2. **本文取得フェーズ**:
   - 収集したURLから記事本文を取得
   - プログレスバーで進捗を表示（例: `記事を取得中... 15/42`）
   - 取得失敗したURLは別途記録

3. **結果表示**:
   - 取得成功した記事数を表示
   - 取得失敗したURLリスト（展開可能）
   - 記事一覧をDataFrame形式で表示（公開日、タイトル、URL、著者、カテゴリ）

### 7. エクスポート機能

収集した記事は、以下の4つのフォーマットで個別にダウンロードできます：

#### Markdown形式 (`.md`)

```markdown
---
source: "サイト名"
generated_at: "2025-10-31T12:34:56+00:00"
generator: "retradio_lib.py"
time_range: "2025-01-01 – 2025-01-31"
---

# 記事タイトル

**Published:** 2025-01-15
**URL:** https://example.com/article
**Author:** 著者名
**Categories:** カテゴリ1, カテゴリ2
**Audio:** https://example.com/audio1.mp3 （音声リンクがある場合のみ）

記事本文...

---
```

#### テキスト形式 (`.txt`)

```
記事タイトル
[2025-01-15]
https://example.com/article

記事本文...

--------------------------------------------------------------------------------
```

#### CSV形式 (`.csv`)

| url | title | published | author | categories | audio_links |
|-----|-------|-----------|--------|------------|-------------|
| https://... | タイトル | 2025-01-15T10:00:00 | 著者 | cat1,cat2 | url1,url2 |

#### JSONL形式 (`.jsonl`)

```jsonl
{"url": "https://...", "title": "タイトル", "published": "2025-01-15T10:00:00", "content_text": "...", "author": "著者", "categories": ["cat1", "cat2"], "audio_links": null}
```

#### 一括ダウンロード

「全フォーマットを一括ダウンロード」ボタンをクリックすると、上記4つのフォーマットすべてを含むZIPファイルがダウンロードされます。

---

## アーキテクチャ

### ファイル構成

```
.
├── streamlit_app.py           # メインアプリケーション（日本語）
├── streamlit_app_ko.py        # 韓国語ラッパー
├── streamlit_app_eo.py        # エスペラントラッパー
├── retradio_lib.py            # 共通スクレイピングライブラリ
├── requirements.txt           # Python依存パッケージ
├── El Popola Ĉinio/
│   └── elpopola_lib.py       # El Popola Ĉinio専用スクレイパー
├── Monato/
│   └── monato_lib.py         # Monato専用スクレイパー
├── Uea_Facila/
│   └── uea_facila_lib.py     # UEA Facila専用スクレイパー
├── Global Voices en Esperanto/  # retradio_libを使用
├── Scivolemo/                   # retradio_libを使用
└── Pola Retradio/              # retradio_libを使用
```

### コア技術スタック

#### フロントエンド
- **Streamlit** (v1.37.0+): インタラクティブなWebアプリケーションフレームワーク
- **Pandas** (v2.2.2+): データ表示とDataFrame操作

#### バックエンド
- **Requests** (v2.31.0+): HTTP通信
- **Requests-Cache** (v1.2.0+): HTTPキャッシュ（オプション、12時間有効）
- **BeautifulSoup4** (v4.12.3+): HTML解析
- **lxml** (v5.2.2+): 高速HTMLパーサー
- **FeedParser** (v6.0.11+): RSS/Atom フィード解析
- **DateParser** (v1.2.0+): 多言語日付解析
- **python-dateutil** (v2.9.0+): 日付・時刻処理
- **tqdm** (v4.66.4+): CLIプログレスバー（CLI使用時）

### 主要コンポーネント

#### 1. `streamlit_app.py` - メインアプリケーション

**責務**:
- 多言語UI（日本語、韓国語、エスペラント）の提供
- ユーザー入力の受付と検証
- 6つのサイト設定の管理
- スクレイピングプロセスのオーケストレーション
- 結果の表示とエクスポート

**主要関数**:

- `run_app(lang: str)`: メインUIループ
  - 言語選択とクエリパラメータ同期
  - サイト選択と設定UI
  - 収集実行とプログレス表示
  - 結果レンダリング

- `_build_sources(lang: str)`: サイト設定辞書の構築
  - 各サイトの動的モジュール読み込み
  - サイト固有の設定（URL、収集方法、オプション）

- `render_results(state: Dict)`: 収集結果の表示
  - 統計情報の表示
  - DataFrameテーブルのレンダリング
  - ダウンロードボタンの生成

- `load_module(module_name: str, relative_path: str)`: 動的モジュール読み込み
  - アクセント文字や空白を含むディレクトリ名に対応
  - `importlib.util` を使用した安全な読み込み

**多言語化の実装**:

```python
I18N: Dict[str, Dict[str, str]] = {
    "ja": {"app_title": "🗞️ エスペラント記事 期間収集ツール", ...},
    "ko": {"app_title": "🗞️ 에스페란토 기사 기간 수집 도구", ...},
    "eo": {"app_title": "🗞️ Ilo por kolekti artikolojn en Esperanto", ...},
}

def _t(lang: str, key: str, **kwargs) -> str:
    """翻訳テキストを取得し、必要に応じてフォーマット"""
    text = I18N.get(lang, I18N["ja"]).get(key, key)
    return text.format(**kwargs) if kwargs else text
```

**セッション状態管理**:

```python
st.session_state["lang"]         # 現在の表示言語
st.session_state["last_result"]  # 最後の収集結果（再描画時に再利用）
```

#### 2. `retradio_lib.py` - 共通スクレイピングライブラリ

**責務**:
- WordPress系サイト（Global Voices、Scivolemo、Pola Retradio）の汎用スクレイパー
- 3つの収集方法（REST API、Feed、Archive）の実装
- 記事本文の抽出とクリーニング
- エクスポート機能（Markdown、TXT、CSV、JSONL）

**主要データクラス**:

```python
@dataclass
class ScrapeConfig:
    base_url: str                      # サイトのベースURL
    start_date: date                   # 収集開始日
    end_date: date                     # 収集終了日
    throttle_sec: float                # リクエスト間隔（秒）
    max_pages: Optional[int]           # ページ送り上限（None で無制限）
    method: str                        # "auto" | "rest" | "feed" | "archive" | "both"
    categories: Optional[List[str]]    # カテゴリフィルタ（現在未使用、将来の拡張用）
    timezone: str                      # タイムゾーン（デフォルト: "Europe/Warsaw"）
    use_cache: bool                    # HTTPキャッシュ使用（requests-cache）
    timeout_sec: int                   # HTTPタイムアウト（秒）
    max_retries: int                   # HTTPリトライ回数
    respect_robots: bool               # robots.txt遵守フラグ
    include_audio_links: bool          # 音声リンク取得
    source_label: Optional[str]        # エクスポート時のソースラベル
    feed_url_override: Optional[str]   # フィードURL上書き（自動検出を無効化）

@dataclass
class Article:
    url: str                           # 記事URL
    title: str                         # タイトル
    published: Optional[datetime]      # 公開日時
    content_text: str                  # 本文テキスト
    author: Optional[str]              # 著者
    categories: Optional[List[str]]    # カテゴリ
    audio_links: Optional[List[str]]   # 音声リンク

@dataclass
class URLCollectionResult:
    urls: List[str]                    # 収集したURL（重複除去・範囲フィルタ後）
    feed_initial: int                  # Feed収集の初期取得数
    archive_initial: int               # Archive収集の初期取得数
    rest_initial: int                  # REST API収集の初期取得数
    feed_used: int                     # Feed経由の最終使用数（重複除去・範囲フィルタ後）
    archive_used: int                  # Archive経由の最終使用数（重複除去・範囲フィルタ後）
    rest_used: int                     # REST API経由の最終使用数（重複除去・範囲フィルタ後）
    duplicates_removed: int            # 重複除去数
    out_of_range_skipped: int          # 範囲外除外数
    earliest_date: Optional[date]      # 最も古い公開日
    latest_date: Optional[date]        # 最も新しい公開日

    @property
    def total(self) -> int:            # 総URL数（len(urls)と同じ）
        return len(self.urls)
```

**主要関数**:

- `collect_urls(cfg: ScrapeConfig) -> URLCollectionResult`
  - 設定に基づき最適な収集方法を実行
  - 重複除去とソース優先度管理（REST > Feed > Archive）
  - 日付範囲フィルタリング

- `collect_from_rest(cfg: ScrapeConfig, s: Optional[requests.Session] = None) -> List[Tuple[str, Optional[datetime]]]`
  - WordPress REST API (`/wp-json/wp/v2/posts`) から記事一覧を取得
  - ページネーション対応（100件/ページ）
  - 埋め込みデータ（著者、カテゴリ）の取得
  - 日付範囲クエリによる高速フィルタリング

- `collect_from_feed(cfg: ScrapeConfig, s: Optional[requests.Session] = None) -> List[Tuple[str, Optional[datetime]]]`
  - RSS/Atom フィードの自動検出
  - フィードのページネーション対応
  - FeedEntryDataをキャッシュして後で再利用

- `collect_from_archives(cfg: ScrapeConfig, s: Optional[requests.Session] = None) -> List[Tuple[str, Optional[datetime]]]`
  - `/YYYY/MM/` 形式の月別アーカイブをクロール
  - 月ごとのページ送り対応
  - URLパターンマッチング（WordPress標準構造）

- `fetch_article(url: str, cfg: ScrapeConfig, s: Optional[requests.Session] = None) -> Article`
  - キャッシュからメタデータを取得（可能な場合）
  - HTMLページのスクレイピング
  - タイトル、公開日、本文、著者、カテゴリの抽出
  - 音声リンクの検出（オプション）

**日付解析**:

```python
def _parse_date_any(s: str) -> Optional[datetime]:
    """エスペラント、英語、ポーランド語などの日付を解析"""
    # DateParserで多言語対応
    return dateparser.parse(
        s,
        languages=["eo", "en", "pl", "de", "fr", "es", "it"],
        settings={"DATE_ORDER": "DMY"},
    )
```

**フィード自動検出**:

```python
def _discover_feed_url(cfg, s) -> Optional[str]:
    """
    1. <link rel="alternate" type="application/rss+xml">を検索
    2. フォールバックパス（/feed/, /?feed=rss2, など）を試行
    3. Content-Typeとファイル内容を検証
    """
```

#### 3. サイト固有スクレイパー

##### `elpopola_lib.py` - El Popola Ĉinio

**特徴**:
- 独自HTMLフォーマット（WordPress以前）
- `node_*.htm` ページからURLリストを取得
- 記事URL形式: `/YYYY-MM/DD/content_<id>.htm`

**主要関数**:
- `collect_urls(cfg)`: 複数の `node_*` ページからURLを収集
- `fetch_article(url, cfg, session)`: カスタムHTML構造から記事を抽出

##### `monato_lib.py` - Monato

**特徴**:
- 独自CMS（WordPress以前）
- 年次インデックスページ（`/YYYY/index.php?p`）から収集
- セクション別の記事リスト

**主要関数**:
- `_collect_from_year(year, cfg, session)`: 年次ページから記事一覧を取得
- `collect_urls(cfg)`: 期間内の全年次ページを走査
- `fetch_article(url, cfg, session)`: Monato固有のHTML構造を解析

##### `uea_facila_lib.py` - UEA Facila

**特徴**:
- Invision Community プラットフォーム
- 活動ストリーム (`/malkovri/`) からスクレイピング
- 記事とビデオを含む

**主要関数**:
- `_stream_page_urls(cfg, session)`: ストリームページをページネーション
- `collect_urls(cfg)`: 有効なコンテンツパスをフィルタリング
- `fetch_article(url, cfg, session)`: Invision Community のHTML構造を解析

---

## 使用方法

### インストール

1. **リポジトリのクローン**:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. **依存パッケージのインストール**:
   ```bash
   pip install -r requirements.txt
   ```

### アプリケーションの起動

#### 日本語UI

```bash
streamlit run streamlit_app.py
```

#### 韓国語UI

```bash
streamlit run streamlit_app_ko.py
```

#### エスペラントUI

```bash
streamlit run streamlit_app_eo.py
```

アプリケーションが起動すると、ブラウザが自動的に開き（通常は `http://localhost:8501`）、UIが表示されます。

### 基本的なワークフロー

1. **言語選択**: UIの左上で表示言語を選択（日本語/한국어/Esperanto）

2. **サイト選択**: ドロップダウンメニューから収集対象サイトを選択

3. **期間設定**:
   - 開始日をカレンダーで選択
   - 終了日をカレンダーで選択

4. **収集方法の選択**（サイトによって選択肢が異なります）:
   - `auto`: 自動選択（推奨）
   - `rest`: REST API（高速）
   - `feed`: RSS/Atomフィード
   - `archive`: 月別アーカイブ
   - `both`: FeedとArchiveを併用

5. **オプション設定**:
   - **リクエスト間隔**: サーバー負荷を考慮して調整（デフォルト推奨）
   - **ページ送り上限**: 必要に応じて制限（0で無制限）
   - **音声リンク取得**: 必要な場合はチェック（Pola Retradio、UEA Facila のみ）

6. **収集実行**: 「収集を実行する」ボタンをクリック

7. **結果確認**:
   - 収集統計を確認
   - 記事一覧テーブルをレビュー
   - 失敗URLがあれば展開して確認

8. **ダウンロード**:
   - 個別フォーマット（Markdown、TXT、CSV、JSONL）をダウンロード
   - または、一括ZIPダウンロード

### 使用例

#### 例1: Global Voicesから2025年1月の記事を収集

1. サイト選択: **Global Voices en Esperanto**
2. 開始日: `2025-01-01`
3. 終了日: `2025-01-31`
4. 収集方法: `rest`（または `auto`）
5. リクエスト間隔: `0.5` 秒（デフォルト）
6. 「収集を実行する」をクリック
7. 結果をMarkdown形式でダウンロード

#### 例2: Pola Retradioから音声リンク付きで最近2週間の記事を収集

1. サイト選択: **Pola Retradio**
2. 開始日: `2025-10-17`（今日の2週間前）
3. 終了日: `2025-10-31`（今日）
4. 収集方法: `auto`
5. リクエスト間隔: `1.0` 秒
6. **音声・埋め込みリンクも含める**: ✓（チェック）
7. 「収集を実行する」をクリック
8. JSONL形式でダウンロード（音声リンクを含む）

#### 例3: 複数フォーマットでバックアップ

1. 任意のサイトと期間を選択
2. 収集を実行
3. 「全フォーマットを一括ダウンロード」をクリック
4. ZIPファイルをダウンロード（.md, .txt, .csv, .jsonl を含む）

---

## 技術詳細

### HTMLコンテンツ抽出戦略

#### WordPress系サイト（retradio_lib）

```python
def _extract_main_content(soup: BeautifulSoup) -> str:
    """
    優先順位付きCSSセレクタで本文コンテナを検出:
    1. .entry-content
    2. .post-content
    3. article .entry-content
    4. .et_pb_post_content (Divi/Elegant Themes)
    5. #left-area
    6. article タグ
    """
    # 不要要素の除去: script, style, nav, header, footer, aside
    # 見出し(H1-H4)、段落(P)、リスト(LI)を抽出
```

#### El Popola Ĉinio

```python
# 独自テーブルレイアウト:
# - <td class="text_title">: タイトル
# - <td class="text_author">: 著者と日付
# - <td class="text_content">: 本文
```

#### Monato

```python
# トップレベルテーブル構造:
# - <h1>: タイトル
# - メタ情報（著者、号数、セクション）
# - 本文セル
```

#### UEA Facila

```python
# Invision Community構造:
# - .ipsType_pageTitle: タイトル
# - time[datetime]: 公開日時（ISO 8601 or Unix timestamp）
# - [data-role='commentContent']: 本文
```

### 日付解析の優先順位

1. **構造化データ**:
   - `<time datetime="...">` 属性
   - REST API の `date_gmt` / `date` フィールド
   - Feed の `<published>` / `<updated>` タグ

2. **URL推定**:
   - `/2025/01/15/article-slug/` → 2025-01-15

3. **テキスト解析**:
   - `DateParser` で多言語対応（エスペラント、英語、ポーランド語など）
   - エスペラント月名: "januaro", "februaro", "marto", ...

4. **フォールバック**:
   - 日付が取得できない場合は `None`
   - 範囲フィルタリング時に除外されない

### キャッシュ戦略

#### HTTP キャッシュ（`requests-cache`）

- **有効期間**: 12時間
- **バックエンド**: SQLite (`retradio_cache.sqlite`)
- **対象**: 全てのHTTP GET リクエスト
- **メリット**: 開発時の再実行が高速、サーバー負荷軽減

#### メタデータキャッシュ（インメモリ）

```python
_FEED_ENTRY_CACHE: Dict[str, FeedEntryData] = {}
```

- **用途**: Feed/REST APIから取得したメタデータを保持
- **利点**: `fetch_article()` 時にHTMLを再パースせずメタデータを再利用
- **スコープ**: 各 `collect_urls()` 呼び出しでクリア

### 重複除去とソース優先度

```python
SOURCE_PRIORITY = {"rest": 3, "feed": 2, "archive": 1}
```

同じURLが複数のソースから見つかった場合：

1. **ソース優先度**: REST > Feed > Archive
2. **日付優先**: 同じソースなら、より古い公開日を優先
3. **URL正規化**: 末尾スラッシュの有無を統一

### エラーハンドリング

#### リトライロジック

```python
def _get(s: requests.Session, url: str, cfg: ScrapeConfig) -> requests.Response:
    for i in range(cfg.max_retries):  # デフォルト3回
        try:
            resp = s.get(url, timeout=cfg.timeout_sec)
            if resp.status_code >= 500:
                time.sleep(min(cfg.throttle_sec * (i + 1), 5))
                continue
            return resp
        except Exception as e:
            last_exc = e
            time.sleep(min(cfg.throttle_sec * (i + 1), 5))
    raise last_exc
```

#### Streamlit UI でのエラー表示

```python
try:
    result = source_cfg["collect"](cfg)
except Exception as exc:
    st.error(_t(current_lang, "error_collect_fmt", exc=exc))
    st.stop()
```

### プログレス通知

```python
def set_progress_callback(func: Optional[Callable[[str], None]]) -> None:
    """進捗通知コールバックを登録"""

def _progress(msg: str) -> None:
    """登録されたコールバックに進捗を通知"""
    if _PROGRESS_CB:
        _PROGRESS_CB(msg)
```

Streamlitアプリでは、このコールバックを使用してリアルタイムに進捗を表示できます（現在の実装ではプログレスバーを使用）。

---

## カスタマイズとメンテナンス

### 新しいサイトの追加

新しいエスペラントサイトを追加する手順：

1. **サイト固有ライブラリの作成**（必要な場合）:

   ```python
   # new_site/new_site_lib.py
   from retradio_lib import Article, ScrapeConfig, URLCollectionResult

   def collect_urls(cfg: ScrapeConfig) -> URLCollectionResult:
       # URL収集ロジック
       pass

   def fetch_article(url: str, cfg: ScrapeConfig, session) -> Article:
       # 記事抽出ロジック
       pass

   def shared_session(cfg: ScrapeConfig):
       # セッション作成
       pass

   def set_progress_callback(func):
       # プログレスコールバック設定
       pass
   ```

2. **`streamlit_app.py` の `_build_sources()` に追加**:

   ```python
   def _build_sources(lang: str):
       # 既存のインポート...

       from new_site.new_site_lib import (
           collect_urls as new_collect_urls,
           fetch_article as new_fetch_article,
           shared_session as new_session,
           set_progress_callback as new_set_progress,
       )

       SOURCES["New Site Name"] = {
           "description": DESCRIPTIONS["New Site Name"].get(lang, "..."),
           "base_url": "https://newsite.example.com",
           "collect": new_collect_urls,
           "fetch": new_fetch_article,
           "session": new_session,
           "set_progress": new_set_progress,
           "methods": ["feed"],  # 対応する収集方法
           "default_method": "feed",
           "supports_max_pages": True,
           "include_audio_option": False,
           "throttle_default": 0.5,
           "min_date": date(2020, 1, 1),
           "source_label": "New Site Name (newsite.example.com)",
       }

       return SOURCES
   ```

3. **多言語説明の追加**:

   ```python
   DESCRIPTIONS: Dict[str, Dict[str, str]] = {
       "New Site Name": {
           "ja": "日本語の説明",
           "ko": "韓国語の説明",
           "eo": "エスペラント語の説明",
       },
       # ...
   }
   ```

### UI文言の変更

`streamlit_app.py` の `I18N` 辞書を編集：

```python
I18N: Dict[str, Dict[str, str]] = {
    "ja": {
        "app_title": "新しいタイトル",
        "new_key": "新しい文言",
        # ...
    },
    "ko": {
        "app_title": "새 제목",
        "new_key": "새 문구",
    },
    "eo": {
        "app_title": "Nova titolo",
        "new_key": "Nova frazo",
    },
}
```

### デフォルト設定の変更

各サイトのデフォルト値を調整：

```python
"throttle_default": 1.5,  # リクエスト間隔を1.5秒に
"min_date": date(2015, 1, 1),  # 最小日付を2015年に
```

---

## トラブルシューティング

### よくある問題と解決策

#### 1. URLが全く収集されない

**症状**: 「候補 URL: 0 件」と表示される

**原因**:
- 指定期間に記事が存在しない
- 収集方法が不適切
- サイトの構造変更

**解決策**:
- 期間を広げる（例: 過去3ヶ月）
- 収集方法を変更（`auto` → `feed` → `archive`）
- サイトがアクセス可能か確認（ブラウザで直接開く）

#### 2. 一部の記事が取得できない

**症状**: 「取得できなかった URL」リストに複数のURLが表示される

**原因**:
- サーバーの一時的なエラー
- タイムアウト
- ページ構造が例外的

**解決策**:
- リクエスト間隔を増やす（0.5秒 → 1.5秒）
- タイムアウト設定を増やす（`ScrapeConfig.timeout_sec`）
- 失敗URLを手動で確認

#### 3. Streamlitが起動しない

**症状**: `streamlit: command not found` エラー

**原因**: Streamlitがインストールされていない

**解決策**:
```bash
pip install streamlit>=1.37.0
```

#### 4. モジュールのインポートエラー

**症状**: `ModuleNotFoundError: No module named 'retradio_lib'`

**原因**: Pythonのパスが正しく設定されていない

**解決策**:
- プロジェクトのルートディレクトリで実行していることを確認
- `sys.path` に追加（`streamlit_app.py` は自動的に行います）

#### 5. 日付範囲が正しく機能しない

**症状**: 範囲外の記事が含まれる、または範囲内の記事が除外される

**原因**:
- 記事の日付が正しく解析されていない
- タイムゾーンの問題

**解決策**:
- 収集後の記事リストで公開日を確認
- タイムゾーン設定を確認（`ScrapeConfig.timezone`）
- デバッグログを有効化（`logging.basicConfig(level=logging.DEBUG)`）

#### 6. キャッシュが古い

**症状**: 最新の記事が表示されない

**原因**: HTTP キャッシュが有効（12時間）

**解決策**:
```bash
# キャッシュファイルを削除
rm retradio_cache.sqlite*
```

または、`ScrapeConfig.use_cache = False` に設定

---

## パフォーマンスとベストプラクティス

### 最適な収集方法の選択

| サイト | 推奨方法 | 理由 |
|-------|---------|------|
| Global Voices | `rest` | REST APIが高速・正確 |
| Pola Retradio | `auto` | REST APIが利用可能（自動選択が最適） |
| Scivolemo | `feed` | RSSのみ提供 |
| Monato | `feed` | 独自実装（年次インデックスページから収集） |
| El Popola Ĉinio | `feed` | 独自実装（node_*.htmページから収集） |
| UEA Facila | `feed` | Invision Community固有の活動ストリームから収集 |

### サーバー負荷の軽減

1. **適切なリクエスト間隔**:
   - 小規模サイト（Scivolemo、Monato）: 1.0秒以上
   - 大規模サイト（Global Voices、Pola Retradio）: 0.5秒以上

2. **ページ送り上限の設定**:
   - テスト時: `max_pages=2`（最初の2ページのみ）
   - 本番: `max_pages=0`（無制限）または適切な値

3. **キャッシュの活用**:
   - 開発・デバッグ時は `use_cache=True`（デフォルト）
   - 本番環境では定期的にキャッシュをクリア

### 大量記事の処理

長期間（1年以上）の記事を収集する場合：

1. **期間を分割**:
   - 例: 2023年全体 → 2023年1-6月、2023年7-12月

2. **収集方法の選択**:
   - REST API（`rest`）が最も効率的
   - アーカイブ（`archive`）は月別に分かれるため、長期間に適している

3. **タイムアウトとリトライ**:
   - `timeout_sec` を増やす（30秒 → 60秒）
   - `max_retries` を増やす（3回 → 5回）

### メモリ管理

大量の記事を処理する際のメモリ使用量を抑える方法：

1. **ストリーミング処理**:
   - 記事を一度にメモリに保持せず、逐次処理
   - 現在の実装はすべてメモリに保持するため、超大量データには注意

2. **キャッシュのクリア**:
   ```python
   _FEED_ENTRY_CACHE.clear()  # メタデータキャッシュをクリア
   ```

---

## ライセンスと著作権

### ツール本体

このツールのソースコードは、適切なライセンス（MITなど）の下で配布されています。詳細は `LICENSE` ファイルを参照してください。

### 収集した記事のライセンス

収集した記事のコンテンツは、各サイトの著作権とライセンスに従います：

- **Global Voices**: CC BY 3.0
- **Pola Retradio**: サイトのライセンスを確認
- **Monato**: 有料購読誌の公開記事（利用規約を確認）
- **El Popola Ĉinio**: 政府系メディア（利用規約を確認）
- **Scivolemo**: ブログ記事（著者に確認）
- **UEA Facila**: UEA のライセンスを確認

**重要**: 収集した記事を再配布または商用利用する場合は、必ず各サイトのライセンスと利用規約を確認してください。

---

## 開発者向け情報

### コードスタイル

- **PEP 8** に準拠
- 型ヒント（Type Hints）の使用を推奨
- Docstring（`"""`）で関数の説明を記述

### テスト

現在、自動テストは実装されていません。手動テストの手順：

1. 各サイトで短期間（1週間）のテストを実行
2. 収集数が予想と一致することを確認
3. エクスポートされたファイルの内容を検証
4. エラーログを確認

### デバッグモード

詳細なログを表示するには：

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## 貢献とサポート

### バグ報告

問題を発見した場合は、以下の情報を含めてIssueを作成してください：

- 使用環境（OS、Pythonバージョン、ブラウザ）
- 再現手順
- エラーメッセージまたはスクリーンショット
- 期待される動作

### 機能リクエスト

新機能の提案は歓迎します。以下を含めてください：

- 機能の説明
- ユースケース
- 期待される動作

### プルリクエスト

コードの改善を提案する場合：

1. フォークしてブランチを作成
2. コードを変更
3. テスト（手動でも可）
4. プルリクエストを作成（変更内容の説明を含む）

---

## 謝辞

このプロジェクトは、エスペラントコミュニティの情報アクセスを向上させるために開発されました。以下のライブラリとツールに感謝します：

- **Streamlit**: 直感的なWebアプリケーションフレームワーク
- **BeautifulSoup4**: 柔軟なHTML解析
- **Requests**: シンプルで強力なHTTPライブラリ
- **FeedParser**: RSS/Atom フィード解析
- **DateParser**: 多言語日付解析

そして、エスペラントのコンテンツを提供してくださっている全てのサイト運営者と著者の皆様に感謝します。

---

## 変更履歴

### v1.0.0 (2025年10月)

- 初期リリース
- 6つのエスペラントサイト対応
- 多言語UI（日本語、韓国語、エスペラント）
- 4つのエクスポート形式（Markdown、TXT、CSV、JSONL）
- REST API、Feed、Archiveの3つの収集方法

---

## まとめ

このStreamlitアプリケーションは、エスペラント語の記事を効率的に収集・管理するための包括的なツールです。主な特徴：

- **多サイト対応**: 6つの主要エスペラントサイトをサポート
- **多言語UI**: 日本語、韓国語、エスペラントで利用可能
- **柔軟な収集**: REST API、Feed、Archiveの複数の収集方法
- **豊富なエクスポート**: Markdown、TXT、CSV、JSONL形式で出力
- **ユーザーフレンドリー**: 直感的なWebインターフェース
- **拡張可能**: 新しいサイトやフォーマットの追加が容易

エスペラント学習者、研究者、アーカイビストなど、様々なユーザーのニーズに対応する設計となっています。

**ぜひお試しください！**
