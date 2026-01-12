import os
import tempfile
import yt_dlp
import time
import threading
import shutil
import subprocess
import asyncio
import argparse
import mimetypes

from typing import Any, Dict, List, Optional, Union

from pathlib import Path
from openai import OpenAI

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier  # , JWTVerifier
import warnings

from util import pretty_diarized_output

# pydub が内部で `audioop` を import するため Python 3.13 で DeprecationWarning が出る。
# テストやランタイムで不要な警告が出ないよう、import 時に該当の警告を抑制する。
with warnings.catch_warnings():
    # suppress pydub warnings that arise on newer Python versions
    warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*audioop.*")
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    from pydub import AudioSegment
from dotenv import load_dotenv

load_dotenv()


client = OpenAI()
# OpenAI API キーは環境変数にセットしておくこと
client.api_key = os.getenv("OPENAI_API_KEY")

# -------------------------------------------------------------------
# 1. JWT 設定（ここでは対称鍵 (HMAC) を使用する例）
# -------------------------------------------------------------------
# # クレーム	何を表すか	例
# # iss	トークンを発行した主体	https://auth.myservice.com
# # aud	トークンが使用される対象	https://api.myservice.com 或いは mcp-api

# jwt_jwks_uri = "https://your-auth-system.com/.well-known/jwks.json"
# jwt_issuer = "https://auth.myservice.com"
# jwt_audience = "https://auth.myservice.com"

# jwt_auth = JWTVerifier(
#     jwks_uri=jwt_jwks_uri,
#     issuer=jwt_issuer,
#     audience=jwt_audience
# )


# ---------------------------------------------------
# 1. StaticTokenVerifier の設定
# ---------------------------------------------------
# 開発／テスト用に静的に有効なトークンとそのクレームを定義
static_tokens = {
    # トークン文字列 : クレーム情報
    "dev-alice-token": {
        "client_id": "alice",
        "scopes": ["read:data", "write:data", "admin:tools"]
    },
    "dev-guest-token": {
        "client_id": "guest",
        "scopes": ["read:data"]
    }
}

# required_scopes は必須ではありませんが、
# 指定する場合はそのスコープ がトークンに含まれている必要があります
static_auth = StaticTokenVerifier(
    tokens=static_tokens,
    required_scopes=["read:data"]
)


# -------------------------------------------------------------------
# 2. FastMCP サーバー生成
# -------------------------------------------------------------------

mcp = FastMCP(name="YoutubeTranscribeMCP")
# use static auth for development/tests
mcp.auth = static_auth

# In-memory job store for background transcriptions
# job structure: {job_id: {status, progress, result, error}}
_jobs = {}
_jobs_lock = threading.Lock()


def _run_transcription_job(job_id: str, url: str) -> None:
    """Background worker that updates _jobs entry as it proceeds."""
    try:
        with _jobs_lock:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["progress"] = 0

        # 1) download
        with _jobs_lock:
            _jobs[job_id]["stage"] = "download"
            _jobs[job_id]["progress"] = 5

        downloaded_file = download_audio_from_youtube(url)

        with _jobs_lock:
            _jobs[job_id]["progress"] = 50

        # 2) transcribe
        with _jobs_lock:
            _jobs[job_id]["stage"] = "transcribe"
        text = transcribe_audio(downloaded_file)

        with _jobs_lock:
            _jobs[job_id]["progress"] = 85

        # 3) translate
        with _jobs_lock:
            _jobs[job_id]["stage"] = "translate"
        translated = translate_text_to_japanese(text)

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["progress"] = 100
            _jobs[job_id]["result"] = translated
            _jobs[job_id].pop("stage", None)
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
            _jobs[job_id]["progress"] = _jobs[job_id].get("progress", 0)


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed (code={p.returncode}):\n{p.stderr.strip()}")


