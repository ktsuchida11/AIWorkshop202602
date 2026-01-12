MCP Transcriber
================

ローカルで実行できる YouTube → 文字起こし（Transcribe）用の FastMCP サーバ実装です。

概要
- YouTube の URL を受け取り音声をダウンロード（yt-dlp）
- OpenAI API を利用した文字起こし（transcribe）
- 翻訳（OpenAI Chat API）
- ツール分割：ダウンロード / 文字起こし / 翻訳 を個別の MCP ツールとして公開
- 同期ツールと非同期(await)ツールの両方を提供
- 簡易ジョブ API（`start_transcription` / `get_transcription_status`）
- 開発用の静的トークンによる認証（`StaticTokenVerifier`）

必須（実行前に）
- `ffmpeg`（`pydub.AudioSegment` の変換に必要）
- `yt-dlp`（YouTube からのダウンロード）
- OpenAI API キー（環境変数 `OPENAI_API_KEY` に設定）
- Python 依存はプロジェクトの `pyproject.toml` / `requirements.txt` を参照

主な公開シンボル（コード参照）
- `server.mcp` — FastMCP インスタンス（名前: "YoutubeTranscribeMCP"）
- `server.transcribe_youtube_to_japanese_tool` / `server.transcribe_youtube_to_japanese_async_tool`
- `server.download_audio_from_youtube_tool` / `server.download_audio_from_youtube_async_tool`
- `server.transcribe_audio_tool` / `server.transcribe_audio_async_tool`
- `server.translate_text_to_japanese_tool` / `server.translate_text_to_japanese_async_tool`
- `server.start_transcription` / `server.get_transcription_status`

実行（ローカル・コンテナ）

Docker イメージを作る場合の例:
```bash
docker build -t mcp-transcriber:latest .
```

環境変数を渡して実行する例:
```bash
docker run -e OPENAI_API_KEY=$OPENAI_API_KEY -e JWT_SECRET=mysecret -p 8000:8000 mcp-transcriber:latest
```

ローカルで直接実行する場合（開発）:
```bash
export OPENAI_API_KEY=...
# テストやインポート時に自動で mcp.run() が起動しないよう、MCP_TESTING を使ってガードしています
python server.py
```

注意事項
- モジュールをテストやインポートする際、自動的に `mcp.run()` が起動しないように `if __name__ == "__main__":` の中で起動処理を行っています。テスト実行時に環境変数 `MCP_TESTING=1` をセットすると明示的にスキップされます。
- 実機では `StaticTokenVerifier` ではなく、JWT（Cognito/Auth0 など）を使った検証を推奨します。

MCP Inspector での確認手順（簡易）
1. サーバを HTTP で起動（例: `streamable-http`）
2. `@modelcontextprotocol/inspector` などの Inspector を起動
3. 接続情報にサーバの MCP エンドポイントを設定し、`Authorization: Bearer dev-alice-token` をヘッダにつけて接続
4. ツール一覧に下記が表示されることを確認します:
   - `transcribe_youtube_to_japanese_tool`
   - `transcribe_youtube_to_japanese_async_tool`
   - `download_audio_from_youtube_tool`
   - `download_audio_from_youtube_async_tool`
   - `transcribe_audio_tool`
   - `transcribe_audio_async_tool`
   - `translate_text_to_japanese_tool`
   - `translate_text_to_japanese_async_tool`
   - `start_transcription`
   - `get_transcription_status`

簡単な同期ワークフロー（概念）
```py
# 1) ダウンロード -> WAV パス
# 2) 文字起こし -> text
# 3) 翻訳 -> 日本語テキスト
wav = server.download_audio_from_youtube_tool(url)
text = server.transcribe_audio_tool(wav)
translated = server.translate_text_to_japanese_tool(text)
```

非同期ツールチェイン（await 可能）
```py
wav = await server.download_audio_from_youtube_async_tool(url)
text = await server.transcribe_audio_async_tool(wav)
translated = await server.translate_text_to_japanese_async_tool(text)
```

ジョブ API（非同期バックグラウンド）
- `start_transcription(url)` -> `job_id`（即時返却）
- `get_transcription_status(job_id)` -> `{status, progress, stage, result?}`

トラブルシュート（よくある事例）
- 401 Unauthorized: Authorization ヘッダがない、もしくはトークンが一致しない。開発用トークンは `dev-alice-token`。
- No audio file produced by yt-dlp: `yt-dlp` の出力候補にファイルが無い場合。`ffmpeg` や node/deno の要件を確認。
- OpenAI 呼び出しエラー: `OPENAI_API_KEY` が正しいか、API の利用状況やレート制限を確認。

テストについて
- テストは外部呼び出し（yt-dlp / OpenAI）を差し替えるヘルパーを使って実行します（`tests/helpers.py`）。
- 主要なテストファイル:
  - `tests/test_protocol_server.py` — MCP とツールの存在確認
  - `tests/test_unit_server.py` — 単体テスト
  - `tests/test_cascade_server.py` — 同期/非同期ツールチェイン検証
  - `tests/test_workflow_job.py` — ジョブ API のワークフロー例

