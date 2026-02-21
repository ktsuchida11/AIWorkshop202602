from flask import Flask, request, jsonify
import jwt
import datetime
import os

app = Flask(__name__)

# 秘密鍵（環境変数から取得）
SECRET_KEY = os.getenv("JWT_SECRET", "your-secret-key")

# 公開鍵と秘密鍵のペアを生成（RS256用）
PRIVATE_KEY = os.getenv("JWT_PRIVATE_KEY", None)
PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", None)

if not PRIVATE_KEY or not PUBLIC_KEY:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    PRIVATE_KEY = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode('utf-8')

    PUBLIC_KEY = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode('utf-8')

# ユーザー認証用のダミーデータ（ロール付き）
USERS = {
    "alice": {"password": "password123", "role": "admin"},
    "bob": {"password": "securepassword", "role": "user"}
}

# ロールごとのスコープ設定
ROLE_SCOPES = {
    "admin": ["read:data", "write:data", "admin:tools"],
    "user": ["read:data"]
}


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    # ユーザー認証
    user = USERS.get(username)
    if user and user["password"] == password:
        # ユーザーのロールに基づいてスコープを設定
        role = user["role"]
        scopes = ROLE_SCOPES.get(role, [])

        # JWTトークンを生成
        payload = {
            "sub": username,
            "role": role,
            "scopes": scopes,
            "iss": "http://localhost:4444",  # Issuer
            "aud": "your-mcp-server",       # Audience
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)  # 有効期限1時間
        }
        token = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256")
        return jsonify({"token": token})

    return jsonify({"error": "Invalid credentials"}), 401


@app.route("/verify", methods=["POST"])
def verify():
    token = request.json.get("token")
    try:
        decoded = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"], audience="your-mcp-server", issuer="http://localhost:4444")
        return jsonify({"valid": True, "decoded": decoded})
    except jwt.ExpiredSignatureError:
        return jsonify({"valid": False, "error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"valid": False, "error": "Invalid token"}), 401


@app.route("/.well-known/jwks.json", methods=["GET"])
def jwks():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    # 公開鍵を JWK 形式に変換
    from jose import jwk
    from jose.utils import base64url_encode

    public_key = serialization.load_pem_public_key(PUBLIC_KEY.encode('utf-8'))
    numbers = public_key.public_numbers()

    jwk_data = {
        "kty": "RSA",
        "use": "sig",
        "kid": "1",  # 任意の一意なキーID
        "alg": "RS256",
        "n": base64url_encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, byteorder="big")).decode("utf-8"),
        "e": base64url_encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, byteorder="big")).decode("utf-8"),
    }

    return jsonify({"keys": [jwk_data]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4444)