"""
Workflow examples that combine the job API and individual tools.

Two demos (mock mode by default):

1) demo_start_transcription_via_job_api(url)
   - Calls `server.start_transcription(url)` (full pipeline) and polls
     `server.get_transcription_status(job_id)` until completion.

2) demo_start_transcription_from_download(url)
   - Uses the individual download tool to get a WAV, then creates a job
     manually (in `server._jobs`) that runs transcription+translation on
     the WAV in a background thread, and polls the same `get_transcription_status`.

Run:
    python tools/mcp_transcriber/workflow_job_example.py

This script runs in mock mode by default so it doesn't call network or OpenAI.
Set `mock=False` to try the real pipelines (requires yt-dlp, OpenAI, ffmpeg).
"""
import time
import threading
import uuid
from pathlib import Path

import server


def demo_start_transcription_via_job_api(url: str, poll_interval: float = 1.0):
    print("[demo] Starting job via start_transcription()")
    # helper: call underlying function of an object wrapped by `mcp.tool()` if necessary
    try:
        from helpers import call_tool as _call_tool, install_mock_server
    except Exception:
        # fallback: local implementation if helpers cannot be imported (script run directly)
        def _call_tool(obj, *a, **kw):
            if callable(obj):
                return obj(*a, **kw)
            for attr in ("fn", "func", "__wrapped__"):
                f = getattr(obj, attr, None)
                if callable(f):
                    return f(*a, **kw)
            raise TypeError(f"Tool object {obj!r} is not callable and has no known underlying function")

        def install_mock_server(server_module, tmp_path):
            from pathlib import Path

            def fake_download(url: str) -> str:
                p = Path(tmp_path) / "dummy.wav"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"RIFF....")
                print("[mock] fake_download ->", p)
                return str(p)

            def fake_transcribe(path: str) -> str:
                print("[mock] fake_transcribe ->", path)
                return "Hello world"

            def fake_translate(text: str) -> str:
                print("[mock] fake_translate ->", text)
                return "こんにちは世界"

            server_module.download_audio_from_youtube = fake_download
            server_module.transcribe_audio = fake_transcribe
            server_module.translate_text_to_japanese = fake_translate

            orig_download_tool = getattr(server_module, 'download_audio_from_youtube_tool', None)
            orig_transcribe_tool = getattr(server_module, 'transcribe_audio_tool', None)
            orig_translate_tool = getattr(server_module, 'translate_text_to_japanese_tool', None)

            if orig_download_tool:
                server_module.download_audio_from_youtube_tool = lambda url, _orig=orig_download_tool: _call_tool(_orig, url)
            else:
                server_module.download_audio_from_youtube_tool = lambda url: _call_tool(server_module.download_audio_from_youtube, url)

            if orig_transcribe_tool:
                server_module.transcribe_audio_tool = lambda p, _orig=orig_transcribe_tool: _call_tool(_orig, p)
            else:
                server_module.transcribe_audio_tool = lambda p: _call_tool(server_module.transcribe_audio, p)

            if orig_translate_tool:
                server_module.translate_text_to_japanese_tool = lambda t, _orig=orig_translate_tool: _call_tool(_orig, t)
            else:
                server_module.translate_text_to_japanese_tool = lambda t: _call_tool(server_module.translate_text_to_japanese, t)

            return {'download': fake_download, 'transcribe': fake_transcribe, 'translate': fake_translate}


def demo_start_transcription_via_job_api(url: str, poll_interval: float = 1.0):
    job_id = _call_tool(server.start_transcription, url)
    print(f"[demo] job_id={job_id}")

    while True:
        status = _call_tool(server.get_transcription_status, job_id)
        print(f"[demo] status={status}")
        if status.get("status") in ("done", "error", "not_found"):
            break
        time.sleep(poll_interval)

    print("[demo] finished:", _call_tool(server.get_transcription_status, job_id))