def download_audio_from_youtube(url: str) -> List[str]:
    """
    YouTube の動画から音声をダウンロードして、mp3(96kbps, mono, 16kHz)に変換し、
    10分(600秒)ごとに分割したファイルパス一覧を返す。

    - 60分想定でも 10分×96kbps => 約7.2MB/チャンク で 25MB制限を安全に回避しやすい
    """
    download_dir = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
    download_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = os.getenv("FFMPEG_BIN", "ffmpeg")
    if shutil.which(ffmpeg_bin) is None:
        raise RuntimeError("ffmpeg not found in PATH. Install ffmpeg or set FFMPEG_BIN.")

    ts = int(time.time())
    outtmpl = str(download_dir / f"audio_{ts}.%(ext)s")

    ydl_opts = {
        # m4a優先、なければ bestaudio
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "noplaylist": True,
        # 失敗調査時は quiet=False, verbose=True 推奨
        # "verbose": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

        downloaded = ydl.prepare_filename(info)
        if not os.path.exists(downloaded):
            rd = (info.get("requested_downloads") or [{}])[0]
            downloaded = rd.get("filepath") or downloaded

        if not downloaded or not os.path.exists(downloaded):
            raise RuntimeError("yt-dlp did not produce an audio file (SABR等で失敗している可能性があります)。")

    # ffmpegで「変換しながら分割」する（中間mp3不要）
    # 10分ごと: -f segment -segment_time 600
    # チャンクは reset_timestamps して扱いやすくする
    chunk_dir = download_dir / f"chunks_{ts}"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_pattern = str(chunk_dir / "chunk_%03d.mp3")
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", downloaded,
        "-vn",
        "-ac", "1",          # mono
        "-ar", "16000",      # 16kHz
        "-b:a", "128k",       # 128kbps (固定)
        "-f", "segment",
        "-segment_time", "600",
        "-reset_timestamps", "1",
        chunk_pattern,
    ]
    _run(cmd)

    # チャンク列挙
    chunks = sorted(str(p) for p in chunk_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise RuntimeError("ffmpeg succeeded but no chunk files were created.")

    # 元のダウンロードファイルを消す（必要なら KEEP_ORIGINAL_AUDIO=1 で保持）
    if os.getenv("KEEP_ORIGINAL_AUDIO", "0") != "1":
        try:
            os.remove(downloaded)
        except OSError:
            pass

    return chunks


def transcribe_audio(file_path: Union[str, List[str]]) -> Union[str, List[Dict[str, str]]]:
    """
    OpenAI の Speech-to-Text モデルで文字起こし
    """
    # If multiple chunks are provided, transcribe each and return results as a list of dicts.
    if isinstance(file_path, list):
        results: List[Dict[str, str]] = []
        for p in file_path:
            try:
                text = transcribe_audio(p)
                results.append({"file": p, "text": text})
            except Exception as e:
                print(f"Error processing file {p}: {e}")
                results.append({"file": p, "error": str(e)})
        return results

    # single file path
    # Basic validation
    if not os.path.exists(file_path):
        raise RuntimeError(f"Audio file not found: {file_path}")
    size = os.path.getsize(file_path)
    if size == 0:
        raise RuntimeError(f"Audio file is empty: {file_path}")

    with open(file_path, "rb") as audio_file:
        # ensure pointer at start
        audio_file.seek(0)
        try:
            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model="gpt-4o-transcribe",
            )
            text = getattr(transcription, "text", "")
            print(f"Transcription response: {text}")
            return text
        except Exception as e:
            # Try to extract more info from the OpenAI error
            print("OpenAI transcription error:", repr(e))
            resp = getattr(e, "response", None)
            try:
                if resp is not None:
                    # httpx.Response-like
                    body = getattr(resp, "text", None)
                    if body:
                        print("OpenAI response body:", body)
            except Exception:
                pass
            # Re-raise for upstream handling
            raise


