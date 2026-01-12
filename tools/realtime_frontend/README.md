Realtime YouTube Transcribe Frontend

- Start dev server: `npm install` then `npm run dev`
- Open browser and click "Start Capture"; allow tab capture and audio.
- This app captures the current tab (YouTube) audio and streams chunks to backend via WebSocket.

Notes:
- Browser must support `getDisplayMedia` with `audio:true` (Chrome desktop can capture tab audio).
- Backend must run at `ws://localhost:8080/ws` by default.

## Docker Compose を使った起動（簡易テスト）

リポジトリルートの `docker-compose.yml` を使うとフロントとバックエンドを同時にビルド・起動できます。フロントは `5173`、バックエンドは `3334` を公開します。

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

コンテナ構成のポイント:
- Compose 内ではフロントに `VITE_WS_HOST=backend:3334` を渡しているため、フロントは Compose ネットワーク上の `backend` サービス名でバックエンドに接続します。
- Docker でフロントを直接実行しローカルホストのバックエンドに接続する場合は `VITE_WS_HOST=host.docker.internal:3334` のように設定してください（環境により名前が異なります）。

ブラウザで開く:

```
http://localhost:5173
```

トラブルシュート:
- フロントからバックエンドへ接続できない場合は、コンテナ間ネットワークと `VITE_WS_HOST` の値を確認してください。
