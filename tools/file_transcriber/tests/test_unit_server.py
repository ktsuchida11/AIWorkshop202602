import shutil
import pytest
from pydub import AudioSegment

import server


# このテストファイルは、`server`モジュールのユニットテストを行うためのものです。
# ユニットテストでは、外部サービス（YouTubeやOpenAIなど）を呼び出さず、
# 小さな関数単位での動作確認を行います。

def test_transcribe_audio_file_not_found():
    # このテストは、存在しないオーディオファイルを指定した場合に
    # `server.transcribe_audio`関数が正しくFileNotFoundErrorをスローするかを確認します。

    # 他のテストでモックがインストールされている場合に備え、モックを解除
    if hasattr(server, '_restore_mocks'):
        server._restore_mocks()

    # 存在しないファイルを指定してFileNotFoundErrorが発生することを確認
    with pytest.raises(FileNotFoundError):
        server.transcribe_audio("nonexistent_file.wav")


def test_translate_text_to_japanese_mock(tmp_path):
    # このテストは、`server.translate_text_to_japanese`関数をモック化して、
    # 正しく翻訳結果が返されるかを確認します。

    # `install_mock_server`を使用してモックをインストール
    from helpers import install_mock_server
    m = install_mock_server(server, tmp_path)

    # モック化された関数を呼び出し、期待される結果が返るか確認
    out = server.translate_text_to_japanese("hello world")
    # モック関数は "こんにちは世界" を返すよう設定されている
    assert out == "こんにちは世界"

    # 他のテストに影響を与えないよう、モックを解除
    try:
        m['restore']()
    except Exception:
        if hasattr(server, '_restore_mocks'):
            server._restore_mocks()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_audiosegment_load_and_export(tmp_path):
    # このテストは、pydubを使用してオーディオファイルを生成し、
    # 正しくエクスポートできるかを確認します。

    # 500ミリ秒の無音のWAVファイルを作成
    seg = AudioSegment.silent(duration=500)

    # 一時ディレクトリにファイルをエクスポート
    path = tmp_path / "test.wav"
    seg.export(path, format="wav")

    # ファイルが正しくエクスポートされたことを確認
    assert path.exists()