def transcribe_audio_diarize(
    file_path: Union[str, List[str]],
    *,
    language: Optional[str] = "ja",   # 例: "ja" / "en"（任意）
    prompt: Optional[str] = None,     # 任意（固有名詞が多い場合など）
    chunking_strategy: Any = "auto",  # diarizeでは必須（まずは "auto" 推奨）
) -> List[Dict[str, Any]]:
    """
    OpenAI の gpt-4o-transcribe-diarize で話者分離つき文字起こしを実行。

    Returns:
      [
        {
          "file": str,             # ファイルパス
          "text": str,             # 全体テキスト
          "segments": [            # 話者・時刻つきセグメント
            {"start": float, "end": float, "speaker": str, "text": str, ...},
            ...
          ],
          "duration": float|None,  # 入力音声長（返る場合）
          "usage": dict|None       # 使用量（返る場合）
        },
        ...
      ]
    """

    # If multiple chunks are provided, process each file individually
    if isinstance(file_path, list):
        results = []
        for p in file_path:
            try:
                result = transcribe_audio_diarize(
                    p, language=language, prompt=prompt, chunking_strategy=chunking_strategy
                )
                result["file"] = p
                results.append(result)
            except Exception as e:
                results.append({"file": p, "error": str(e)})
        return results

    # single file path handling (original behaviour)
    path = Path(file_path)
    if not path.exists():
        raise RuntimeError(f"Audio file not found: {path}")
    size = path.stat().st_size
    if size == 0:
        raise RuntimeError(f"Audio file is empty: {path}")

    # Content-Type 推定（multipartの安定性のため明示する）
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    with path.open("rb") as audio_file:
        audio_file.seek(0)
        try:
            resp = client.audio.transcriptions.create(
                model="gpt-4o-transcribe-diarize",
                file=(path.name, audio_file, content_type),
                response_format="diarized_json",
                chunking_strategy=chunking_strategy,
                **({"language": language} if language else {}),
                **({"prompt": prompt} if prompt else {}),
            )

            # openai-python の返却はオブジェクトのため、防御的に取り出す
            text = getattr(resp, "text", None) or ""
            segments = getattr(resp, "segments", None)

            # segments が取れない場合は to_dict()/model_dump() を試す（SDK差異吸収）
            if segments is None:
                to_dict = getattr(resp, "to_dict", None)
                if callable(to_dict):
                    d = to_dict()
                else:
                    model_dump = getattr(resp, "model_dump", None)
                    d = model_dump() if callable(model_dump) else {}
                segments = d.get("segments")

            result = {
                "text": text,
                "segments": segments or [],
                "duration": getattr(resp, "duration", None),
                "usage": getattr(resp, "usage", None),
            }

            # 目視確認ログ（必要なければ消してOK）
            print(f"[diarize] text_len={len(result['text'])} segments={len(result['segments'])}")
            return result

        except Exception as e:
            # エラー詳細（可能な範囲で）
            print("OpenAI diarize transcription error:", repr(e))
            resp = getattr(e, "response", None)
            try:
                if resp is not None:
                    body = getattr(resp, "text", None)
                    if body:
                        print("OpenAI response body:", body)
            except Exception:
                pass
            raise


def translate_text_to_japanese(text: str) -> str:
    """
    OpenAI の Chat Completions を使って日本語翻訳
    """
    response = client.chat.completions.create(
        model="gpt-5.1-mini",
        messages=[
            {"role": "system", "content": "以下のテキストを自然な日本語に翻訳してください。"},
            {"role": "user", "content": text}
        ]
    )
    return response.choices[0].message.content.strip()


# -------------------------------------------------------------------
# 3. MCP ツール定義（MCP のエンドポイント関数）
# -------------------------------------------------------------------
# @mcp.tool()
# def transcribe_youtube_to_japanese_tool(url: str) -> str:
#     """
#     同期MCPツール:
#     YouTubeのURLから音声をダウンロードし、
#     文字起こしを行う
#     """
#     # 1) 音声抽出
#     download_file = download_audio_from_youtube(url)
#     # 2) 文字起こし
#     text = transcribe_audio(download_file)

#     return text


@mcp.tool()
async def transcribe_youtube_to_japanese_async_tool(
    file_paths: Union[str, List[str]],
) -> List[Dict[str, Any]]:
    """
    非同期でローカルファイルパスまたはチャンクリストを文字起こしするMCPツール。

    この関数は、指定された音声ファイルまたはチャンクリストを非同期で処理し、
    各ファイルの文字起こし結果を返します。結果はファイル名順にソートされます。

    利用方法:
    - 単一のファイルパスを指定する場合:
        result = await transcribe_youtube_to_japanese_async_tool("path/to/audio/file.mp3")
    - 複数のファイルパスをリストで指定する場合:
        result = await transcribe_youtube_to_japanese_async_tool(["file1.mp3", "file2.mp3"])

    引数:
        file_paths (Union[str, List[str]]): 
            - 文字起こしを行うローカルファイルのパス（文字列）または
              ファイルパスのリスト。

    戻り値:
        List[Dict[str, Any]]:
            - 各ファイルの処理結果を含む辞書のリスト。
            - 辞書の形式:
                {
                    "file": str,  # 入力ファイルのパス
                    "result": str,  # 文字起こし結果（成功時）
                    "error": str,  # エラーメッセージ（失敗時、オプション）
            - リストはファイル名順にソートされて返されます。

    例外:
        - 内部で発生した例外はキャッチされ、結果の辞書に "error" キーとして含まれます。

    注意:
        - この関数は非同期関数であるため、呼び出しには `await` が必要です。
        - 入力ファイルが存在しない場合やサポートされていない形式の場合、
          エラーが結果に含まれる可能性があります。
    """
    loop = asyncio.get_running_loop()

    def _run(file_path):
        try:
            # transcribe_audio を使用して文字起こしを実行
            transcription = transcribe_audio(file_path)
            return {
                "file": file_path,
                "result": transcription,
            }
        except Exception as e:
            return {"file": file_path, "error": str(e)}

    # ファイルを順番に処理
    tasks = [loop.run_in_executor(None, _run, path) for path in (file_paths if isinstance(file_paths, list) else [file_paths])]
    results = await asyncio.gather(*tasks)

    # 処理後にファイル名順に並べ替え
    return sorted(results, key=lambda x: x["file"])


