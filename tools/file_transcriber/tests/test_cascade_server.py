import pytest

import server


def test_transcribe_youtube_to_japanese_orchestration(tmp_path):
    # テスト用のモックサーバーをインストールし、呼び出し履歴を記録するためのヘルパー関数を使用
    from helpers import install_mock_server

    # 呼び出し履歴を格納するリスト
    calls = []
    # モックサーバーをインストールし、元の関数をモックに置き換える
    m = install_mock_server(server, tmp_path, calls=calls)

    # --- 同期ツールチェインを呼び出す ---
    wav = server.download_audio_from_youtube_tool("https://www.youtube.com/watch?v=39iH2IKLeKA")
    assert isinstance(wav, str) and wav.endswith(".wav")

    text = server.transcribe_audio_tool(wav)
    assert isinstance(text, str) and text == "Hello world"

    translated = server.translate_text_to_japanese_tool(text)
    assert translated == "こんにちは世界"

    # テスト終了後にモックを元の関数に戻し、他のテストに影響を与えないようにする
    try:
        m['restore']()
    except Exception:
        # 古い形式のモック復元メソッドが存在する場合に対応
        if hasattr(server, '_restore_mocks'):
            server._restore_mocks()


def test_transcribe_youtube_tool_chain_async(tmp_path):
    """非同期ツール版のチェインを検証する（async -> await 可能）。"""
    from helpers import install_mock_server

    calls = []
    m = install_mock_server(server, tmp_path, calls=calls)

    # use asyncio.run to await the async tool wrappers
    import asyncio

    async def run_chain():
        wav = await server.download_audio_from_youtube_async_tool("https://www.youtube.com/watch?v=39iH2IKLeKA")
        assert isinstance(wav, str) and wav.endswith(".wav")

        text = await server.transcribe_audio_async_tool(wav)
        assert isinstance(text, str) and text == "Hello world"

        translated = await server.translate_text_to_japanese_async_tool(text)
        assert translated == "こんにちは世界"

    asyncio.run(run_chain())

    # restore
    try:
        m['restore']()
    except Exception:
        if hasattr(server, '_restore_mocks'):
            server._restore_mocks()
