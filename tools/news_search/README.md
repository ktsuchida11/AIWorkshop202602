# News Search MCP Server

Google OAuth2.0認証を使用したニュース検索MCPサーバ

## 機能

- Google OAuth2.0による認証
- NewsAPI.orgを使用したニュース検索
- 4つの検索ツール:
  - `search_news`: キーワード検索
  - `get_top_headlines`: トップニュース取得
  - `search_news_by_category`: カテゴリ別検索
  - `search_news_by_date_range`: 日付範囲検索

## セットアップ

### 1. Google Cloud Platformの設定（OAuth 2.0）

> **📌 注意**: 2024年末よりGoogle Cloud ConsoleのOAuth設定UIが新しいデザインに変更されました。
> 以下の手順は新しいUI（Branding / Audience / Clients / Data Accessタブ構成）に対応しています。

#### ステップ1: プロジェクトの作成

1. **Google Cloud Consoleにアクセス**
   - <https://console.cloud.google.com/> を開く
   - Googleアカウントでログイン

2. **新しいプロジェクトを作成**
   - 画面上部の「プロジェクトを選択」→「新しいプロジェクト」をクリック
   - プロジェクト名: `mcp-news-search`（任意の名前）
   - 「作成」をクリック
   - プロジェクトが作成されたら選択

#### ステップ2: OAuth同意画面の設定（新しいUI）

左側メニュー → 「APIとサービス」 → 「OAuth同意画面」に移動すると、
以下の4つのタブが表示されます。

---

#### ① Branding（ブランディング）タブ

1. 「Branding」タブを開く
2. 以下を入力して「保存」:
   - App name: `News Search MCP Server`
   - User support email: 自分のメールアドレスを選択
   - Developer contact information: 自分のメールアドレスを入力

---

#### ② Audience（オーディエンス）タブ

1. 「Audience」タブを開く
2. 「外部（External）」を選択して「保存」
3. **テストユーザーの追加**（テスト中は必須）:
   - 「Test users」セクション → 「ADD USERS」をクリック
   - 自分のGmailアドレスを入力して「追加」→「保存」

---

#### ③ Clients（クライアント）タブ ← OAuthクライアントIDの作成

1. 「Clients」タブを開く
2. 「CREATE CLIENT」（または「クライアントを作成」）をクリック
3. 以下を入力:
   - Application type: 「ウェブアプリケーション（Web application）」
   - Name: `News Search MCP Client`
4. **承認済みのリダイレクトURIを追加**:
   - 「承認済みのリダイレクトURI」→「URIを追加」をクリック
   - 以下のURIを追加（fastmcp のデフォルトは `/auth/callback`）:

     ```text
     http://localhost:6666/auth/callback
     ```

5. 「作成」をクリック
6. **クライアントIDとクライアントシークレットをコピー**して安全な場所に保存

> **⚠️ 重要**: クライアントシークレットは後から確認できません。紛失した場合は新しいクライアントを作成してください。

---

#### ④ Data Access（データアクセス）タブ ← スコープの設定

> ここがスコープ設定の場所です（旧UIではウィザードの途中にありましたが、新UIでは独立したタブになっています）

1. 「Data Access」タブを開く
2. 「ADD OR REMOVE SCOPES」をクリック
3. 右側に検索パネルが表示されるので、以下のスコープにチェックを入れる:
   - `openid`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`

   > 検索ボックスに `userinfo` と入力するとフィルタできます
4. 「UPDATE」をクリック
5. 「SAVE」をクリック

### 2. NewsAPI.orgのAPIキー取得

#### ステップ1: アカウント登録

1. **NewsAPI.orgにアクセス**
   - <https://newsapi.org/> を開く

2. **Get API Keyをクリック**
   - トップページの「Get API Key」ボタンをクリック

3. **アカウント情報を入力**
   - First Name: 名前
   - Email: メールアドレス
   - Password: パスワード（8文字以上）
   - 「I'm not a robot」にチェック
   - 「Submit」をクリック

4. **メール確認**
   - 登録したメールアドレスに確認メールが届きます
   - メール内のリンクをクリックしてアカウントを有効化

#### ステップ2: APIキーの取得

1. **ダッシュボードにログイン**
   - <https://newsapi.org/account> にアクセス
   - 登録したメールアドレスとパスワードでログイン

2. **APIキーをコピー**
   - ダッシュボードに表示されている「API key」をコピー
   - 形式: `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`（32文字の英数字）

3. **無料プランの制限を確認**
   - リクエスト数: **100リクエスト/日**
   - 開発環境のみ利用可能（本番環境は有料プラン）
   - 過去1ヶ月のニュースのみ取得可能

> **💡 ヒント**: レート制限を超えないよう、キャッシュの実装を検討してください。

### 3. 環境変数の設定

#### ステップ1: .envファイルの作成

```bash
cd /Users/tsuchitakouji/Documents/WorkShop/AI/2026/aws_llm/py_app/tools/news_search
cp .env.example .env
```

#### ステップ2: .envファイルの編集

`.env`ファイルを開いて、取得した認証情報を設定します:

```bash
# Google OAuth2.0 Configuration
# 取得したClient IDとSecretに置き換える
GOOGLE_CLIENT_ID=123456789-abcdefghijklmnopqrstuvwxyz.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxx

