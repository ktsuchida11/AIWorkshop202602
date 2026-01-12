import inspect


def call_tool(obj, *a, **kw):
    """Call an object that may be an MCP tool wrapper by extracting
    a known underlying callable attribute if needed.

    This centralizes the logic used across examples and tests.
    """
    if callable(obj):
        return obj(*a, **kw)
    for attr in ("fn", "func", "__wrapped__"):
        f = getattr(obj, attr, None)
        if callable(f):
            return f(*a, **kw)
    raise TypeError(f"Tool object {obj!r} is not callable and has no known underlying function")


def install_mock_server(server_module, tmp_path, calls: list | None = None):
    """Install simple mock implementations on the given server module.

    If `calls` is provided, each mock will append a tuple describing the call
    so tests can assert ordering and arguments.

    Returns a dict of the fake functions for inspection if needed.
    """
    from pathlib import Path

    def fake_download(url: str) -> str:
        if calls is not None:
            calls.append(("download", url))
        p = Path(tmp_path) / "dummy.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"RIFF....")
        print("[mock] fake_download ->", p)
        return str(p)

    def fake_transcribe(path: str) -> str:
        if calls is not None:
            calls.append(("transcribe", path))
        print("[mock] fake_transcribe ->", path)
        return "Hello world"

    def fake_translate(text: str) -> str:
        if calls is not None:
            calls.append(("translate", text))
        print("[mock] fake_translate ->", text)
        return "こんにちは世界"

    # Save originals so we can restore after tests
    originals = {
        'download_audio_from_youtube': getattr(server_module, 'download_audio_from_youtube', None),
        'transcribe_audio': getattr(server_module, 'transcribe_audio', None),
        'translate_text_to_japanese': getattr(server_module, 'translate_text_to_japanese', None),
        'download_audio_from_youtube_tool': getattr(server_module, 'download_audio_from_youtube_tool', None),
        'transcribe_audio_tool': getattr(server_module, 'transcribe_audio_tool', None),
        'translate_text_to_japanese_tool': getattr(server_module, 'translate_text_to_japanese_tool', None),
        'download_audio_from_youtube_async_tool': getattr(server_module, 'download_audio_from_youtube_async_tool', None),
        'transcribe_audio_async_tool': getattr(server_module, 'transcribe_audio_async_tool', None),
        'translate_text_to_japanese_async_tool': getattr(server_module, 'translate_text_to_japanese_async_tool', None),
    }

    server_module.download_audio_from_youtube = fake_download
    server_module.transcribe_audio = fake_transcribe
    server_module.translate_text_to_japanese = fake_translate

    # Capture existing MCP-wrapped tool objects so callers can still invoke them
    orig_download_tool = getattr(server_module, 'download_audio_from_youtube_tool', None)
    orig_transcribe_tool = getattr(server_module, 'transcribe_audio_tool', None)
    orig_translate_tool = getattr(server_module, 'translate_text_to_japanese_tool', None)

    # Provide tool-callable proxies that use call_tool on the original wrappers
    if orig_download_tool:
        server_module.download_audio_from_youtube_tool = lambda url, _orig=orig_download_tool: call_tool(_orig, url)
    else:
        server_module.download_audio_from_youtube_tool = lambda url: call_tool(server_module.download_audio_from_youtube, url)

    if orig_transcribe_tool:
        server_module.transcribe_audio_tool = lambda p, _orig=orig_transcribe_tool: call_tool(_orig, p)
    else:
        server_module.transcribe_audio_tool = lambda p: call_tool(server_module.transcribe_audio, p)

    if orig_translate_tool:
        server_module.translate_text_to_japanese_tool = lambda t, _orig=orig_translate_tool: call_tool(_orig, t)
    else:
        server_module.translate_text_to_japanese_tool = lambda t: call_tool(server_module.translate_text_to_japanese, t)

    # async tool proxies
    orig_download_async = getattr(server_module, 'download_audio_from_youtube_async_tool', None)
    orig_transcribe_async = getattr(server_module, 'transcribe_audio_async_tool', None)
    orig_translate_async = getattr(server_module, 'translate_text_to_japanese_async_tool', None)

    if orig_download_async:
        async def _download_async(url, _orig=orig_download_async):
            res = call_tool(_orig, url)
            if inspect.isawaitable(res):
                return await res
            return res

        server_module.download_audio_from_youtube_async_tool = _download_async
    else:
        async def _download_async(url):
            res = call_tool(server_module.download_audio_from_youtube, url)
            if inspect.isawaitable(res):
                return await res
            return res

        server_module.download_audio_from_youtube_async_tool = _download_async

    if orig_transcribe_async:
        async def _transcribe_async(p, _orig=orig_transcribe_async):
            res = call_tool(_orig, p)
            if inspect.isawaitable(res):
                return await res
            return res

        server_module.transcribe_audio_async_tool = _transcribe_async
    else:
        async def _transcribe_async(p):
            res = call_tool(server_module.transcribe_audio, p)
            if inspect.isawaitable(res):
                return await res
            return res

        server_module.transcribe_audio_async_tool = _transcribe_async

    if orig_translate_async:
        async def _translate_async(t, _orig=orig_translate_async):
            res = call_tool(_orig, t)
            if inspect.isawaitable(res):
                return await res
            return res

        server_module.translate_text_to_japanese_async_tool = _translate_async
    else:
        async def _translate_async(t):
            res = call_tool(server_module.translate_text_to_japanese, t)
            if inspect.isawaitable(res):
                return await res
            return res

        server_module.translate_text_to_japanese_async_tool = _translate_async

    def _restore():
        # restore saved originals
        for name, val in originals.items():
            if val is None:
                if hasattr(server_module, name):
                    try:
                        delattr(server_module, name)
                    except Exception:
                        pass
            else:
                setattr(server_module, name, val)

    # attach restore helper to module so tests can invoke it
    setattr(server_module, '_restore_mocks', _restore)

    return {
        'download': fake_download,
        'transcribe': fake_transcribe,
        'translate': fake_translate,
        'restore': _restore,
    }
