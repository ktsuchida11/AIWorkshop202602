"""
MCP サーバ接続・認証の統合テスト

対象サーバ:
  - jwt-server       (port 4444): JWT発行・検証・JWKS
  - indicator-mcp    (port 5555): JWT Bearer 認証
  - news-search-mcp  (port 6666): Google OAuth 2.0
  - youtube-transcribe (port 3333): 固定 Bearer token

実行方法:
  cd aws_llm/py_app
  uv run pytest tests/test_mcp_servers.py -v
"""

import pytest
import httpx

JWT_SERVER = "http://localhost:4444"
INDICATOR_MCP = "http://localhost:5555"
NEWS_SEARCH_MCP = "http://localhost:6666"
YOUTUBE_MCP = "http://localhost:3333"

ALICE = {"username": "alice", "password": "password123"}
BOB = {"username": "bob", "password": "securepassword"}


# ------------------------------------------------------------------ #
# Fixture: JWT トークン（alice）                                       #
# ------------------------------------------------------------------ #
@pytest.fixture(scope="module")
def jwt_token() -> str:
    """alice でログインして JWT トークンを取得する"""
    r = httpx.post(f"{JWT_SERVER}/login", json=ALICE, timeout=10)
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json().get("token", "")
    assert token, "token が空です"
    return token


# ================================================================== #
# 1. JWT サーバ（port 4444）
# ================================================================== #
class TestJWTServer:
    def test_login_alice(self):
        """alice でログインして token が返ること"""
        r = httpx.post(f"{JWT_SERVER}/login", json=ALICE, timeout=10)
        assert r.status_code == 200
        assert "token" in r.json()

    def test_login_bob(self):
        """bob でログインして token が返ること"""
        r = httpx.post(f"{JWT_SERVER}/login", json=BOB, timeout=10)
        assert r.status_code == 200
        assert "token" in r.json()

    def test_login_invalid_credentials(self):
        """不正な認証情報では 401 が返ること"""
        r = httpx.post(f"{JWT_SERVER}/login",
                       json={"username": "alice", "password": "wrong"},
                       timeout=10)
        assert r.status_code == 401

    def test_verify_valid_token(self, jwt_token):
        """有効な token の検証が成功すること"""
        r = httpx.post(f"{JWT_SERVER}/verify", json={"token": jwt_token}, timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body.get("valid") is True
        assert body["decoded"]["sub"] == "alice"
        assert "admin" in body["decoded"].get("role", "")

    def test_verify_invalid_token(self):
        """不正な token の検証が失敗すること"""
        r = httpx.post(f"{JWT_SERVER}/verify",
                       json={"token": "invalid.token.here"},
                       timeout=10)
        assert r.status_code in (200, 401)
        if r.status_code == 200:
            assert r.json().get("valid") is False

    def test_jwks_endpoint(self):
        """JWKS エンドポイントが RSA 公開鍵を返すこと"""
        r = httpx.get(f"{JWT_SERVER}/.well-known/jwks.json", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert "keys" in body
        assert len(body["keys"]) > 0
        key = body["keys"][0]
        assert key["kty"] == "RSA"
        assert key["alg"] == "RS256"


# ================================================================== #
# 2. Indicator MCP サーバ（port 5555）- JWT Bearer 認証               #
# ================================================================== #
class TestIndicatorMCP:
    def test_unauthenticated_returns_401(self):
        """認証なしのアクセスは 401 を返すこと"""
        r = httpx.get(f"{INDICATOR_MCP}/mcp", timeout=10)
        assert r.status_code == 401

    def test_authenticated_with_jwt(self, jwt_token):
        """JWT Bearer token での認証が通過すること（401 以外）"""
        r = httpx.get(
            f"{INDICATOR_MCP}/mcp",
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=10,
        )
        # MCP の streamable-http は GET に対して 405 を返すが、認証は通過している
        assert r.status_code != 401, (
            f"JWT 認証が拒否されました (401)。"
            f"jwt-server の再ビルドが必要な可能性があります。"
        )

    def test_invalid_token_returns_401(self):
        """不正な Bearer token は 401 を返すこと"""
        r = httpx.get(
            f"{INDICATOR_MCP}/mcp",
            headers={"Authorization": "Bearer invalid.token.here"},
            timeout=10,
        )
        assert r.status_code == 401


# ================================================================== #
# 3. News Search MCP サーバ（port 6274）- Google OAuth 2.0            #
# ================================================================== #
class TestNewsSearchMCP:
    def test_oauth_metadata(self):
        """OAuth メタデータエンドポイントが正常に返ること"""
        r = httpx.get(
            f"{NEWS_SEARCH_MCP}/.well-known/oauth-authorization-server",
            timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        assert "issuer" in body
        assert "authorization_endpoint" in body
        assert "token_endpoint" in body

    def test_unauthenticated_returns_401(self):
        """認証なしのアクセスは 401 を返すこと"""
        r = httpx.get(f"{NEWS_SEARCH_MCP}/mcp", timeout=10)
        assert r.status_code == 401
        # www-authenticate ヘッダが含まれること
        assert "www-authenticate" in r.headers

    def test_oauth_protected_resource_metadata(self):
        """OAuth protected resource メタデータが取得できること"""
        r = httpx.get(
            f"{NEWS_SEARCH_MCP}/.well-known/oauth-protected-resource/mcp",
            timeout=10,
        )
        assert r.status_code == 200


# ================================================================== #
# 4. File Transcriber MCP サーバ（port 3333）- 固定 Bearer token      #
#    StaticTokenVerifier で以下の2トークンを定義:                      #
#      dev-alice-token : scopes [read:data, write:data, admin:tools]  #
#      dev-guest-token : scopes [read:data]                           #
# ================================================================== #
class TestFileTranscriberMCP:
    def test_unauthenticated_returns_401(self):
        """認証なしのアクセスは 401 を返すこと"""
        r = httpx.get(f"{YOUTUBE_MCP}/mcp", timeout=10)
        assert r.status_code == 401

    def test_alice_token_works(self):
        """dev-alice-token（admin権限）での認証が通過すること"""
        r = httpx.get(
            f"{YOUTUBE_MCP}/mcp",
            headers={"Authorization": "Bearer dev-alice-token"},
            timeout=10,
        )
        assert r.status_code != 401, (
            "dev-alice-token が拒否されました。token を確認してください。"
        )

    def test_guest_token_works(self):
        """dev-guest-token（read:data のみ）での認証が通過すること"""
        r = httpx.get(
            f"{YOUTUBE_MCP}/mcp",
            headers={"Authorization": "Bearer dev-guest-token"},
            timeout=10,
        )
        assert r.status_code != 401, (
            "dev-guest-token が拒否されました。StaticTokenVerifier の設定を確認してください。"
        )

    def test_invalid_token_returns_401(self):
        """不正な Bearer token は 401 を返すこと"""
        r = httpx.get(
            f"{YOUTUBE_MCP}/mcp",
            headers={"Authorization": "Bearer invalid-token-xyz"},
            timeout=10,
        )
        assert r.status_code == 401
