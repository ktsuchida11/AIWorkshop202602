import os
import json
import sqlite3
from datetime import datetime
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from mcp.server.fastmcp import FastMCP
from urllib.parse import urlparse, unquote

# 環境変数で上書き可能
DB_PATH = os.environ.get("BOJ_RAG_DB_PATH", "./db/boj_rag.sqlite3")
OPENAI_MODEL = os.environ.get("BOJ_RAG_EMBED_MODEL", "text-embedding-3-small")

mcp = FastMCP("boj-minutes-rag")


# ----------------------------------------------------------------------
# SQLite 初期化・接続
# ----------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # documents テーブルに年、resource、published_date を追加して管理する
    conn.execute(
        """CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT,
            meeting_date TEXT,
            source_url TEXT,
            lang TEXT,
            created_at TEXT,
            year INTEGER,
            resource TEXT,
            published_date TEXT
        );"""
    )

    # 既存 DB に対しては念のため不足カラムを追加する（無ければ ALTER TABLE）
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(documents);")
    cols = [r[1] for r in cur.fetchall()]
    if "year" not in cols:
        try:
            cur.execute("ALTER TABLE documents ADD COLUMN year INTEGER;")
        except Exception:
            pass
    if "resource" not in cols:
        try:
            cur.execute("ALTER TABLE documents ADD COLUMN resource TEXT;")
        except Exception:
            pass
    if "published_date" not in cols:
        try:
            cur.execute("ALTER TABLE documents ADD COLUMN published_date TEXT;")
        except Exception:
            pass

    conn.execute(
        """CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT,
            chunk_index INTEGER,
            content TEXT,
            embedding TEXT,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );"""
    )

    return conn


# ----------------------------------------------------------------------
# OpenAI Embedding
# ----------------------------------------------------------------------
_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            
        )
    return _client


def embed_texts(texts: List[str]) -> List[List[float]]:
    client = get_client()
    resp = client.embeddings.create(
        model=OPENAI_MODEL,
        input=texts,
    )
    return [item.embedding for item in resp.data]


# ----------------------------------------------------------------------
# テキストのチャンク分割 & 類似度
# ----------------------------------------------------------------------
def chunk_text(text: str, max_chars: int = 1200, overlap: int = 200) -> List[str]:
    """シンプルな文字数ベースのチャンク分割"""
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + max_chars)
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= n:
            break
        # オーバーラップさせつつ次へ
        start = max(0, end - overlap)
    return chunks


def cosine_similarity(a: List[float], b: List[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ----------------------------------------------------------------------
# インデックス登録ロジック
# ----------------------------------------------------------------------
def upsert_document_with_chunks(
    doc_id: str,
    title: str,
    meeting_date: str,
    url: str,
    lang: str,
    content: str,
    year: int | None = None,
    resource: str | None = None,
    published_date: str | None = None,
) -> int:
    """1つの議事要旨全文をチャンク分割＋ベクトル化してSQLiteに保存"""
    conn = get_db()
    cur = conn.cursor()

    # created_at を JST で保存
    from datetime import timezone, timedelta

    jst = timezone(timedelta(hours=9))
    created_at = datetime.now(jst).isoformat()

    cur.execute(
        "INSERT OR REPLACE INTO documents "
        "(id, title, meeting_date, source_url, lang, created_at, year, resource, published_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            doc_id,
            title,
            meeting_date,
            url,
            lang,
            created_at,
            year,
            resource,
            published_date,
        ),
    )

    # 既存チャンクは削除
    cur.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))

    chunks = chunk_text(content)
    embeddings = embed_texts(chunks)

    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        cur.execute(
            "INSERT INTO chunks (doc_id, chunk_index, content, embedding) "
            "VALUES (?, ?, ?, ?)",
            (doc_id, idx, chunk, json.dumps(emb)),
        )

    conn.commit()
    conn.close()
    return len(chunks)


