import server


def test_mcp_and_tools_present(tmp_path):
    """
    このテストは、サーバーオブジェクトが正しく初期化され、必要な属性や機能を持っているかを検証するものです。

    主なテスト内容:
    1. `server` オブジェクトが `mcp` 属性を持ち、かつその名前が "YoutubeTranscribeMCP" であることを確認します。
    2. `server` オブジェクトが `transcribe_youtube_to_japanese` というツールを公開していることを確認します。
       - このツールは、名前属性を持つか、もしくは呼び出し可能である必要があります。
    3. 開発・テスト環境用に静的トークン認証 (`static_auth`) が設定されていることを確認します。
       - `static_tokens` 属性が存在し、特定のトークン（例: "dev-alice-token"）が含まれていることを検証します。
       - また、`mcp` が `static_auth` インスタンスを使用していることを確認します。
    4. テスト終了後にモックを元の状態に戻す処理を実行します。

    このテストは、サーバーの基本的な構成と依存関係が正しく設定されているかを保証するためのものです。
    """
    # サーバーオブジェクトのモックをインストールして、外部呼び出しを回避します。
    # レコードはここでは必要ありませんが、一貫性を保つために設定します。
    from helpers import install_mock_server
    m = install_mock_server(server, tmp_path)

    # サーバーオブジェクトが `mcp` インスタンスを持っていることを確認します。
    assert hasattr(server, "mcp"), "server.mcp が存在する必要があります"
    assert getattr(server.mcp, "name", None) == "YoutubeTranscribeMCP", "mcp.name が 'YoutubeTranscribeMCP' である必要があります"

    # サーバーが `transcribe_youtube_to_japanese` ツールを公開していることを確認します。
    assert hasattr(server, "transcribe_youtube_to_japanese"), "server は transcribe_youtube_to_japanese を公開する必要があります"
    obj = getattr(server, "transcribe_youtube_to_japanese")
    assert hasattr(obj, "name") or callable(obj), "transcribe_youtube_to_japanese は呼び出し可能であるか、または name 属性を持つ必要があります"

    # 開発・テスト環境用に静的トークン認証が設定されていることを確認します。
    assert hasattr(server, "static_auth"), "server はテスト用に static_auth を定義する必要があります"
    assert hasattr(server, "static_tokens"), "server は static_tokens を公開する必要があります"
    # 開発用トークンが存在することを確認します。
    assert "dev-alice-token" in server.static_tokens, "static_tokens に 'dev-alice-token' が含まれている必要があります"
    # `mcp` が `static_auth` インスタンスを使用していることを確認します。
    assert getattr(server.mcp, "auth", None) is server.static_auth, "mcp.auth は server.static_auth を使用する必要があります"

    # テスト終了後にモックを元の状態に戻します。
    try:
        m['restore']()
    except Exception:
        # 例外が発生した場合、サーバーが `_restore_mocks` を持っていればそれを呼び出します。
        if hasattr(server, '_restore_mocks'):
            server._restore_mocks()