# -------------------------------------------------------------------
# 分離されたツール: ダウンロード / 文字起こし / 翻訳
# 各処理について同期ツールと非同期ツールを公開する
# -------------------------------------------------------------------

# @mcp.tool()
# def download_audio_from_youtube_tool(url: str) -> str:
#     """
#     同期ツール:
#     指定されたYouTubeのURLから音声をダウンロードし、
#     m4a形式のファイルパスを返します。
#     このツールは文字起こしはしないです。
#     """
#     return download_audio_from_youtube(url)

# @mcp.tool()
# def transcribe_audio_tool(file_path: str) -> str:
#     """
#     同期ツール:
#     指定された音声ファイルをOpenAIのSpeech-to-Textモデルを使用して文字起こしし、
#     文字列として返します。
#     """
#     return transcribe_audio(file_path)

# @mcp.tool()
# def translate_text_to_japanese_tool(text: str) -> str:
#     """
#     同期ツール:
#     指定されたテキストをOpenAIのChat Completionsを使用して
#     日本語に翻訳し、翻訳結果を文字列として返します。
#     """
#     return translate_text_to_japanese(text)
# @mcp.tool()
# def transcribe_youtube_to_japanese_tool_diarize_tool(
#     url: str,
# ) -> Dict[str, Any]:
#     """
#     同期ツール: 指定した音声ファイルを話者分離付きで文字起こしし,
#     `pretty_diarized_output` の出力（dict）を返します。
#     """

#     # 1) 音声抽出
#     download_file = download_audio_from_youtube(url)

#     # 2) 話者分離付き文字起こし
#     diarized = transcribe_audio_diarize(
#         download_file,
#         language="ja",
#         prompt=None,
#         chunking_strategy="auto",
#     )

#     speaker_names = {
#         "A": "話者A",
#         "B": "話者B",
#         "C": "話者C",
#     }

#     pretty = pretty_diarized_output(diarized, speaker_names=speaker_names)
#     return pretty

# -------------------------------------------------------------------
# 話者分離付き文字起こしツール
# -------------------------------------------------------------------
@mcp.tool()
async def transcribe_youtube_to_japanese_diarize_async_tool(
    file_paths: Union[str, List[str]],
) -> List[Dict[str, Any]]:
    """
    このツールは、指定された音声ファイルまたはチャンクリストを日本語で文字起こしし、
    話者分離を行った結果を返します。話者はデフォルトで「話者A」「話者B」「話者C」として
    識別されますが、必要に応じてカスタマイズ可能です。

    利用方法:
        - `file_paths` にローカルの音声ファイルパス（文字列）または複数のファイルパスを含むリストを渡します。
        - 非同期関数として呼び出す必要があります。

    引数:
        file_paths (Union[str, List[str]]): 
            処理対象のローカル音声ファイルパス（文字列）またはファイルパスのリスト。

    戻り値:
        List[Dict[str, Any]]:
            各ファイルに対する処理結果のリスト。各結果は以下の形式の辞書です:
            - "file" (str): 処理対象のファイルパス。
            - "result" (str): 話者分離付きの文字起こし結果（整形済み）。
            - "error" (str, optional): 処理中に発生したエラー（エラーが発生した場合のみ）。

    出力例:
        [
            {
                "file": "/path/to/audio1.mp3",
                "result": "話者A: こんにちは。\n話者B: おはようございます。",
            },
            {
                "file": "/path/to/audio2.mp3",
                "error": "ファイルが見つかりません。",
        ]

    注意:
        - 音声ファイルは日本語であることを前提としています。
        - 処理は非同期で行われるため、関数を呼び出す際には `await` を使用してください。
        - 話者名はデフォルトで「話者A」「話者B」「話者C」として設定されていますが、
          必要に応じて `speaker_names` を変更してください。
    """
    language = "ja"
    prompt = None
    chunking_strategy = "auto"
    speaker_names = {
        "A": "話者A",
        "B": "話者B",
        "C": "話者C",
    }

    loop = asyncio.get_running_loop()

    def _run(file_path):
        try:
            diarized = transcribe_audio_diarize(
                file_path,
                language=language,
                prompt="句読点を適切に付与し、固有名詞は自然な表記にしてください。",
                chunking_strategy=chunking_strategy,
            )
            return {
                "file": file_path,
                "result": pretty_diarized_output(diarized, speaker_names=speaker_names or {}),
            }
        except Exception as e:
            return {"file": file_path, "error": str(e)}

    # ファイルを順番に処理
    tasks = [loop.run_in_executor(None, _run, path) for path in (file_paths if isinstance(file_paths, list) else [file_paths])]
    results = await asyncio.gather(*tasks)

    # 処理後にファイル名順に並べ替え
    return sorted(results, key=lambda x: x["file"])