def search_chunks(query: str, top_k: int = 5) -> List[Tuple[float, dict]]:
    """クエリに対して全チャンクを走査し、コサイン類似度上位を返す"""
    conn = get_db()
    cur = conn.cursor()

    query_emb = embed_texts([query])[0]

    cur.execute(
        "SELECT chunks.id, chunks.doc_id, chunks.content, chunks.embedding, "
        "documents.title, documents.meeting_date, documents.source_url, documents.year, "
        "documents.resource, documents.published_date "
        "FROM chunks "
        "JOIN documents ON chunks.doc_id = documents.id"
    )
    rows = cur.fetchall()

    scored: List[Tuple[float, dict]] = []
    for row in rows:
        chunk_id, doc_id, content, emb_json, title, meeting_date, url, year, resource, published_date = row
        emb = json.loads(emb_json)
        score = cosine_similarity(query_emb, emb)
        scored.append(
            (
                score,
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "title": title,
                    "meeting_date": meeting_date,
                    "source_url": url,
                    "year": year,
                    "resource": resource,
                    "published_date": published_date,
                    "content": content,
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    conn.close()
    return scored[:top_k]


# ----------------------------------------------------------------------
# 日銀「Past Monetary Policy Meetings」から議事要旨PDF一覧取得
# ----------------------------------------------------------------------
PAST_MPM_URL_EN = "https://www.boj.or.jp/en/mopo/mpmsche_minu/past.htm"
PAST_MPM_URL_INDEX_EN = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
PAST_MPM_URL_JA = "https://www.boj.or.jp/mopo/mpmsche_minu/past.htm"
PAST_MPM_URL_INDEX_JA = "https://www.boj.or.jp/mopo/mpmsche_minu/index.htm"


def fetch_boj_minutes_pdf_links(year: int, lang: str = "en") -> List[Tuple[str, str, str, str, str]]:
    """
    Past Monetary Policy Meetings ページから、指定年の
    「MPM Minutes」列の PDF リンクを全件取得。
    """
    # 今年のデータは index ページに載ることがあるため、year が今年なら index URL を使う
    current_year = datetime.now().year
    if year == current_year:
        url = PAST_MPM_URL_INDEX_EN if lang == "en" else PAST_MPM_URL_INDEX_JA
    else:
        url = PAST_MPM_URL_EN if lang == "en" else PAST_MPM_URL_JA

    resp = requests.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 見出し (h2/h3) に "2024年" のように年が書いてあるので、それを起点にテーブルを取る
    def is_year_header(tag):
        if tag.name not in ("h2", "h3"):
            return False
        text = tag.get_text(strip=True)
        # ページでは "2024年" のようになっているため、年の数字が含まれているかで判定する
        return str(year) in text

    year_header = soup.find(is_year_header)
    if not year_header:
        raise ValueError(f"Year {year} section not found on {url}")

    table = year_header.find_next("table")
    if table is None:
        raise ValueError(f"No table found for year {year}")

    # 戻り値: (doc_id, minutes_url, minutes_published_date, press_url, press_published_date)
    results: List[Tuple[str, str, str, str, str]] = []
    import re

    def filename_from_url(u: str) -> str | None:
        if not u:
            return None
        try:
            p = urlparse(u).path
            name = os.path.basename(p)
            return unquote(name) if name else None
        except Exception:
            return None

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue

        date_cell = cells[0]

        # 行内のリンクを全部確認して、議事要旨(minu_YYYY/gYYYYMMDD*.pdf) と 記者会見(kaiken_YYYY/kkYYYYMMDD*.pdf) を探す
        minutes_url = None
        minutes_pub = None
        press_url = None
        press_pub = None
        for a in row.find_all("a", href=True):
            href = a["href"]
            # minutes のパスには /minu_YYYY/ または "minu_" が含まれることが多い
            if "/minu_" in href or re.search(r"/minu_\d{4}|minu_\d{2,}", href):
                minutes_url = requests.compat.urljoin(url, href)
                # published_date はファイル名から取得
                minutes_pub = filename_from_url(minutes_url)
            # 記者会見は /kaiken_ 以下や "kaiken" を含むリンク
            elif "/kaiken_" in href or re.search(r"/kaiken_\d{4}|kaiken_\d{2,}", href):
                press_url = requests.compat.urljoin(url, href)
                # published_date はファイル名から取得
                press_pub = filename_from_url(press_url)

        if not minutes_url:
            # 見つからなければ、列の位置から試す（互換性確保）
            if len(cells) >= 4:
                maybe = cells[3].find("a", href=True)
                if maybe:
                    minutes_url = requests.compat.urljoin(url, maybe["href"]) if maybe.get("href") else None
                    minutes_pub = filename_from_url(minutes_url) or minutes_pub

        if not minutes_url:
            # 議事要旨が見つからなければスキップ
            continue

        meeting_label = date_cell.get_text(strip=True)
        # 世代一意な ID（年 + 日付ラベルを適当に整形）
        safe_label = re.sub(r"[\s\.,、・（）()\[\]]+", "", meeting_label)
        safe_label = re.sub(r"[^0-9A-Za-z_-]", "", safe_label)
        doc_id = f"{year}_{safe_label}"

        # 各行ごとに結果リストへ追加（インデントが浅いと最後の1件しか残らない不具合の修正）
        results.append((doc_id, minutes_url, minutes_pub, press_url, press_pub))

    return results


def pdf_to_text(pdf_bytes: bytes) -> str:
    """PDF バイナリからテキスト抽出"""
    from io import BytesIO
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    texts: List[str] = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n".join(texts)


# ----------------------------------------------------------------------
# MCP ツール定義
# ----------------------------------------------------------------------
@mcp.tool()
async def ingest_boj_minutes_for_year(
    year: int,
    lang: str = "jp",
    resource: str = "both",
) -> str:
    """
    日銀の Past Monetary Policy Meetings ページから
    指定年の MPM Minutes(PDF) を取得し、SQLite + ベクトルに登録します。
    """
    """
    resource: 'minutes' (default) | 'press' | 'both'

    指定に応じて議事要旨（minutes）／定例記者会見（press）のPDFを取得してインデックス登録します。
    議事要旨は documents.id にそのまま保存されます。記者会見を登録する場合は doc_id に
    '_press' サフィックスを付与して別ドキュメントとして保存します（衝突回避のため）。
    """

    allowed = {"minutes", "press", "both"}
    if resource not in allowed:
        raise ValueError(f"resource must be one of {allowed}")

    links = fetch_boj_minutes_pdf_links(year, lang=lang)

    session = requests.Session()
    total_chunks = 0
    minutes_docs = 0
    press_docs = 0

    for doc_id, minutes_url, minutes_pub, press_url, press_pub in links:
        meeting_date = doc_id.split("_", 1)[-1]

        # 議事要旨を登録する場合
        if resource in ("minutes", "both") and minutes_url:
            try:
                pdf_resp = session.get(minutes_url)
                pdf_resp.raise_for_status()
                text = pdf_to_text(pdf_resp.content)

                title = f"BOJ MPM Minutes {doc_id}"

                chunks_count = upsert_document_with_chunks(
                    doc_id=doc_id,
                    title=title,
                    meeting_date=meeting_date,
                    url=minutes_url,
                    lang=lang,
                    content=text,
                    year=year,
                    resource="minutes",
                    published_date=minutes_pub,
                )
                total_chunks += chunks_count
                minutes_docs += 1
            except Exception as e:
                print(f"Failed to ingest minutes for {doc_id} from {minutes_url}: {e}")

        # 記者会見を登録する場合（別 doc_id で登録）
        if resource in ("press", "both") and press_url:
            try:
                pdf_resp = session.get(press_url)
                pdf_resp.raise_for_status()
                text = pdf_to_text(pdf_resp.content)

                press_doc_id = f"{doc_id}_press"
                title = f"BOJ MPM PressRelease {doc_id}"

                chunks_count = upsert_document_with_chunks(
                    doc_id=press_doc_id,
                    title=title,
                    meeting_date=meeting_date,
                    url=press_url,
                    lang=lang,
                    content=text,
                    year=year,
                    resource="press",
                    published_date=press_pub,
                )
                total_chunks += chunks_count
                press_docs += 1
            except Exception as e:
                print(f"Failed to ingest press for {doc_id} from {press_url}: {e}")

        # press_url があるが単に通知したい場合（resource==minutes で検出時のみログ）
        if resource == "minutes" and press_url:
            try:
                head = session.head(press_url, allow_redirects=True)
                if head.status_code >= 400:
                    print(f"Press URL not reachable for {doc_id}: {press_url} (status {head.status_code})")
                else:
                    print(f"Found press PDF for {doc_id}: {press_url}")
            except Exception as e:
                print(f"Failed to check press URL for {doc_id}: {press_url} -> {e}")

    return json.dumps(
        {
            "type": "text",
            "text": (
                f"Ingested {len(links)} rows for year {year}: "
                f"minutes_docs={minutes_docs}, press_docs={press_docs}, total_chunks={total_chunks}"
            ),
        }
    )


@mcp.tool()
async def add_manual_document(
    doc_id: str,
    title: str,
    meeting_date: str,
    url: str,
    lang: str,
    content: str,
) -> str:
    """
    任意の議事要旨テキストを指定してベクトル化し、SQLiteに登録します。
    BOJ以外のテキストにも利用できます。
    """
    chunks_count = upsert_document_with_chunks(
        doc_id=doc_id,
        title=title,
        meeting_date=meeting_date,
        url=url,
        lang=lang,
        content=content,
    )

    return json.dumps(
        {
            "type": "text",
            "text": f"Document {doc_id} indexed with {chunks_count} chunks.",
        }
    )


@mcp.tool()
async def search_boj_minutes(query: str, top_k: int = 5) -> str:
    """
    日本銀行の MPM Minutes コーパスに対してベクトル検索を行い、
    関連度の高いチャンクを返します。
    """
    results = search_chunks(query, top_k=top_k)

    payload: List[dict] = []
    for score, item in results:
        payload.append(
            {
                "score": score,
                **item,
            }
        )

    # text フィールドには、さらにJSON文字列として結果一覧を埋め込む
    return json.dumps(
        {
            "type": "text",
            "text": json.dumps(payload, ensure_ascii=False, indent=2),
        }
    )


if __name__ == "__main__":
    # stdio MCP サーバとして起動
    mcp.run(transport="stdio")
