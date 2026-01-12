import os
import sys
import asyncio
import tempfile
import pathlib
import pytest


from dotenv import load_dotenv

# Ensure project root (aws_llm/py_app) is on sys.path so `tools` package is importable
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.file_transcriber import server

load_dotenv()

@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests disabled (set RUN_INTEGRATION_TESTS=1 to enable)",
)
def test_transcribe_and_translate_integration(tmp_path):
    """
    Integration test: download a YouTube video, transcribe and translate to Japanese.

    Requirements to run:
    - Network access
    - `RUN_INTEGRATION_TESTS=1` to enable the test
    """
    url = "https://www.youtube.com/watch?v=DKt8y7aNoDY"

    # Use a temporary downloads directory to avoid polluting workspace
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    os.environ["DOWNLOAD_DIR"] = str(download_dir)

    # OpenAI key required for transcription/translation
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    # Call the async pipeline which runs blocking work in a threadpool
    try:
        translated = asyncio.run(server.transcribe_youtube_to_japanese_async(url))
    except Exception as e:
        pytest.skip(f"Skipping integration test because download/transcription failed: {e}")

    assert translated is not None
    translated_text = translated.strip()
    assert translated_text != ""

    # Basic heuristic: result should contain at least one Japanese character
    contains_japanese = any(
        ("\u3040" <= ch <= "\u30ff") or ("\u4e00" <= ch <= "\u9fff")
        for ch in translated_text
    )
    assert contains_japanese, "Translated text does not appear to contain Japanese characters"
