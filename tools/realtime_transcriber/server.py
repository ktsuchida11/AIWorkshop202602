import os
import json
import base64
import asyncio
import logging
import inspect
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from dotenv import load_dotenv
from urllib.parse import urlparse

# websockets: prefer new asyncio implementation if available
try:
    from websockets.asyncio.client import connect  # websockets >= 13
except Exception:  # fallback legacy
    from websockets import connect  # type: ignore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("realtime-relay")

# make .env loading stable
load_dotenv(Path(__file__).with_name(".env"))

app = FastAPI()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# transcription-only の例（推奨）
OPENAI_RT_URL = os.getenv(
    "OPENAI_RT_URL",
    "wss://api.openai.com/v1/realtime?intent=transcription"
)

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable is required")


def validate_url(url: str):
    result = urlparse(url)
    if not all([result.scheme, result.netloc]):
        raise ValueError(f"Invalid URL: {url}")


# Validate OPENAI_RT_URL
validate_url(OPENAI_RT_URL)


def _connect_kwargs_for_headers(headers: dict) -> dict:
    """
    websockets version compatibility:
    """
    params = inspect.signature(connect).parameters
    if "additional_headers" in params:
        return {"additional_headers": headers}
    if "extra_headers" in params:
        return {"extra_headers": headers}
    raise RuntimeError("Your websockets.connect() doesn't support headers args.")


@app.get("/")
async def root():
    return {"message": "realtime relay is running"}


async def client_to_upstream(client_ws: WebSocket, upstream, vad: bool):
    while True:
        try:
            msg = await client_ws.receive()
        except WebSocketDisconnect:
            logger.info("client websocket disconnected (client_to_upstream)")
            return
        except Exception as e:
            logger.exception("error receiving from client: %s", e)
            return

        msg_type = msg.get("type")
        if msg_type == "websocket.disconnect":
            logger.info("client reported websocket.disconnect")
            return

        # (A) binary PCM16
        if msg.get("bytes") is not None:
            b64 = base64.b64encode(msg["bytes"]).decode("ascii")
            try:
                await upstream.send(json.dumps({"type": "input_audio_buffer.append", "audio": b64}))
                logger.debug("forwarded binary audio to upstream (%d bytes)", len(msg["bytes"]))
            except Exception:
                logger.exception("failed to send binary audio to upstream")
            continue

        # (B) JSON base64
        if msg.get("text"):
            try:
                obj = json.loads(msg["text"])
            except Exception:
                logger.warning("invalid JSON from client: %s", msg.get("text"))
                continue

            t = obj.get("type")
            # basic options handling (ack) for debugging
            if t == "options":
                logger.info("received options from client: %s", obj.get("options"))
                try:
                    await client_ws.send_text(json.dumps({"type": "options.ack"}))
                except Exception:
                    logger.exception("failed to ack options")
                continue

            if t == "audio" and obj.get("data"):
                try:
                    await upstream.send(json.dumps({"type": "input_audio_buffer.append", "audio": obj["data"]}))
                    logger.debug("forwarded audio b64 length=%d", len(obj.get("data", "")))
                except Exception:
                    logger.exception("failed to send audio to upstream")
            elif t == "commit":
                if not vad:
                    try:
                        await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))
                        logger.info("sent input_audio_buffer.commit to upstream")
                    except Exception:
                        logger.exception("failed to send commit to upstream")
                # vad=True の場合は無視（サーバが自動commit）
            elif t == "stop":
                logger.info("received stop from client")
                return


async def upstream_to_client(client_ws: WebSocket, upstream):
    try:
        async for raw in upstream:
            # OpenAI Realtime server events are JSON text
            try:
                ev = json.loads(raw)
            except Exception:
                try:
                    await client_ws.send_text(json.dumps({"type": "event", "raw": raw}))
                except WebSocketDisconnect:
                    logger.info("client disconnected while sending raw event")
                    return
                continue

            et = ev.get("type")

            # transcription の代表イベントを整形して返す（クライアントが扱いやすい形）
            if et == "conversation.item.input_audio_transcription.delta":
                logger.debug("skipping delta event")
                # try:
                #     await client_ws.send_text(json.dumps({"type": "delta", "item_id": ev.get("item_id"), "delta": ev.get("delta", "")}, ensure_ascii=False))
                # except WebSocketDisconnect:
                #     logger.info("client disconnected during delta send")
                #     return
            elif et == "conversation.item.input_audio_transcription.completed":
                transcript = ev.get("transcript", "")
                try:
                    await client_ws.send_text(json.dumps({"type": "completed", "item_id": ev.get("item_id"), "transcript": transcript}, ensure_ascii=False))
                except WebSocketDisconnect:
                    logger.info("client disconnected during completed send")
                    return
            else:
                # そのまま転送（デバッグ/将来拡張）
                try:
                    await client_ws.send_text(json.dumps({"type": "event", "data": ev}, ensure_ascii=False))
                except WebSocketDisconnect:
                    logger.info("client disconnected during event send")
                    return
    except Exception:
        logger.exception("upstream_to_client loop failed")


@app.websocket("/ws")
async def relay_ws(
    client_ws: WebSocket,
    translate: Optional[bool] = Query(False),
    vad: Optional[bool] = Query(True),
    model: str = Query("gpt-4o-mini-transcribe"),
):
    """
    Client -> FastAPI WS -> OpenAI Realtime WS (transcription) relay.
    """
    await client_ws.accept()
    logger.info("client connected: %s", getattr(client_ws, 'client', None))

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    connect_kwargs = _connect_kwargs_for_headers(headers)

    try:
        logger.info("connecting to upstream: %s", OPENAI_RT_URL)
        async with connect(OPENAI_RT_URL, **connect_kwargs, ping_interval=20, ping_timeout=10) as upstream:
            session_update = {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "transcription": {
                                "model": model,
                                "language": "ja",
                                "prompt": "Output Japanese when possible."
                            },
                            "turn_detection": (
                                {
                                    "type": "server_vad",
                                    "threshold": 0.5,
                                    "prefix_padding_ms": 300,
                                    "silence_duration_ms": 500,
                                    "create_response": False,
                                    "interrupt_response": False,
                                } if vad else None
                            ),
                            "noise_reduction": {"type": "near_field"},
                        }
                    }
                }
            }
            await upstream.send(json.dumps(session_update))
            logger.info("sent session.update to upstream")

            tasks = [
                asyncio.create_task(client_to_upstream(client_ws, upstream, vad)),
                asyncio.create_task(upstream_to_client(client_ws, upstream)),
            ]
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                logger.info("Tasks were cancelled")

    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.exception("relay error")
        try:
            await client_ws.send_text(json.dumps({"type": "error", "message": str(e)}))
        finally:
            await client_ws.close(code=1011)

if __name__ == "__main__":
    import uvicorn

    # サーバを起動
    uvicorn.run(app, host="0.0.0.0", port=8000)
