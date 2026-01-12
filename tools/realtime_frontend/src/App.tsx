import { useMemo, useRef, useState } from "react";

type ServerMsg =
  | { type: "delta"; item_id?: string; delta: string }
  | { type: "completed"; item_id?: string; transcript: string }
  | { type: "event"; data: any }
  | { type: "error"; message: string };

function wsUrl(path: string) {
  const host = process.env.REACT_APP_WS_HOST || "localhost:3334";
  const proto = location.protocol === "https:" ? "ws:" : "ws:"; // httpsの場合はwss、それ以外はws
  return `${proto}//${host}${path}`;
}

export default function App() {
  const [running, setRunning] = useState(false);
  const [text, setText] = useState("");
  const [isTranscribing, setIsTranscribing] = useState(false); // 文字起こし中の状態を管理
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const acRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);

  const displayMediaOptions = useMemo(() => {
    return {
      video: true,
      audio: true, // タブ音声を共有するために true を設定
    };
  }, []);

  async function start() {
    if (running) return;

    try {
      setIsTranscribing(true);

      // 既存のWebSocket接続を閉じる
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }

      const stream = await navigator.mediaDevices.getDisplayMedia(displayMediaOptions);
      streamRef.current = stream;

      const ws = new WebSocket(wsUrl("/ws"));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("WebSocket接続が確立されました");
      };

      ws.onclose = () => {
        console.log("WebSocket接続が閉じられました");
      };

      ws.onerror = (error) => {
        console.error("WebSocketエラー:", error);
      };

      ws.onmessage = (ev) => {
        try {
          const msg: ServerMsg = JSON.parse(ev.data);
          console.log("WebSocket受信データ:", msg);
          if (msg.type === "delta") {
            console.log("deltaメッセージを受信:", msg.delta);
            setText((t) => t + msg.delta);
          }
          if (msg.type === "completed") {
            console.log("completedメッセージを受信:", msg.transcript);
            setText((t) => t + "\n" + msg.transcript + "\n");
          }
        } catch (err) {
          console.error("WebSocketメッセージの処理中にエラー:", err);
        }
      };

      await new Promise<void>((resolve, reject) => {
        ws.onopen = () => resolve();
        ws.onerror = () => reject(new Error("WebSocket接続に失敗しました"));
      });

      const ac = new AudioContext();
      acRef.current = ac;

      // AudioWorklet モジュールのパスを修正
      await ac.audioWorklet.addModule("/pcm24k-mono-worklet.js");

      const source = ac.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ac, "pcm24k-mono");
      workletNodeRef.current = node;

      node.port.onmessage = (e) => {
        const buf = e.data as ArrayBuffer;
        console.log("WebSocket送信データ:", buf);
        if (ws.readyState === WebSocket.OPEN) ws.send(buf);
      };

      source.connect(node);
      setRunning(true);
    } catch (err) {
      setIsTranscribing(false);
        if (err instanceof Error && err.name === "NotAllowedError") {
          alert("画面共有が拒否されました。再度許可してください。");
        } else {
          console.error("Error starting screen share:", err);
        }
    }
  }

  async function stop() {
    setRunning(false);
    setIsTranscribing(false); // 停止ボタン押下時に文字起こし中を非表示

    try {
      workletNodeRef.current?.disconnect();
    } catch {}
    try {
      await acRef.current?.close();
    } catch {}
    acRef.current = null;
    workletNodeRef.current = null;

    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.close();
    }
    wsRef.current = null;
  }

  return (
    <div style={{ padding: 16, fontFamily: "sans-serif" }}>
      <h2>タブ音声 リアルタイム文字起こし</h2>
      <p>
        「開始」を押したら、共有ダイアログで <b>Chrome タブ</b> を選択し、
        <b>タブの音声を共有</b> を有効にしてください。
      </p>
      <button onClick={start} disabled={running}>
        開始
      </button>
      <button onClick={stop} disabled={!running} style={{ marginLeft: 8 }}>
        停止
      </button>

      {/* 文字起こし中の表示 */}
      {isTranscribing && (
        <p style={{ color: "green", marginTop: 16 }}>文字起こし中...</p>
      )}

      {/* 文字起こし結果の表示 */}
      <pre
        style={{
          marginTop: 16,
          whiteSpace: "pre-wrap",
          border: "1px solid #ccc",
          padding: 16,
          width: "100%", // 幅を広げる
          maxWidth: "800px", // 最大幅を設定
          backgroundColor: "#f9f9f9",
        }}
      >
        {text}
      </pre>

      {/* コピー用のボタン */}
      <button
        onClick={() => {
          navigator.clipboard.writeText(text);
          alert("文字起こし結果をコピーしました！");
        }}
        style={{
          marginTop: 8,
          padding: "8px 16px",
          backgroundColor: "#007BFF",
          color: "white",
          border: "none",
          borderRadius: "4px",
          cursor: "pointer",
        }}
      >
        コピー
      </button>
    </div>
  );
}