# NewsAPI.org API Key
# 取得したAPIキーに置き換える
NEWS_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Server Configuration（変更不要）
HOST=0.0.0.0
PORT=6666
LOG_LEVEL=INFO
```

#### ステップ3: ルートの.envファイルも更新

Docker Composeを使用する場合、プロジェクトルートの`.env`ファイルも更新します:

```bash
cd /Users/tsuchitakouji/Documents/WorkShop/AI/2026/aws_llm/py_app
```

`.env`ファイルに以下を追加（既に追加されている場合は値を更新）:

```bash
# News Search MCP - Google OAuth2.0
GOOGLE_CLIENT_ID=123456789-abcdefghijklmnopqrstuvwxyz.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxx

# NewsAPI.org API Key
NEWS_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> **🔒 セキュリティ注意**: `.env`ファイルは`.gitignore`に含まれており、Gitにコミットされません。認証情報を公開リポジトリにアップロードしないよう注意してください。

### 4. 依存関係のインストール

```bash
uv sync
```

### 5. サーバ起動

```bash
uv run python server.py
```

## Docker

```bash
# ビルド
docker build -t news-search-mcp .

# 起動
docker run -p 6666:6274　--env-file .env news-search-mcp
```

## DeepAgentとの統合

`task_agent/deep_agent.py`の`MultiServerMCPClient`に以下を追加:

```python
"news-search": {
    "transport": "http",
    "url": "http://localhost:6666/mcp",
    "oauth": {
        "provider": "google",
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "scopes": ["openid", "email", "profile"],
    },
    "timeout": timedelta(seconds=30),
    "sse_read_timeout": timedelta(minutes=5),
}
```

## 動作確認テスト

### JWT サーバ（ポート 4444）のテスト

#### 1. ログイン（JWTトークン取得）

```bash
# alice（admin権限）でログイン
curl -X POST http://localhost:4444/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "password123"}'
# → {"token": "eyJ..."} が返れば成功

# bob（user権限）でログイン
curl -X POST http://localhost:4444/login \
  -H "Content-Type: application/json" \
  -d '{"username": "bob", "password": "securepassword"}'
```

#### 2. トークン検証

```bash
TOKEN=$(curl -s -X POST http://localhost:4444/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "password123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -X POST http://localhost:4444/verify \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"$TOKEN\"}"
# → {"valid": true, "decoded": {"sub": "alice", "role": "admin", "scopes": [...]}} が返れば成功
```

#### 3. JWKS エンドポイント（公開鍵取得）

```bash
curl http://localhost:4444/.well-known/jwks.json
# → {"keys": [{"kty": "RSA", ...}]} が返れば成功
```

> **注意**: JWTサーバのイメージが古い場合はJWKSエンドポイントが404になります。
> その場合は `docker compose up --build jwt-server` でリビルドしてください。

---

### News Search MCP サーバ（ポート 6724）のテスト

#### 1. OAuth メタデータの確認（サーバ起動確認）

```bash
curl http://localhost:6666/.well-known/oauth-authorization-server | python3 -m json.tool
# → {"issuer": "http://localhost:6666/", "authorization_endpoint": "...", ...} が返れば起動OK
```

#### 2. 未認証アクセスの確認（401 が返ることを確認）

```bash
curl -v http://localhost:6666/mcp 2>&1 | grep -E "HTTP|www-authenticate" -i
# → HTTP/1.1 401 Unauthorized
# → www-authenticate: Bearer error="invalid_token" ... が返れば認証が機能している
```

#### 3. OAuth フロー全体テスト（ブラウザ経由）

MCPクライアント（DeepAgent等）から接続すると自動的にブラウザが開き、
Googleログイン画面にリダイレクトされます。

手動でフローを確認する場合：

```bash
# 1. クライアント登録
curl -X POST http://localhost:6666/register \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "test-client",
    "redirect_uris": ["http://localhost:9999/callback"],
    "grant_types": ["authorization_code"],
    "response_types": ["code"]
  }' | python3 -m json.tool

# 2. 返ってきた client_id を使って認証URLを開く（ブラウザで）
# http://localhost:6666/authorize?response_type=code&client_id=<client_id>&redirect_uri=http://localhost:9999/callback&scope=openid
```

---

### Docker コンテナの再ビルド（コード変更後）

```bash
# jwt-server のみ再ビルド（JWKSエンドポイント追加後など）
docker compose up --build jwt-server

# news-search のみ再ビルド
docker compose up --build news-search

# 全サービス再ビルド
docker compose up --build
```

## 制限事項

- NewsAPI.org無料プラン: **100リクエスト/日**
- 開発環境のみ（本番環境はHTTPS必須）

## ライセンス

MIT