# -------------------------------------------------------------------
# 非同期ジョブ API
# -------------------------------------------------------------------

@mcp.tool()
async def download_audio_from_youtube_async_tool(url: str) -> List[str]:
    """
    非同期ツール:
    指定されたYouTubeのURLから音声をダウンロードします。
    ダウンロード処理をスレッドで実行し、await可能な形で
    チャンク化された音声ファイルのパス一覧（List[str]）を返します。

    使用例:
        chunks = await download_audio_from_youtube_async_tool(url)
        # chunks は transcribe_youtube_to_japanese_async_tool にそのまま渡せます

    引数:
        url (str): ダウンロード対象のYouTube動画のURL。

    戻り値:
        List[str]: チャンク化された音声ファイルのパス一覧。
        各ファイルは10分ごとに分割され、mp3形式（128kbps, mono, 16kHz）で保存されます。

    出力例:
        [
            "downloads/chunks_1691234567/chunk_000.mp3",
            "downloads/chunks_1691234567/chunk_001.mp3",
            ...
        ]

    注意:
        - ダウンロードされた音声ファイルは、環境変数 `DOWNLOAD_DIR` で指定された
          ディレクトリ（デフォルトは "downloads"）に保存されます。
        - ffmpeg がインストールされている必要があります。
        - ダウンロードされた元の音声ファイルは、環境変数 `KEEP_ORIGINAL_AUDIO` が "1" に
          設定されていない限り削除されます。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, download_audio_from_youtube, url)


@mcp.tool()
async def translate_text_to_japanese_async_tool(text: str) -> str:
    """
    非同期ツール:
    指定されたテキストを日本語に翻訳します。
    翻訳処理をスレッドで実行し、await可能な形で翻訳結果を文字列として返します。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, translate_text_to_japanese, text)


# -------------------------------------------------------------------
# 4. サーバー起動
# -------------------------------------------------------------------
# By default only start the server when executed as a script. When running
# tests or importing the module in other contexts set `MCP_TESTING=1` to
# prevent accidental server startup during import.
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Run the MCP server or test specific functionality.")
    parser.add_argument("--test", action="store_true", help="Run in test mode (skip mcp.run())")
    # Use parse_known_args to avoid argparse exiting the process
    # when unexpected CLI args are passed (e.g. by container runtimes).
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"Ignored unknown CLI args: {unknown}")

    if args.test:
        print("Test mode enabled; skipping mcp.run() to allow test import")

        # ここに指定のURLからデータをダウンロードするテストコードなどを追加
        url = "https://www.youtube.com/watch?v=py16SJh_78U" # 日銀会見　Long テスト用
        url = "https://www.youtube.com/watch?v=DKt8y7aNoDY"
        downloaded_chunks = download_audio_from_youtube(url)
        print(f"Downloaded chunks: {downloaded_chunks}")

        # ダウンロードしたチャンクを文字起こしするテストコードを追加
        transcription = transcribe_audio(downloaded_chunks)
        print(f"Transcription: {transcription[:100]}...")

        # ダウンロードしたチャンクを話者分離付きで文字起こしするテストコードを追加
        diarized_result = transcribe_audio_diarize(
            downloaded_chunks,
            language="ja",
            prompt=None,
            chunking_strategy="auto"
        )

        pretty = pretty_diarized_output(
            diarized_result,
            speaker_names={
                "A": "話者A",
                "B": "話者B",
                "C": "話者C",
            }
        )

        print(pretty["dialogue"])

    else:
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=3333
        )

