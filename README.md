# AIエージェントシステム 機能概要ドキュメント

## 目次

1. [システム全体構成](#1-システム全体構成)
2. [MCPサーバ一覧と接続・認証方法](#2-mcpサーバ一覧と接続認証方法)
3. [認証シーケンス](#3-認証シーケンス)
4. [エージェントミドルウェア](#4-エージェントミドルウェア)
5. [StreamlitチャットAIエージェント](#5-streamlitチャットaiエージェント)
6. [AIエージェントのユースケース](#6-aiエージェントのユースケース)
7. [環境構築・起動方法](#7-環境構築起動方法)

---

## 1. システム全体構成

```text
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit UI (app.py)                   │
│            チャットインターフェース / HITL承認UI              │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│              LangGraph Agent (task_agent/)                   │
│   DeepAgent / StructuredAgent / MiddlewareAgent             │
│   モデル: GPT-4o / Claude 3.7 Sonnet (Bedrock)              │
└──────┬───────────┬───────────┬──────────────────────────────┘
       │           │           │ MCP (stdio / Streamable HTTP)
┌──────▼───┐  ┌───▼─────┐  ┌──▼─────────────────────────────┐
│ ローカル  │  │  Local  │  │       Docker MCP Servers        │
│  MCP     │  │  Tools  │  │                                 │
│ (stdio)  │  │(Tavily  │  │  :3333 File Transcriber         │
│BOJ-RAG   │  │ /file/  │  │  :4444 JWT Server               │
│MarketData│  │  SNS)   │  │  :5555 Indicator                │
└──────────┘  └─────────┘  │  :7666 News Search              │
       │                    └─────────────────────────────────┘
┌──────▼──────────────────┐
│ PostgreSQL (:35432)     │
│ チェックポイント / 長期記憶│
└─────────────────────────┘
```

### ディレクトリ構成

```text
py_app/
├── app.py                    # Streamlit UI（メインエントリーポイント）
├── compose.yml               # Docker Compose定義
├── pyproject.toml            # 依存関係定義
├── task_agent/               # エージェント実装
│   ├── deep_agent.py         # DeepAgent（主要・長期記憶対応）
│   ├── structured_agent.py   # 構造化出力エージェント
│   ├── middleware_agent.py   # ミドルウェアスタック実装
│   ├── lmemory_agent.py      # 長期記憶専用実装
│   └── mcp_config.json       # MCP接続設定
├── mcp_server/               # ローカルMCPサーバー（stdio）
│   ├── boj_minutes_rag.py    # 日銀議事要旨RAG
│   └── market_data.py        # 金融市場データ
├── tools/                    # Docker MCPサーバー
│   ├── file_transcriber/     # YouTube文字起こし MCP (:3333)
│   ├── jwt_server/           # JWT認証サーバー (:4444)
│   ├── indicator/            # 経済指標 MCP (:5555)
│   └── news_search/          # ニュース検索 MCP (:7666)
├── lib/
│   ├── tools.py              # ローカルツール初期化
│   ├── database.py           # DB接続
│   └── secrets.py            # シークレット管理
└── db/
    └── boj_rag.sqlite3       # 日銀RAGデータベース
```

---

## 2. MCPサーバ一覧と接続・認証方法

### サーバ一覧

| サーバ名 | エンドポイント | 認証方式 | トランスポート |
| --- | --- | --- | --- |
| BOJ Minutes RAG | `stdio` (ローカル) | なし（プロセス内） | stdio |
| Market Data | `stdio` (ローカル) | なし（プロセス内） | stdio |
| File Transcriber | `http://localhost:3333/mcp` | Static Bearer Token | Streamable HTTP |
| JWT Server | `http://localhost:4444` | RS256 JWT (JWKS) | HTTP (REST) |
| Indicator | `http://localhost:5555/mcp` | JWT Bearer (RS256) | Streamable HTTP |
| News Search | `http://localhost:7666/mcp` | Google OAuth 2.0 | Streamable HTTP |

---

### BOJ Minutes RAG MCP

**役割**: 日本銀行 金融政策決定会合の議事要旨・会見内容をRAG検索

| 項目 | 内容 |
| --- | --- |
| トランスポート | stdio（ローカルプロセス起動） |
| 認証 | なし |
| データストア | SQLite3 (`./db/boj_rag.sqlite3`) |
| 埋め込みモデル | `text-embedding-3-small` (OpenAI) |

**提供機能**:

- 議事要旨のセマンティック検索（ベクトル類似度）
- 会合日付・言語・ソースURLによるフィルタリング

**接続設定**:

```python
"boj-minutes-rag": {
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "-m", "mcp_server.boj_minutes_rag"]
}
```

---

### Market Data MCP

**役割**: グローバル金融市場のリアルタイム・時系列データ取得

| 項目 | 内容 |
| --- | --- |
| トランスポート | stdio（ローカルプロセス起動） |
| 認証 | なし |
| データソース | Yahoo Finance (`yfinance`) |

**提供データ**:

- 株式指数: S&P 500, NASDAQ, Dow Jones, Nikkei 225, TOPIX など
- 為替レート: USD/JPY, EUR/USD など
- 債券利回り: 米国債 2年・10年
- 暗号資産: BTC/USD, ETH/USD

**接続設定**:

```python
"market-data": {
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "-m", "mcp_server.market_data"]
}
```

---

### File Transcriber MCP (:3333)

**役割**: YouTube動画の音声ダウンロード → OpenAI Whisperによる文字起こし

| 項目 | 内容 |
| --- | --- |
| ポート | `3333` |
| トランスポート | Streamable HTTP |
| 認証方式 | Static Bearer Token |
| 依存サービス | OpenAI API, ffmpeg, yt-dlp |

**認証トークン（開発用）**:

| ユーザー | トークン | スコープ |
| --- | --- | --- |
| alice (admin) | `dev-alice-token` | read:data, write:data, admin:tools |
| guest | `dev-guest-token` | read:data |

**接続設定**:

```python
"youtube-transcribe": {
    "transport": "http",
    "url": "http://localhost:3333/mcp",
    "headers": {"Authorization": "Bearer dev-alice-token"}
}
```

**処理フロー**:

```text
YouTube URL → yt-dlp ダウンロード → ffmpeg (16kHz mono MP3)
→ 10分毎にチャンク分割 → OpenAI Whisper API → テキスト結合
```

---

### JWT Server (:4444)

**役割**: RS256 JWTトークンの発行・JWKS公開鍵の提供（Indicator MCPの認証基盤）

| 項目 | 内容 |
| --- | --- |
| ポート | `4444` |
| フレームワーク | Flask |
| 署名アルゴリズム | RS256 (RSA 2048bit) |
| トークン有効期限 | 1時間 |

**エンドポイント**:

| パス | メソッド | 説明 |
| --- | --- | --- |
| `/login` | POST | ユーザー名/パスワード認証 → JWTトークン発行 |
| `/verify` | POST | トークン検証 |
| `/.well-known/jwks.json` | GET | JWKS公開鍵提供 |

**JWTペイロード例**:

```json
{
  "sub": "alice",
  "role": "admin",
  "scopes": ["read:data", "write:data", "admin:tools"],
  "iss": "http://localhost:4444",
  "aud": "your-mcp-server",
  "exp": 1234567890
}
```

---

### Indicator MCP (:5555)

**役割**: Financial Modeling Prep (FMP) APIを通じた経済指標カレンダーの取得

| 項目 | 内容 |
| --- | --- |
| ポート | `5555` |
| トランスポート | Streamable HTTP |
| 認証方式 | JWT Bearer (RS256) |
| JWKS URI | `http://jwt-server:4444/.well-known/jwks.json` |

**認証フロー**:

```text
① POST http://localhost:4444/login  (alice/password)
         ↓ JWT Token 取得
② POST http://localhost:5555/mcp
   Authorization: Bearer <jwt_token>
         ↓ JWKS検証 → アクセス許可
```

**接続設定**:

```python
# ① まずJWTを取得
jwt_token = await get_jwt_token("http://localhost:4444/login", "alice", "password")

# ② Indicatorに接続
"indicator": {
    "transport": "http",
    "url": "http://localhost:5555/mcp",
    "headers": {"Authorization": f"Bearer {jwt_token}"}
}
```

---

### News Search MCP (:7666)

**役割**: NewsAPI.org を通じたニュース記事検索（Google OAuth 2.0認証付き）

| 項目 | 内容 |
| --- | --- |
| ポート | `7666` |
| トランスポート | Streamable HTTP (Stateless) |
| 認証方式 | Google OAuth 2.0 (OAuthProxy) |
| セッション管理 | ステートレス (`stateless_http=True`) |

**OAuth 2.0 フロー (Dynamic Client Registration)**:

```text
① POST /register  → client_id / client_secret 取得 (DCR: RFC 7591)
② GET  /authorize → Googleログイン画面へリダイレクト
③ Googleで認証   → コールバック /auth/callback
④ POST /token    → アクセストークン取得
⑤ POST /mcp      Authorization: Bearer <access_token>
```

**提供ツール**:

| ツール | 説明 |
| --- | --- |
| `search_news` | キーワードによるニュース記事検索 |
| `get_top_headlines` | 国・カテゴリ別トップニュース取得 |
| `search_news_by_date_range` | 日付範囲指定検索 |
| `search_news_by_category` | カテゴリ別ニュース検索 |

---

## 3. 認証シーケンス

### 3.1 Static認証 (Bearer Token)

最も単純な方式。事前に共有した固定トークンをAuthorizationヘッダーに含めて送信。File Transcriberで採用。

**ポイント**:

- 仕組みが単純で実装が容易
- トークンが漏洩した場合は即座に無効化・再発行が必要（HTTPSが必須）

```mermaid
sequenceDiagram
    participant Client as クライアント
    participant MCP as MCPサーバー

    Note over Client, MCP: 事前にトークンを共有済み

    Client->>MCP: リクエスト送信 (Authorization: Bearer dev-alice-token)
    activate MCP

    MCP->>MCP: トークンをストアと照合・スコープ確認

    alt トークンが有効
        MCP->>MCP: リクエストを処理
        MCP-->>Client: レスポンス (200 OK)
    else トークンが無効
        MCP-->>Client: エラーレスポンス (401 Unauthorized)
    end
    deactivate MCP
```

---

### 3.2 JWT (RS256) 認証

クライアントがJWT Serverからトークンを取得し、MCPサーバーはJWKSで署名を検証。Indicatorで採用。

**ポイント**:

- MCPサーバーはステートレスで認証が可能（署名をローカル検証）
- 認証サーバーへの問い合わせ負荷が低い
- 一度発行したトークンは有効期限まで原則無効化できない

```mermaid
sequenceDiagram
    participant Client as クライアント
    participant JWTServer as JWT Server (:4444)
    participant MCP as Indicator MCP (:5555)

    Client->>JWTServer: POST /login (username/password)
    activate JWTServer
    JWTServer->>JWTServer: クレデンシャル検証
    JWTServer->>JWTServer: JWT生成 (RS256秘密鍵で署名)
    JWTServer-->>Client: JWT (アクセストークン) を返却
    deactivate JWTServer

    Note over Client, MCP: 以降、有効期限内はトークンを使い回す

    Client->>MCP: リクエスト送信 (Authorization: Bearer <jwt>)
    activate MCP

    MCP->>JWTServer: GET /.well-known/jwks.json (公開鍵取得・キャッシュ)
    JWTServer-->>MCP: JWKS (公開鍵)

    MCP->>MCP: JWTの署名を検証 (公開鍵を使用)
    MCP->>MCP: クレーム検証 (exp, iss, aud, scopes)

    alt トークンが有効
        MCP->>MCP: リクエストを処理
        MCP-->>Client: レスポンス (200 OK)
    else トークンが無効 (署名不一致・期限切れ)
        MCP-->>Client: エラーレスポンス (401 Unauthorized)
    end
    deactivate MCP
```

---

### 3.3 Google OAuth 2.0 (認可コードフロー + DCR)

ユーザーが介在し、MCPクライアントがGoogleアカウントで認証後にアクセストークンを取得。News Searchで採用。

**ポイント**:

- Dynamic Client Registration (RFC 7591) でクライアントを動的登録
- ユーザーのパスワードをクライアントに渡さずに安全に連携
- スコープで機能アクセスを細かく制御
- FastMCPがOAuthプロキシとして動作（GoogleトークンをFastMCP JWTに変換）

```mermaid
sequenceDiagram
    actor User as ユーザー (ブラウザ)
    participant Client as MCPクライアント
    participant FastMCP as News Search MCP (:7666)
    participant Google as Google OAuth

    Client->>FastMCP: POST /register (DCR: RFC 7591)
    FastMCP-->>Client: client_id / client_secret 発行

    Client->>User: GET /authorize へリダイレクト
    User->>FastMCP: GET /authorize?client_id=...&code_challenge=... (PKCE)
    FastMCP->>User: 同意画面を表示
    User->>FastMCP: 「同意する」をクリック
    FastMCP->>Google: Googleログイン画面へリダイレクト
    User->>Google: Googleアカウントでログイン・同意
    Google-->>FastMCP: コールバック (認可コード)
    FastMCP-->>User: クライアントへリダイレクト (認可コード)

    Client->>FastMCP: POST /token (認可コード + code_verifier)
    FastMCP->>Google: Googleトークンエンドポイントへ転送
    Google-->>FastMCP: Googleアクセストークン
    FastMCP->>FastMCP: FastMCP JWTを発行 (Google Client SecretからPBKDF2で署名鍵導出)
    FastMCP-->>Client: FastMCP アクセストークン (JWT)

    Client->>FastMCP: POST /mcp (Authorization: Bearer <fastmcp_jwt>)
    FastMCP->>FastMCP: JWT検証 → Googleトークンで追加検証
    FastMCP-->>Client: MCPレスポンス (200 OK)
```

---

## 4. エージェントミドルウェア

`middleware_agent.py` に実装されたセキュリティ・制御ミドルウェアスタック（リクエスト処理順）:

```text
リクエスト入力
     ↓
① PIIMiddleware (email)          → 検出時: redact（マスキング）
     ↓
② PIIMiddleware (credit_card)    → 検出時: mask（部分マスク）
     ↓
③ PIIMiddleware (api_key)        → 検出時: block（リクエスト拒否）
   パターン: /sk-[a-zA-Z0-9]{32}/
     ↓
④ PIIMiddleware (ssn)            → 検出時: block（リクエスト拒否）
   カスタム検出関数
     ↓
⑤ ToolCallLimitMiddleware        → スレッド上限: 20回 / 実行上限: 10回
   web_search専用: スレッド5回 / 実行3回
     ↓
⑥ ModelCallLimitMiddleware       → スレッド上限: 10回 / 実行上限: 3回
     ↓
⑦ SummarizationMiddleware        → 4000トークン超過時に自動要約
   モデル: gpt-4o-mini / 保持メッセージ数: 20
     ↓
⑧ HumanInTheLoopMiddleware       → write_file: approve/deny 承認必須
   (HITL)                          web_search: approve/deny 承認必須
                                    read_data:  承認スキップ
     ↓
   LLM / Tool 実行
```

### PII検出戦略

| 戦略 | 動作 | 対象 |
| --- | --- | --- |
| `block` | リクエストを拒否 | SSN, APIキー |
| `redact` | 情報を完全削除・置換 | メールアドレス |
| `mask` | 一部をマスク (`****`) | クレジットカード番号 |
| `hash` | SHA256ハッシュ化 | 任意 |

### オブザーバビリティ (Langfuse)

LLMコール・ツール呼び出し・レスポンスの全トレースをLangfuseに記録。

```python
CallbackHandler(
    public_key=LANGFUSE_PUBLIC_KEY,
    secret_key=LANGFUSE_SECRET_KEY,
    host=LANGFUSE_BASE_URL  # https://cloud.langfuse.com
)
```

---

## 5. StreamlitチャットAIエージェント

### 概要

| 項目 | 内容 |
| --- | --- |
| ファイル | `py_app/app.py` |
| フレームワーク | Streamlit |
| 用途 | 金融市場分析レポートの対話型生成UI |
| 利用モデル | GPT-4o (OpenAI) / Claude 3.7 Sonnet (AWS Bedrock) |
| エージェント | LangGraph DeepAgent (長期記憶・HITL対応) |

### UI構成

```text
┌─────────────────────────────────────────┐
│  チャット入力エリア                       │
│  （ユーザーの質問・指示）                 │
├─────────────────────────────────────────┤
│  エージェント実行ログ（ストリーミング）    │
│  - ツール呼び出し状況                    │
│  - 思考プロセス表示                      │
├─────────────────────────────────────────┤
│  HITL 承認UI（条件付き表示）             │
│  ┌──────────┐  ┌──────────┐            │
│  │ ✅ APPROVE│  │ ❌ DENY  │            │
│  └──────────┘  └──────────┘            │
├─────────────────────────────────────────┤
│  最終レポート表示                         │
│  （MarketAnalysisReport Markdown）       │
└─────────────────────────────────────────┘
```

### セッション管理

| 状態変数 | 型 | 説明 |
| --- | --- | --- |
| `messages` | `list` | チャット履歴 |
| `pending_approval` | `bool` | HITL承認待ち状態 |
| `pending_command` | `Command` | 承認待ちLangGraphコマンド |
| `final_result` | `MarketAnalysisReport` | 最終レポートオブジェクト |

### 出力スキーマ (MarketAnalysisReport)

```python
class MarketAnalysisReport(BaseModel):
    report_id: str                           # 一意ID
    meeting_date: Optional[str]              # 日銀会合日
    created_at: str                          # 作成日時 (JST ISO8601)
    author: Optional[str]                    # 作成者
    summary: str                             # 要約
    top_findings: List[Finding]              # 主要発見事項
    market_snapshot: List[MarketInstrument]  # 市場スナップショット
    charts: Optional[List[str]]              # チャート参照
    recommendations: Optional[List[str]]     # 推奨事項
    sources: List[SourceRef]                 # 出典情報
    overall_confidence: Optional[float]      # 信頼度スコア
    notes: Optional[str]                     # 補足事項
```

### 長期記憶 (PostgreSQL永続化)

| パス | 内容 | スコープ |
| --- | --- | --- |
| `/memories/{id}/user_profile/` | ユーザーの関心・設定 | スレッド横断 |
| `/memories/{id}/conversations/` | 重要な会話履歴 | スレッド横断 |
| `/memories/{id}/knowledge/` | 蓄積された分析知識 | スレッド横断 |

---

## 6. AIエージェントのユースケース

### UC-1: 金融市場分析レポート自動生成

日銀の金融政策決定会合情報と市場データを組み合わせて、構造化レポートを自動生成する。

```text
ユーザー: 「最新の日銀会合について市場への影響を分析してください」
        ↓
① BOJ-RAG検索     → 最新会合の議事要旨・会見内容取得
② Market Data MCP → 株式・為替・債券の現在値取得
③ Indicator MCP   → 直近の経済指標カレンダー確認
④ [HITL] Web検索   → ユーザーが承認した場合のみ追加検索実行
⑤ 構造化出力      → MarketAnalysisReport 生成
        ↓
ユーザー: Markdownレポート受け取り
```

---

### UC-2: Human-in-the-Loop 制御付きレポート保存

生成したレポートをファイルに保存する際に人間の承認を挟む安全なワークフロー。

```text
エージェント: 「レポートを ./filesystem/report_20260221.md に保存します」
           ↓ HITL インターラプト発生
ユーザー:  [✅ APPROVE] または [❌ DENY] を選択
           ↓ APPROVEの場合
ファイル保存実行 → 完了通知
           ↓ DENYの場合
保存をスキップ → 代替対応をユーザーに提案
```

---

### UC-3: YouTube動画の内容分析

日銀総裁会見などのYouTube動画を文字起こしして、内容を分析する。

```text
ユーザー: 「このYouTube URLの発言内容を要約してください: https://...」
        ↓
① File Transcriber MCP (Bearer Token認証)
   → yt-dlp でダウンロード → Whisper文字起こし
② LLMで要約・分析
③ 関連する市場データと照合（オプション）
```

---

### UC-4: 最新ニュースに基づく市場見通し

最新ニュースを取得してマーケットへの影響を分析する。

```text
ユーザー: 「今週の日本経済ニュースから市場への影響を教えて」
        ↓
① News Search MCP (Google OAuth 2.0認証)
   → search_news("日本経済") で直近ニュース取得
② Market Data MCP → 現在の市場価格確認
③ BOJ-RAG → 関連する日銀スタンスと照合
④ レポート生成
```

---

### UC-5: 長期記憶を活用したパーソナライズ分析

過去の会話履歴・ユーザー設定をPostgreSQLに永続化し、継続的なコンテキストを維持する。

```text
1回目: 「私はドル円の動向を重視しています」
       → /memories/{id}/user_profile/ に自動保存

2回目（別セッション）: 「最新のレポートを作って」
       → user_profile を読み込み
       → ドル円を優先したレポート構成で自動生成
```

---

### UC-6: 経済指標カレンダーの先行監視

今後の重要経済指標発表を確認し、事前の市場予測レポートを作成する。

```text
ユーザー: 「今週の重要経済指標と市場への影響予測を教えて」
        ↓
① Indicator MCP (JWT認証)
   → JWT Server からトークン取得
   → 今週の経済カレンダー取得（日本・米国）
② Market Data MCP → 現在の市場水準を確認
③ BOJ-RAG → 過去の同類指標発表時の日銀反応を検索
④ レポート生成（重要度・サプライズリスク付き）
```

---

## 7. 環境構築・起動方法

### 前提条件

`.env` に以下の環境変数を設定してください。

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:35432/agent_store

# AWS (Bedrock利用時)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=ap-northeast-1

# AI Models
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...

# Observability
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com

# External APIs
FMP_API_KEY=...            # Financial Modeling Prep
NEWS_API_KEY=...           # NewsAPI.org
GOOGLE_CLIENT_ID=...       # Google Cloud Console
GOOGLE_CLIENT_SECRET=...   # Google Cloud Console
JWT_SECRET=...             # JWT Server署名鍵
```

### 起動

```bash
# 依存関係インストール
cd py_app
uv sync

# Dockerコンテナ起動（MCPサーバー群）
docker compose up -d

# Streamlit アプリ起動
uv run streamlit run app.py
```

### 動作確認

```bash
# MCPサーバーの疎通確認
curl http://localhost:3333/mcp  # File Transcriber
curl http://localhost:4444/.well-known/jwks.json  # JWT Server
curl http://localhost:5555/mcp  # Indicator
curl http://localhost:7666/.well-known/oauth-authorization-server  # News Search OAuth metadata

# テスト実行
uv run pytest -p -s tests/
```

---

## 付録: 技術スタック

| カテゴリ | 技術 |
| --- | --- |
| **エージェントフレームワーク** | LangGraph, deepagents |
| **LLMインテグレーション** | LangChain (OpenAI, AWS Bedrock) |
| **MCPフレームワーク** | FastMCP |
| **UI** | Streamlit |
| **永続化** | PostgreSQL (チェックポイント・長期記憶), SQLite3 (RAG) |
| **認証** | Google OAuth 2.0, RS256 JWT (JWKS), Bearer Token |
| **オブザーバビリティ** | Langfuse |
| **外部API** | OpenAI (LLM/Whisper/Embeddings), NewsAPI, FMP, Yahoo Finance, Tavily, AWS SNS |
| **インフラ** | Docker Compose |