def demo_start_transcription_from_download(url: str, poll_interval: float = 1.0):
    print("[demo] Downloading WAV with individual tool")
    wav = server.download_audio_from_youtube_tool(url)
    print("[demo] downloaded:", wav)

    # create a job_id and register a job entry
    job_id = str(uuid.uuid4())
    with server._jobs_lock:
        server._jobs[job_id] = {"status": "queued", "progress": 0}

    def worker(job_id: str, wav_path: str):
        try:
            with server._jobs_lock:
                server._jobs[job_id]["status"] = "running"
                server._jobs[job_id]["progress"] = 10
                server._jobs[job_id]["stage"] = "transcribe"

            # call the individual tools (sync)
            text = server.transcribe_audio_tool(wav_path)
            with server._jobs_lock:
                server._jobs[job_id]["progress"] = 60
                server._jobs[job_id]["stage"] = "translate"

            translated = server.translate_text_to_japanese_tool(text)

            with server._jobs_lock:
                server._jobs[job_id]["status"] = "done"
                server._jobs[job_id]["progress"] = 100
                server._jobs[job_id]["result"] = translated
                server._jobs[job_id].pop("stage", None)
        except Exception as e:
            with server._jobs_lock:
                server._jobs[job_id]["status"] = "error"
                server._jobs[job_id]["error"] = str(e)

    t = threading.Thread(target=worker, args=(job_id, wav), daemon=True)
    t.start()

    print(f"[demo] started job_id={job_id} (from WAV)")

    while True:
        status = _call_tool(server.get_transcription_status, job_id)
        print(f"[demo] status={status}")
        if status.get("status") in ("done", "error", "not_found"):
            break
        time.sleep(poll_interval)

    print("[demo] finished:", _call_tool(server.get_transcription_status, job_id))


if __name__ == "__main__":
    # For safety, run in mock mode so we don't call external services by default.
    mock = True
    example_url = "https://www.youtube.com/watch?v=dummy"

    if mock:
        # Patch server functions to short-circuit external calls.
        def fake_download(url: str) -> str:
            p = Path(server.os.getenv("DOWNLOAD_DIR", "downloads")) / "dummy.wav"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"RIFF....")
            print("[mock] fake_download ->", p)
            return str(p)

        def fake_transcribe(path: str) -> str:
            print("[mock] fake_transcribe ->", path)
            return "Hello world"

        def fake_translate(text: str) -> str:
            print("[mock] fake_translate ->", text)
            return "こんにちは世界"

        server.download_audio_from_youtube = fake_download
        server.transcribe_audio = fake_transcribe
        server.translate_text_to_japanese = fake_translate

        # Also ensure MCP tool wrappers use the patched functions
        # if tools are wrapped by mcp.tool(), ensure we can call their underlying functions
        # Capture any existing MCP tool wrappers before we replace them to avoid
        # recursive lambdas calling themselves via getattr on the already-replaced name.
        orig_download_tool = getattr(server, 'download_audio_from_youtube_tool', None)
        orig_transcribe_tool = getattr(server, 'transcribe_audio_tool', None)
        orig_translate_tool = getattr(server, 'translate_text_to_japanese_tool', None)

        if orig_download_tool:
            server.download_audio_from_youtube_tool = lambda url, _orig=orig_download_tool: _call_tool(_orig, url)
        else:
            server.download_audio_from_youtube_tool = lambda url: _call_tool(server.download_audio_from_youtube, url)

        if orig_transcribe_tool:
            server.transcribe_audio_tool = lambda p, _orig=orig_transcribe_tool: _call_tool(_orig, p)
        else:
            server.transcribe_audio_tool = lambda p: _call_tool(server.transcribe_audio, p)

        if orig_translate_tool:
            server.translate_text_to_japanese_tool = lambda t, _orig=orig_translate_tool: _call_tool(_orig, t)
        else:
            server.translate_text_to_japanese_tool = lambda t: _call_tool(server.translate_text_to_japanese, t)

    print("=== Demo A: start_transcription (full pipeline job API) ===")
    demo_start_transcription_via_job_api(example_url)

    print("\n=== Demo B: download -> create job from WAV (individual tools + job store) ===")
    demo_start_transcription_from_download(example_url)
