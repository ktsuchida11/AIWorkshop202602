# realtime_transcriber_mcp

FastAPI を使った OpenAI Realtime API への中継サーバー (WebSocket)。

主な機能
- ブラウザと接続する WebSocket (`/ws`) を提供
- ブラウザから送られてくる base64 エンコード済み PCM 音声を OpenAI Realtime に中継
- Realtime の文字起こしイベントをブラウザへ返送
- オプションで受け取った文字起こしを日本語へ翻訳して返す
- 話者分離フラグを受け取り、Upstream にリクエストを投げる（ベストエフォート）

環境変数
- `OPENAI_API_KEY` (必須)
- `OPENAI_RT_URL` (任意, デフォルト: `wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-transcribe`)

実行 (ローカル)

1. 仮想環境を作り依存をインストール (プロジェクトの `pyproject.toml` に従う)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt # または pyproject に合わせた方法
export OPENAI_API_KEY="sk-..."
uvicorn server:app --host 0.0.0.0 --port 3334
```

実行 (Docker)

```bash
docker build -t realtime-transcriber .
docker run -e OPENAI_API_KEY="sk-..." -p 3334:3334 realtime-transcriber
```

WebSocket 例 (ブラウザ側)

- 接続先: `ws://<host>:3334/ws?translate=true&diarize=false`
- 送信フォーマット (音声): JSON
  - `{"type":"audio","data":"<base64 pcm_s16le 16000Hz の base64>"}`
  - `{"type":"commit"}` を送るとサーバーは upstream にコミットを送信して部分結果を確定します

注意
- OpenAI Realtime API のメッセージ/イベント形式は頻繁に変わる可能性があります。実際の upstream イベント名やフィールドに合わせて `server.py` のパース部分を調整してください。
- 話者分離は Realtime 側のサポート状況に依存します。サーバー側ではフラグを渡す仕組みを実装していますが、期待どおりの出力が得られない場合は upstream のドキュメントを参照してください。

次のステップ
- React フロントエンドのサンプル（audio capture, base64 送信、受信して表示）を追加できます。要りますか？

## Docker Compose を使った起動（簡易テスト）

リポジトリルートの `docker-compose.yml` を使ってフロントとバックエンドを同時に起動できます。バックエンドはポート `3334`、フロントは `5173` を公開します。

環境変数例（.env またはシェルで設定）:

```
OPENAI_API_KEY=sk-...
OPENAI_RT_URL=wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-transcribe
```

起動方法:

```bash
# リポジトリルートで
docker compose up --build
```

確認:

```bash
curl http://localhost:3334/
# -> {"message":"realtime transcriber proxy is running"}
```

注意:
- Compose 内ではフロントは `VITE_WS_HOST=backend:3334` のようにコンテナ名経由でバックエンドに接続するよう設定しています。ローカルブラウザからフロントにアクセスする場合（http://localhost:5173）、ブラウザはフロントに接続するため、フロントがバックエンドへ接続する設定はそのままで問題ありません。
- 本番では必ず TLS (wss://) と認証を導入してください。
Realtime Transcribe MCP server (日本語)

概要:
- `realtime_transcribe_mcp.py` はブラウザから受け取った音声バイナリを OpenAI Realtime API に転送し、受信したテキストイベントをブラウザに返すシンプルな WebSocket 中継サーバです。

必要な環境変数:
- `OPENAI_API_KEY` : 必須。OpenAI APIキーを設定します。
- `REALTIME_MODEL` : 任意。デフォルトは `gpt-4o-realtime-preview`。

依存パッケージ (例):
- `aiohttp` (WebSocket クライアント/サーバ)
- `mcp` (MCP環境で実行する場合)

ローカルで動かす手順 (スタンドアロン):

1. Python 環境を準備し、依存をインストールします:

```bash
python -m venv .venv
source .venv/bin/activate
pip install aiohttp
# mcp を使う場合は追加で pip install mcp
```

2. 環境変数を設定してサーバを起動します:

```bash
export OPENAI_API_KEY="sk-..."
python mcp_server/realtime_transcribe_mcp.py --port 8080
```

MCP ツールとして起動する場合:
- `mcp` が有効な環境では、`start_realtime_server(port)` ツールを呼び出すことでバックグラウンドでサーバを起動します。

フロントエンドとの接続:
- フロントエンドは `ws://<host>:<port>/ws` に接続し、音声を `ArrayBuffer` の binary メッセージで送信します。
- フロントが `commit` というテキストメッセージを送ると、バックエンドは `input_audio_buffer.commit` を送信し、続けて `response.create` を投げて文字起こしを要求します。

ブラウザ側の注意点:
- タブ音声をキャプチャするには Chrome 系ブラウザの `getDisplayMedia({ audio: true })` を使用します（ブラウザと環境によってはタブ音声キャプチャに制限があります）。
- MediaRecorder の出力は `audio/webm;codecs=opus` のような形式で送信する実装例があります。

デバッグ/ログ:
- サーバは標準出力にログを出します。問題があればログレベルを INFO->DEBUG に上げてください。

セキュリティ:
- 本サーバはサンプル実装です。本番運用時は認証、TLS（wss://）を必ず導入してください。

参考:
- フロントサンプルは `../realtime_frontend` にあります。

追加機能:
- 言語指定 / 句読点オプション: フロントは JSON コントロールメッセージで接続ごとのオプションを設定できます。例:

```json
{"language":"ja", "punctuate": true, "speaker_diarization": false}
```

- フロントが `commit` メッセージを送ると、設定に応じて `response.create` の `instructions` に言語や句読点要求を追加して OpenAI に送信します。

- 話者分離ツール: MCP ツール `diarize_audio_file(file_path)` を追加しました。`pyannote.audio` がインストールされ利用可能な場合、ローカルの音声ファイルに対して話者セグメントを返します。pyannote を使用するには別途インストールとモデルの認証設定が必要です。

pyannote インストール例:

```bash
pip install pyannote.audio
# PYANNOTE_AUDIO で必要な認証環境変数の設定が必要
```

問題が出たら README を更新して教えてください。
