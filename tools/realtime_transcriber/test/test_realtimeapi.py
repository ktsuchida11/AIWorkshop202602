import os
import json
import base64
import asyncio
import websockets

WS_URL = os.getenv("OPENAI_RT_URL", "ws://localhost:8000/ws")
AUDIO_FILE_PATH = "sample_audio.pcm"

# PCM 24kHz/16bit/mono の「1秒のバイト数」= 24000 samples * 2 bytes
BYTES_PER_SEC = 24000 * 2

async def receiver(ws):
    try:
        async for msg in ws:
            print("RECV:", msg)
    except Exception as e:
        print("receiver ended:", e)

async def main():
    headers = {"Authorization": "Bearer test_api_key"}

    async with websockets.connect(WS_URL, additional_headers=headers) as ws:
        recv_task = asyncio.create_task(receiver(ws))

        # 音声を少しずつ送る
        with open(AUDIO_FILE_PATH, "rb") as f:
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break

                payload = {
                    "type": "audio",
                    "data": base64.b64encode(chunk).decode("ascii"),
                }
                await ws.send(json.dumps(payload))

                # 実時間っぽく流す（不要なら 0 に）
                await asyncio.sleep(len(chunk) / BYTES_PER_SEC)

        # 送信完了
        await ws.send(json.dumps({"type": "commit"}))

        # サーバが close するまで少し待つ
        await recv_task

if __name__ == "__main__":
    asyncio.run(main())