実装参照
- 実装本体: `server.py`（`static_tokens` / `static_auth` / MCP 名: "YoutubeTranscribeMCP" を定義）

ライセンス
- リポジトリの `LICENSE` を参照してください。

追加のヘルプが必要なら、Inspector 接続手順のスクリーンショットや、Docker/ローカル起動でのログ出力の確認を手伝います。


注意: 実行環境に`ffmpeg`が必要です。Pythonライブラリは`requirements.txt`参照。

OpenAI Whisper API を使う場合:

- 環境変数 `OPENAI_API_KEY` を設定してください。
- コンテナ実行時に渡す例: `-e OPENAI_API_KEY=$OPENAI_API_KEY`


以下は **FastMCP（HTTP / 認証付き）で起動した MCP サーバを、MCP Inspector で確認・テストするための完全手順**です。
そのまま README に貼れる **Markdown 形式**で記載します。

---

# MCP Inspector による動作確認手順

## 前提条件

* MCP サーバが起動していること
* FastMCP を `streamable-http` で起動していること
* ポート番号：`3333`
* 認証方式：`StaticTokenVerifier`
* 有効なトークン：`dev-alice-token`

起動ログに以下が出ていることを確認してください。

```text
Listening on http://0.0.0.0:3333/mcp
Transport: streamable-http
```

---

## 1. MCP Inspector の起動

ターミナルで以下を実行します。

```bash
npx @modelcontextprotocol/inspector
```

実行後、自動的にブラウザが起動します。

---

## 2. MCP サーバへの接続設定

Inspector の左ペインで、以下のように設定します。

### Connection Settings

| 項目        | 設定値                         |
| --------- | --------------------------- |
| Transport | **HTTP**                    |
| URL       | `http://localhost:3333/mcp` |

---

### Headers（必須）

StaticToken 認証を利用しているため、以下の HTTP ヘッダを設定します。

```http
Authorization: Bearer dev-alice-token
```

Header Name: Authorization
Bearer Token: dev-alice-token

---

## 3. 接続テスト

### 3.1 接続確認

設定後、**Connect** ボタンを押します。

成功すると以下が確認できます。

* エラーが表示されない
* **List Tools** ボタンが有効になる

---

### 3.2 ツール一覧の取得

**List Tools** をクリックすると、以下のようなツール一覧が表示されます。

例：

* `transcribe_youtube_to_japanese_tool`
* `transcribe_youtube_to_japanese_async_tool`
* `start_transcription`
* `get_transcription_status`
* `download_audio_from_youtube_tool`
* `transcribe_audio_tool`
* `translate_text_to_japanese_tool`

これらが表示されていれば、MCP サーバとの通信は成功しています。

---

## 4. ツールの実行テスト

### 4.1 同期ツールの実行例

#### ツール

```
transcribe_youtube_to_japanese_tool
```

#### Input

```json
{
  "url": "https://www.youtube.com/watch?v=XXXXXXXX"
}
```

#### 確認ポイント

* 実行後にレスポンスが返る
* エラーが発生しない
* 日本語の翻訳結果が返却される

---

### 4.2 非同期ジョブ型ツールの実行例（推奨）

#### Step 1: ジョブ開始

ツール：

```
start_transcription
```

Input：

```json
{
  "url": "https://www.youtube.com/watch?v=XXXXXXXX"
}
```

出力例：

```json
"e7c8f9e4-1234-5678-9abc-xxxxxxxxxxxx"
```

---

#### Step 2: ステータス確認

ツール：

```
get_transcription_status
```

Input：

```json
{
  "job_id": "e7c8f9e4-1234-5678-9abc-xxxxxxxxxxxx"
}
```

返却例（処理中）：

```json
{
  "status": "running",
  "progress": 50,
  "stage": "transcribe"
}
```

返却例（完了）：

```json
{
  "status": "done",
  "progress": 100,
  "result": "（翻訳された日本語テキスト）"
}
```

---

## 5. よくあるエラーと対処法

### 401 Unauthorized

* Authorization ヘッダが未設定、またはトークンが誤っている

```http
Authorization: Bearer dev-alice-token
```

---

### 接続できない（ECONNREFUSED）

確認項目：

* MCP サーバが起動しているか
* ポート番号が `3333` か
* URL に `/mcp` が含まれているか

```text
http://localhost:3333/mcp
```

---

### ツールが表示されない

* サーバ起動時にエラーが出ていないか
* `@mcp.tool()` デコレータが付与されているか
* 認証スコープ不足がないか

---

## 6. 確認完了のチェックリスト

* [ ] MCP Inspector から接続できる
* [ ] ツール一覧が取得できる
* [ ] 同期ツールが実行できる
* [ ] 非同期ジョブの状態が取得できる

すべて満たしていれば、**MCP サーバは正常に動作しています。**

---

## 補足（次のステップ）

* LangGraph / DeepAgent から MCP を Tool として呼び出す
* JWTVerifier（Auth0 / Cognito）への切り替え
* HTTPS（Nginx）対応
* MCP ツールの権限制御（scope 別）

必要であれば、
**「Inspector での確認 → LangGraph 連携確認」までを1本の検証フロー**として整理した資料も作成できます。
