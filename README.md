Realtime YouTube Transcribe (py_app)

このフォルダはリアルタイム文字起こしのサンプル（フロント＋バック）を含みます。

構成:
- `mcp_server/realtime_transcribe_mcp.py` : WebSocket 中継サーバ（ブラウザ <-> OpenAI Realtime API）
- `realtime_frontend/` : React + TypeScript のフロントエンドサンプル

クイックスタート:

1) Backend の起動（スタンドアロン）

```bash
cd aws_llm/py_app
python -m venv .venv
source .venv/bin/activate
pip install aiohttp
export OPENAI_API_KEY="sk-..."
python mcp_server/realtime_transcribe_mcp.py --port 8080
```

コンテナで起動する（推奨）:

```bash
cd aws_llm/py_app
export OPENAI_API_KEY="sk-..."
docker compose up --build
```

- フロントは http://localhost:5173 でアクセスできます（Vite dev server）。
- コンテナ内フロントは `VITE_WS_HOST=backend:8080` を使ってバックエンドに接続します。

2) Frontend の起動

```bash
cd aws_llm/py_app/realtime_frontend
npm install
npm run dev
# ブラウザで表示されるローカル URL を開く
```

使い方:
- フロントの "Start Capture" を押し、キャプチャ対象のタブ（YouTube）を選びます。
- 許可したタブの音声が分割されたチャンクでバックエンドに送られ、文字起こし結果が画面に表示されます。

注意:
- ローカルでの動作確認には Chrome（デスクトップ）が扱いやすいです。
- 本番では `wss://` と認証を必ず導入してください。

トラブルシュート:
- 音声が送られない: ブラウザのコンソールで getDisplayMedia の許可状況と MediaRecorder のエラーを確認してください。
- OpenAI からレスポンスが来ない: `OPENAI_API_KEY` と `REALTIME_MODEL` の互換性を確認してください。

---

必要であれば、MCP ツールとしての起動方法や追加の機能（句読点の付与、言語指定、部分的な翻訳など）を実装します。