import datetime
import os
import psycopg2
import asyncpg
from typing import Any, Dict
import logging
from dotenv import load_dotenv

from src.mcp_server.secrets import get_secret_name, fetch_secret_from_aws

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_secrets():

    # プロジェクトルート（open_deep_research）直下の.envを必ず参照
    dotenv_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')), '.env')
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
    else:
        logger.warning("Warning: .env file not found at %s", dotenv_path)

    if os.getenv("ENVIRONMENT", "develop") == "develop":
        logger.debug("Running in develop environment, skipping secret loading.")
        return

    secret_name = get_secret_name("SECRETS_PGVECTOR")
    secret_data = fetch_secret_from_aws(secret_name)
    logger.debug("Fetched  secret data from AWS Secrets Manager. secrets_data keys: %s",
                 list(secret_data.keys()))
    os.environ["POSTGRES_HOST"] = secret_data.get("POSTGRES_HOST", "")
    os.environ["POSTGRES_PORT"] = secret_data.get("POSTGRES_PORT", "")
    os.environ["POSTGRES_DB"] = secret_data.get("POSTGRES_DB", "")
    os.environ["POSTGRES_USER"] = secret_data.get("POSTGRES_USER", "")
    os.environ["POSTGRES_PASSWORD"] = secret_data.get("POSTGRES_PASSWORD", "")


load_secrets()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "")
POSTGRES_USER = os.getenv("POSTGRES_USER", "")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")


def get_connection_sync():
    """データベース接続を取得します (同期)"""
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    return conn


async def get_connection():
    """データベース接続を取得します"""
    conn = await asyncpg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    return conn


# テーブルとインデックスの作成
# テーブル一覧
# - web_search_result: 検索結果の保存
# - mra_reports: MRAレポートの保存
# - indicator_search_result: 指標検索結果の保存
# - search_keyword: 検索キーワードの保存
# - search_keyword_relation_: 検索キーワードの保存
# - search_keyword_relation_country: 検索キーワードと国の関係を保存
# - search_keyword_relation_comodity: 検索キーワードと商品との関係を保存
# - search_keyword_relation_sector: 検索キーワードと国の生産/消費関係を保存
def init_database():
    """データベースの初期化と必要なテーブル・インデックスの作成を行います"""
    with get_connection_sync() as conn:
        with conn.cursor() as cur:
            # -------------------------
            # web_search_resultテーブルの作成
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS web_search_result (
                    id SERIAL PRIMARY KEY,
                    query TEXT NOT NULL,
                    source_url TEXT,
                    title TEXT,
                    content TEXT,
                    summary TEXT,
                    content_type TEXT,
                    reliability_score FLOAT,
                    published_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # web_search_resultテーブルのトリガー関数とトリガーの作成：updated_atを自動更新
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION update_web_search_result_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS update_web_search_result_updated_at ON web_search_result;
                CREATE TRIGGER update_web_search_result_updated_at
                BEFORE UPDATE ON web_search_result
                FOR EACH ROW
                EXECUTE FUNCTION update_web_search_result_updated_at();
                """
            )

            # web_search_resultテーブルのインデックス
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_search_results_on_query ON web_search_result(query);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_search_results_on_source_url ON web_search_result(source_url);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_search_results_on_content_type ON web_search_result(content_type);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_search_results_on_created_at ON web_search_result(created_at);"
            )

            # source_urlにUNIQUE制約を追加（既存なら何もしない）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'unique_source_url'
                        AND conrelid = 'web_search_result'::regclass
                    ) THEN
                        ALTER TABLE web_search_result ADD CONSTRAINT unique_source_url UNIQUE (source_url);
                    END IF;
                END $$;
                """
            )

            # -------------------------
            # mra_reportsテーブルの作成
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mra_reports (
                    id SERIAL PRIMARY KEY,
                    date DATE,
                    number TEXT,
                    source TEXT,
                    category TEXT,
                    sector TEXT,
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # mra_reportsテーブルのトリガー関数とトリガーの作成：updated_atを自動更新
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION update_mra_reports_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS update_mra_reports_updated_at ON mra_reports;
                CREATE TRIGGER update_mra_reports_updated_at
                BEFORE UPDATE ON mra_reports
                FOR EACH ROW
                EXECUTE FUNCTION update_mra_reports_updated_at();
                """
            )

            # mra_reportsテーブルのインデックス
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_mra_reports_on_number ON mra_reports(number);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_mra_reports_on_category ON mra_reports(category);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_mra_reports_on_sector ON mra_reports(sector);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_mra_reports_on_date ON mra_reports(date);"
            )

            # source, sectorにUNIQUE制約を追加（既存なら何もしない）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'unique_source_sector'
                        AND conrelid = 'mra_reports'::regclass
                    ) THEN
                        ALTER TABLE mra_reports ADD CONSTRAINT unique_source_sector UNIQUE (source, sector);
                    END IF;
                END $$;
                """
            )

            # -------------------------
            # indicator_search_resultテーブルの作成
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS indicator_search_result (
                    id SERIAL PRIMARY KEY,
                    indicator_name TEXT,
                    country TEXT,
                    indicator_category TEXT,
                    frequency TEXT,
                    result TEXT,
                    previous TEXT,
                    forecast TEXT,
                    importance TEXT,
                    published_at DATE DEFAULT '1970-01-01',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # トリガー関数とトリガーの作成：updated_atを自動更新
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION update_indicator_search_result_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS update_indicator_search_result_updated_at ON indicator_search_result;
                CREATE TRIGGER update_indicator_search_result_updated_at
                BEFORE UPDATE ON indicator_search_result
                FOR EACH ROW
                EXECUTE FUNCTION update_indicator_search_result_updated_at();
                """
            )

            # indicator_search_resultテーブルのインデックス
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_indicator_search_result_on_indicator_name \
                ON indicator_search_result(indicator_name);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_indicator_search_result_on_country \
                ON indicator_search_result(country);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_indicator_search_result_on_indicator_category \
                ON indicator_search_result(indicator_category);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_indicator_search_result_on_frequency \
                 ON indicator_search_result(frequency);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_indicator_search_result_on_published_at \
                ON indicator_search_result(published_at);"
            )

            # published_at, country, indicator_category, frequency の組み合わせでUNIQUE制約を追加（既存なら何もしない）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'unique_published_country_category_freq'
                        AND conrelid = 'indicator_search_result'::regclass
                    ) THEN
                        ALTER TABLE indicator_search_result
                        ADD CONSTRAINT unique_published_country_category_freq
                        UNIQUE (published_at, country, indicator_category, frequency, indicator_name);
                    END IF;
                END $$;
                """
            )

            # -------------------------
            # search_keywordsテーブルの作成
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS search_keywords (
                    id SERIAL PRIMARY KEY,
                    keyword TEXT,
                    keyword_type TEXT,
                    sector TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
            )
            # search_keywordsのトリガー関数とトリガーの作成：updated_atを自動更新
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION update_search_keywords_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS update_search_keywords_updated_at ON search_keywords;
                CREATE TRIGGER update_search_keywords_updated_at
                BEFORE UPDATE ON search_keywords
                FOR EACH ROW
                EXECUTE FUNCTION update_search_keywords_updated_at();
                """
            )

            # search_keywordsテーブルのインデックス
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_search_keywords_on_keyword ON search_keywords(keyword);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_search_keywords_on_keyword_type ON search_keywords(keyword_type);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_search_keywords_on_sector ON search_keywords(sector);"
            )

            # (keyword, keyword_type, sector)にUNIQUE制約を追加（既存なら何もしない）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'unique_keyword_type_sector'
                        AND conrelid = 'search_keywords'::regclass
                    ) THEN
                        ALTER TABLE search_keywords ADD CONSTRAINT unique_keyword_type_sector
                        UNIQUE (keyword, keyword_type, sector);
                    END IF;
                END $$;
                """
            )

            # -------------------------
            # commodity_country_relationsテーブルの作成
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS commodity_country_relations (
                    id SERIAL PRIMARY KEY,
                    commodity_keyword TEXT,
                    related_country_keyword TEXT,
                    relation_type TEXT,
                    sector TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # commodity_country_relationsのトリガー関数とトリガーの作成：updated_atを自動更新
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION update_commodity_country_relations_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS update_commodity_country_relations_updated_at ON commodity_country_relations;
                CREATE TRIGGER update_commodity_country_relations_updated_at
                BEFORE UPDATE ON commodity_country_relations
                FOR EACH ROW
                EXECUTE FUNCTION update_commodity_country_relations_updated_at();
                """
            )

            # commodity_country_relationsテーブルのインデックス
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_country_relations_on_commodity_keyword \
                ON commodity_country_relations(commodity_keyword);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_country_relations_on_country_keyword \
                ON commodity_country_relations(related_country_keyword);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_country_relations_on_relation_type \
                ON commodity_country_relations(relation_type);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_country_relations_on_sector \
                ON commodity_country_relations(sector);"
            )

            # commodity_keyword, related_country_keyword, relation_type, sector の組み合わせでUNIQUE制約を追加（既存なら何もしない）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'unique_commodity_country_relation_sector'
                        AND conrelid = 'commodity_country_relations'::regclass
                    ) THEN
                        ALTER TABLE commodity_country_relations
                        ADD CONSTRAINT unique_commodity_country_relation_sector
                        UNIQUE (commodity_keyword, related_country_keyword, relation_type, sector);
                    END IF;
                END $$;
                """
            )

            # -------------------------
            # commodity_commodity_relationsテーブルの作成
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS commodity_commodity_relations (
                    id SERIAL PRIMARY KEY,
                    commodity_keyword TEXT,
                    related_commodity_keyword TEXT,
                    relation_type TEXT,
                    sector TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # commodity_commodity_relationsのトリガー関数とトリガーの作成：updated_atを自動更新
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION update_commodity_commodity_relations_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS update_commodity_commodity_relations_updated_at ON commodity_commodity_relations;
                CREATE TRIGGER update_commodity_commodity_relations_updated_at
                BEFORE UPDATE ON commodity_commodity_relations
                FOR EACH ROW
                EXECUTE FUNCTION update_commodity_commodity_relations_updated_at();
                """
            )

            # commodity_commodity_relationsテーブルのインデックス
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_commodity_relations_on_commodity_keyword \
                ON commodity_commodity_relations(commodity_keyword);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_commodity_relations_on_related_commodity_keyword \
                ON commodity_commodity_relations(related_commodity_keyword);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_commodity_relations_on_relation_type \
                ON commodity_commodity_relations(relation_type);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_commodity_relations_on_sector \
                ON commodity_commodity_relations(sector);"
            )

            # commodity_keyword, related_commodity_keyword, relation_type, sector の組み合わせでUNIQUE制約を追加（既存なら何もしない）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'unique_commodity_commodity_relation_sector'
                        AND conrelid = 'commodity_commodity_relations'::regclass
                    ) THEN
                        ALTER TABLE commodity_commodity_relations
                        ADD CONSTRAINT unique_commodity_commodity_relation_sector
                        UNIQUE (commodity_keyword, related_commodity_keyword, relation_type, sector);
                    END IF;
                END $$;
                """
            )

            # -------------------------
            # commodity_production_consumptionsテーブルの作成
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS commodity_production_consumptions (
                    id SERIAL PRIMARY KEY,
                    commodity_keyword TEXT,
                    related_country_keyword TEXT,
                    production TEXT,
                    consumption TEXT,
                    sector TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # commodity_production_consumptionsのトリガー関数とトリガーの作成：updated_atを自動更新
            cur.execute(
                """
                CREATE OR REPLACE FUNCTION update_commodity_production_consumptions_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS update_commodity_production_consumptions_updated_at ON
                commodity_production_consumptions;
                CREATE TRIGGER update_commodity_production_consumptions_updated_at
                BEFORE UPDATE ON commodity_production_consumptions
                FOR EACH ROW
                EXECUTE FUNCTION update_commodity_production_consumptions_updated_at();
                """
            )

            # commodity_production_consumptionsテーブルのインデックス
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_production_consumptions_on_commodity_keyword \
                ON commodity_production_consumptions(commodity_keyword);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_production_consumptions_on_related_country_keyword \
                ON commodity_production_consumptions(related_country_keyword);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_production_consumptions_on_production \
                ON commodity_production_consumptions(production);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_production_consumptions_on_consumption \
                ON commodity_production_consumptions(consumption);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS index_commodity_production_consumptions_on_sector \
                ON commodity_production_consumptions(sector);"
            )

            # commodity_keyword, related_country_keyword, sector の組み合わせでUNIQUE制約を追加（既存なら何もしない）
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'unique_commodity_production_consumptions'
                        AND conrelid = 'commodity_production_consumptions'::regclass
                    ) THEN
                        ALTER TABLE commodity_production_consumptions
                        ADD CONSTRAINT unique_commodity_production_consumptions
                        UNIQUE(commodity_keyword, related_country_keyword, sector);
                    END IF;
                END $$;
                """
            )

            conn.commit()


async def save_web_search_result(
    query: str,
    source_url: str,
    title: str,
    content: str,
    content_type: str = "",
    summary: str = "",
    reliability_score: float = 0.5,
    published_at: str = "1970-01-01 00:00:00",
) -> Dict[str, Any]:
    """
    Webで検索した結果をデータベースに保存します。
    source_urlにUNIQUE制約があるので注意

    引数:
        query: 検索クエリ
        source_url: 情報ソースのURL
        title: コンテンツのタイトル
        content: 抽出したコンテンツ（本文）
        content_type: 情報タイプ（例: "ニュース", "技術文書"）
        summary: 要約文（エージェントが生成）
        reliability_score: 信頼性スコア (0.0-1.0)
        published_at: レポート公開日（YYYY-MM-DD HH:MM:SS形式）

    返値:
        {"success": bool, "message": str, "result_id": Optional[int]}
    """
    try:
        logger.debug("Saving web search result: %s, %s, %s, %s, %s, %s",
                     source_url, title, content_type, reliability_score, published_at)
        now = datetime.datetime.now()
        if isinstance(published_at, str):
            published_at = datetime.datetime.strptime(published_at, "%Y-%m-%d %H:%M:%S")
        conn = await get_connection()
        try:
            result = await conn.fetchrow(
                """
                INSERT INTO web_search_result
                (query, source_url, title, content, summary, content_type, reliability_score, created_at, published_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, CURRENT_TIMESTAMP)
                ON CONFLICT (source_url)
                DO UPDATE SET
                    query = EXCLUDED.query,
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    summary = EXCLUDED.summary,
                    content_type = EXCLUDED.content_type,
                    reliability_score = EXCLUDED.reliability_score,
                    published_at = EXCLUDED.published_at,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                query, source_url, title, content, summary, content_type, reliability_score, now, published_at
            )
            if result:
                logger.debug("Web search result saved with ID: %s", result['id'])
                message = f"検索結果の保存または更新に成功しました (ID: {result['id']})"
                return {"success": True, "message": message, "result_id": result["id"]}
            else:
                logger.debug("Failed to save web search result: ID not returned")
                return {"success": False, "message": "保存に失敗しました（ID取得不可）", "result_id": None}
        finally:
            await conn.close()
    except Exception as e:
        logger.error("query: %s, source_url: %s, title: %s, content: %s, "
                     "content_type: %s, summary: %s, reliability_score: %s",
                     query, source_url, title, content, content_type, summary, reliability_score)
        return {"success": False, "message": f"保存エラー: {e}", "result_id": None}


async def save_mra_reports(
    date: str,
    number: str,
    source: str,
    category: str,
    sector: str,
    content: str,
) -> Dict[str, Any]:
    """
    MRAレポートから特定の情報を抽出した結果をデータベースに保存します。
    source, sectorにUNIQUE制約があるので注意

    引数:
        date : レポート公開日
        number : レポート番号 (例: 第2914号)
        source : 情報ソースファイル名
        category : レポートカテゴリ (例: "昨日の市場動向総括", "本日の見通し", "昨日のセクター別動向と本日の見通し", "マクロ見通しのリスクシナリオ")
        sector : セクター (例: "原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属")
        content : 抽出したコンテンツ（本文）
    返値:
        {"success": bool, "message": str, "result_id": Optional[int]}
    """
    try:
        logger.debug("Saving MRA report: %s, %s, %s, %s, %s, "
                     "content length: %d", date, number, source, category, sector, len(content))
        now = datetime.datetime.now()
        if isinstance(date, str):
            date = datetime.datetime.strptime(date, "%Y-%m-%d")

        conn = await get_connection()
        try:
            result = await conn.fetchrow(
                """
                INSERT INTO mra_reports
                (date, number, source, category, sector, content, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP)
                ON CONFLICT (source, sector)
                DO UPDATE SET
                    date = EXCLUDED.date,
                    number = EXCLUDED.number,
                    category = EXCLUDED.category,
                    sector = EXCLUDED.sector,
                    content = EXCLUDED.content,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                date, number, source, category, sector, content, now
            )
            if result:
                logger.debug("MRA report saved with ID: %s", result['id'])
                message = f"検索結果の保存または更新に成功しました (ID: {result['id']}、ソース: {source}, セクター: {sector})"
                return {"success": True, "message": message, "result_id": result["id"]}
            else:
                logger.debug("Failed to save MRA report: ID not returned")
                return {"success": False, "message": f"保存に失敗しました（ID取得不可）、ソース: {source}, セクター: {sector}", "result_id": None}
        finally:
            await conn.close()
    except Exception as e:
        logger.error("date: %s, number: %s, source: %s, "
                     "category: %s, sector: %s, content: %s",
                     date, number, source, category, sector, content)
        return {"success": False, "message": f"保存エラー: {e}、ソース: {source}, セクター: {sector}", "result_id": None}


async def save_indicator_search_result(
    indicator_name: str,
    country: str,
    indicator_category: str,
    frequency: str,
    result: str,
    previous: str = "",
    forecast: str = "",
    importance: str = "medium",
    published_at: str = "1970-01-01",
) -> Dict[str, Any]:
    """
    指標の検索結果をデータベースに保存します。
    published_at, country, indicator_category, frequency の組み合わせでUNIQUE制約があるので注意

    引数:
        indicator_name: 指標名
        country: 国名
        indicator_category: 指標カテゴリ（例: "経済", "金融", "商品価格"）
        frequency: 更新頻度
        result: 結果
        previous: 前回値
        forecast: 予測値
        importance: 重要度 "high", "medium", "low"
        published_at: 公開日（YYYY-MM-DD HH:MM:SS形式）
    返値:
        {"success": bool, "message": str, "result_id": Optional[int]}
    """
    try:
        logger.debug(
            "Saving indicator search result: %s, %s, %s, %s, "
            "result length: %d, previous: %s, forecast: %s, "
            "importance: %s, published_at: %s",
            indicator_name, country, indicator_category, frequency,
            len(result), previous, forecast, importance, published_at
        )
        now = datetime.datetime.now()
        if isinstance(published_at, str):
            try:

                published_at = datetime.datetime.strptime(published_at, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # 時刻なしの場合
                published_at = datetime.datetime.strptime(published_at, "%Y-%m-%d")
        elif isinstance(published_at, datetime.date):
            published_at = datetime.datetime.combine(published_at, datetime.time.min)

        conn = await get_connection()
        try:
            result = await conn.fetchrow(
                """
                INSERT INTO indicator_search_result
                (indicator_name, country, indicator_category, frequency, result, previous, forecast, importance, published_at, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, CURRENT_TIMESTAMP)
                ON CONFLICT (published_at, country, indicator_category, frequency, indicator_name)
                DO UPDATE SET
                    indicator_name = EXCLUDED.indicator_name,
                    result = EXCLUDED.result,
                    previous = EXCLUDED.previous,
                    forecast = EXCLUDED.forecast,
                    importance = EXCLUDED.importance,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                indicator_name, country, indicator_category, frequency, result,
                previous, forecast, importance, published_at, now
            )
            if result:
                logger.debug("Indicator search result saved with ID: %s", result['id'])
                message = f"検索結果の保存または更新に成功しました (ID: {result['id']})"
                return {"success": True, "message": message, "result_id": result["id"]}
            else:
                logger.debug("Failed to save indicator search result: ID not returned")
                return {"success": False, "message": "保存に失敗しました（ID取得不可）", "result_id": None}
        finally:
            await conn.close()
    except Exception as e:
        logger.error(
            "indicator_name: %s, country: %s, indicator_category: %s, "
            "frequency: %s, result: %s, previous: %s, forecast: %s, "
            "importance: %s, published_at: %s",
            indicator_name, country, indicator_category, frequency, result,
            previous, forecast, importance, published_at
        )
        return {"success": False, "message": f"保存エラー: {e}", "result_id": None}


async def save_search_keywords(
    keyword: str,
    keyword_type: str = "commodity",
    sector: str = "",
) -> Dict[str, Any]:
    """
    セクターに関連する商品もしくは、セクターに関連する国の情報を検索するための情報で
    セクターに対するレポート作成する際にセクターでフィルタリングして検索キーワードを抽出し検索を行う
    (keyword, keyword_type, sector)にUNIQUE制約があるので注意

    引数:
        keyword: 検索キーワード
        keyword_type: キーワードの種類（例: "commodity", "country"）
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）を指定する
    返値:
        {"success": bool, "message": str, "result_id": Optional[int]}
    """
    try:
        logger.debug("Saving search keywords: %s, %s, %s", keyword, keyword_type, sector)
        now = datetime.datetime.now()

        conn = await get_connection()
        try:
            result = await conn.fetchrow(
                """
                INSERT INTO search_keywords
                (keyword, keyword_type, sector, created_at, updated_at)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (keyword, keyword_type, sector)
                DO UPDATE SET
                    keyword = EXCLUDED.keyword,
                    keyword_type = EXCLUDED.keyword_type,
                    sector = EXCLUDED.sector,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                keyword, keyword_type, sector, now
            )
            if result:
                logger.debug("Search keyword saved with ID: %s", result['id'])
                message = f"検索結果の保存または更新に成功しました (ID: {result['id']})"
                return {"success": True, "message": message, "result_id": result["id"]}
            else:
                logger.debug("Failed to save search keyword: ID not returned")
                return {"success": False, "message": "保存に失敗しました（ID取得不可）", "result_id": None}
        finally:
            await conn.close()
    except Exception as e:
        logger.error("keyword: %s, keyword_type: %s, sector: %s, created_at: %s",
                     keyword, keyword_type, sector, now)
        return {"success": False, "message": f"保存エラー: {e}", "result_id": None}


async def save_commodity_country_relations(
    keyword: str,
    related_country_keyword: str,
    relation_type: str = "金融市場を通じて影響",
    sector: str = "",
) -> Dict[str, Any]:
    """
    対象商品と国にどのような関係があるか、どんなニュースに注目するのかの指針を示すための情報で、
    保存するニュースの重要度に影響を与える
    commodity_keyword, related_country_keyword, relation_type, sector の組み合わせでUNIQUE制約があるので注意

    引数:
        keyword: 検索キーワード
        related_country_keyword: 関係国キーワード
        relation_type: 関係の種類 "金融市場を通じて影響", "政策動向が影響", "地政学的リスク", "異常気象", "原発稼働状況", "主要加工地"
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）を指定する
    返値:
        {"success": bool, "message": str, "result_id": Optional[int]}
    """
    try:
        logger.debug("Saving commodity_country_relations: %s, %s, %s, %s",
                     keyword, related_country_keyword, relation_type, sector)
        now = datetime.datetime.now()
        conn = await get_connection()
        try:
            result = await conn.fetchrow(
                """
                INSERT INTO commodity_country_relations
                (commodity_keyword, related_country_keyword, relation_type, sector, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (commodity_keyword, related_country_keyword, relation_type, sector)
                DO UPDATE SET
                    commodity_keyword = EXCLUDED.commodity_keyword,
                    related_country_keyword = EXCLUDED.related_country_keyword,
                    relation_type = EXCLUDED.relation_type,
                    sector = EXCLUDED.sector,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                keyword, related_country_keyword, relation_type, sector, now
            )
            if result:
                message = f"検索結果の保存または更新に成功しました (ID: {result['id']})"
                return {"success": True, "message": message, "result_id": result["id"]}
            else:
                return {"success": False, "message": "保存に失敗しました（ID取得不可）", "result_id": None}
        finally:
            await conn.close()
    except Exception as e:
        logger.error(
            "keyword: %s, related_country_keyword: %s, "
            "relation_type: %s, sector: %s, created_at: %s",
            keyword, related_country_keyword, relation_type, sector, now
        )
        return {"success": False, "message": f"保存エラー: {e}", "result_id": None}


async def save_commodity_commodity_relations(
    keyword: str,
    related_commodity_keyword: str,
    relation_type: str = "影響を与える",
    sector: str = "",
) -> Dict[str, Any]:
    """
    対象商品とそのほかの商品にどのような関係があるか、どんなニュースに注目するのかの指針を示すための情報で、
    保存するニュースの重要度に影響を与える
    commodity_keyword, related_commodity_keyword, relation_type, sector の組み合わせでUNIQUE制約があるので注意

    引数:
        keyword: 検索キーワード
        related_commodity_keyword: 関係商品キーワード
        relation_type: 関係の種類 1:とても強い影響を与える, 2:強い影響を与える, 3:影響を与える
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）を指定する
    返値:
        {"success": bool, "message": str, "result_id": Optional[int]}
    """
    try:
        logger.debug(
            "Saving commodity_commodity_relations: %s, %s, %s, %s",
            keyword, related_commodity_keyword, relation_type, sector
        )
        now = datetime.datetime.now()
        conn = await get_connection()
        try:
            result = await conn.fetchrow(
                """
                INSERT INTO commodity_commodity_relations
                (commodity_keyword, related_commodity_keyword, relation_type, sector, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (commodity_keyword, related_commodity_keyword, relation_type, sector)
                DO UPDATE SET
                    commodity_keyword = EXCLUDED.commodity_keyword,
                    related_commodity_keyword = EXCLUDED.related_commodity_keyword,
                    relation_type = EXCLUDED.relation_type,
                    sector = EXCLUDED.sector,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                keyword, related_commodity_keyword, relation_type, sector, now
            )
            if result:
                message = f"検索結果の保存または更新に成功しました (ID: {result['id']})"
                return {"success": True, "message": message, "result_id": result["id"]}
            else:
                return {"success": False, "message": "保存に失敗しました（ID取得不可）", "result_id": None}
        finally:
            await conn.close()
    except Exception as e:
        logger.error(
            "keyword: %s, related_commodity_keyword: %s, "
            "relation_type: %s, sector: %s, created_at: %s",
            keyword, related_commodity_keyword, relation_type, sector, now
        )
        return {"success": False, "message": f"保存エラー: {e}", "result_id": None}


async def save_commodity_production_consumptions(
    keyword: str,
    related_country_keyword: str,
    sector: str = "",
    production: str = "",
    consumption: str = "",
) -> Dict[str, Any]:
    """
    対象商品とそのほかの商品にどのような関係があるか、どんなニュースに注目するのかの指針を示すための情報で、
    保存するニュースの重要度に影響を与える
    commodity_keyword, related_country_keyword, sector の組み合わせでUNIQUE制約があるので注意

    引数:
        keyword: 検索キーワード
        related_country_keyword: 関係国キーワード
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）を指定する
        production: 生産量 1:とても多い 2:多い 3: 少ない 4:ない
        consumption: 消費量 1:とても多い 2:多い 3: 少ない 4:ない
    返値:
        {"success": bool, "message": str, "result_id": Optional[int]}
    """
    try:
        logger.debug(
            "Saving commodity production/consumption: %s, %s, %s, %s, %s",
            keyword, related_country_keyword, sector, production, consumption
        )
        now = datetime.datetime.now()
        conn = await get_connection()
        try:
            result = await conn.fetchrow(
                """
                INSERT INTO commodity_production_consumptions
                (commodity_keyword, related_country_keyword, sector, production, consumption, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                ON CONFLICT (commodity_keyword, related_country_keyword, sector)
                DO UPDATE SET
                    commodity_keyword = EXCLUDED.commodity_keyword,
                    related_country_keyword = EXCLUDED.related_country_keyword,
                    sector = EXCLUDED.sector,
                    production = EXCLUDED.production,
                    consumption = EXCLUDED.consumption,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                keyword, related_country_keyword, sector, production, consumption, now
            )
            if result:
                logger.debug("Commodity production/consumption saved: %s", result['id'])
                message = f"検索結果の保存または更新に成功しました (ID: {result['id']})"
                return {"success": True, "message": message, "result_id": result["id"]}
            else:
                logger.debug("Failed to save commodity production/consumption: ID not returned")
                return {"success": False, "message": "保存に失敗しました（ID取得不可）", "result_id": None}
        finally:
            await conn.close()
    except Exception as e:
        logger.error(
            "keyword: %s, related_country_keyword: %s, "
            "sector: %s, created_at: %s",
            keyword, related_country_keyword, sector, now
        )
        return {"success": False, "message": f"保存エラー: {e}", "result_id": None}


async def get_web_recent_results(
    days: int = 7, limit: int = 50, content_type: str = ""
) -> Dict[str, Any]:
    """
    指定された日数以内の最近のweb検索結果を取得します。

    引数:
        days: 何日前までの検索結果を取得するか (デフォルト: 7)
        limit: 返す結果の最大数 (デフォルト: 50)
        content_type: 特定のコンテンツタイプでフィルタリング (オプション)

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug("Getting recent web results: days=%s, limit=%s, content_type=%s", days, limit, content_type)
        # days日前の日付を計算
        date_threshold = datetime.datetime.now() - datetime.timedelta(days=days)

        # SQLクエリ構築（asyncpg用に$1, $2...でバインド）
        sql = """
        SELECT id, query, source_url, title, summary, content_type, reliability_score, published_at
        FROM web_search_result
        WHERE published_at >= $1
        """
        params = [date_threshold]

        if content_type:
            sql += " AND content_type = $2"
            params.append(content_type)
            sql += f" ORDER BY reliability_score DESC, published_at DESC LIMIT ${len(params)+1}"
            params.append(limit)
        else:
            sql += " ORDER BY reliability_score DESC, published_at DESC LIMIT $2"
            params.append(limit)

        conn = await get_connection()
        try:
            rows = await conn.fetch(sql, *params)
            if not rows:
                logger.debug("No recent web results found.")
                return {
                    "success": True,
                    "message": "指定された期間内の検索結果は見つかりませんでした。",
                    "results": [],
                }
            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の検索結果が見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error getting recent web results: %s", e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_web_content_by_id(result_id: int) -> Dict[str, Any]:
    """
    特定IDのweb検索結果の詳細コンテンツを取得します。

    引数:
        result_id: 検索結果のID

    返値:
        {"success": bool, "message": str, "result": Optional[Dict]}
    """
    try:
        logger.debug("Getting web content by ID: %s", result_id)
        conn = await get_connection()

        try:
            row = await conn.fetchrow(
                """
                SELECT id, query, source_url, title, content, summary, content_type,
                    reliability_score, created_at
                FROM web_search_result
                WHERE id = $1
                """,
                result_id
            )

            if not row:
                logger.debug(f"No web search result found for ID: {result_id}")
                return {
                    "success": False,
                    "message": f"エラー: ID {result_id} の検索結果が見つかりません。",
                    "result": None,
                }
            # asyncpgのRowはdictに変換できる
            result = dict(row)
            # datetime型をstringに変換
            if isinstance(result.get("created_at"), datetime.datetime):
                result["created_at"] = result["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            logger.debug("Web content retrieved for ID: %s", result_id)
            return {
                "success": True,
                "message": f"ID {result_id} の検索結果を取得しました。",
                "result": result,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error getting web content by ID %s: %s", result_id, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_web_content_types() -> Dict[str, Any]:
    """
    データベースに保存されている全てのコンテンツタイプの一覧と各タイプの件数を返します。

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        conn = await get_connection()

        try:
            rows = await conn.fetch(
                """
                SELECT content_type, COUNT(*) as count
                FROM web_search_result
                GROUP BY content_type
                ORDER BY count DESC
                """
            )

            if not rows:
                return {
                    "success": True,
                    "message": "保存されている検索結果がありません。",
                    "results": [],
                }
            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}種類のコンテンツタイプが見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_report_recent_results(
    days: int = 1, limit: int = 10, category: str = "", sector: str = ""
) -> Dict[str, Any]:
    """
    指定された日数以内の最近のweb検索結果を取得します。

    引数:
        days: 何日前までの検索結果を取得するか (デフォルト: 1)
        limit: 返す結果の最大数 (デフォルト: 10)
        category: 特定のカテゴリでフィルタリング (オプション)
        sector: 特定のセクターでフィルタリング (オプション)

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug("Getting recent MRA reports: days=%s, limit=%s, category=%s, sector=%s", days, limit, category, sector)
        date_threshold = datetime.datetime.now() - datetime.timedelta(days=days)

        sql = """
        SELECT id, date, number, source, content, category, sector, created_at
        FROM mra_reports
        WHERE created_at >= $1
        """
        params = [date_threshold]
        param_idx = 2
        if category:
            sql += f" AND category = ${param_idx}"
            params.append(category)
            param_idx += 1
        if sector:
            sql += f" AND sector = ${param_idx}"
            params.append(sector)
            param_idx += 1
        sql += f" ORDER BY date DESC, created_at DESC LIMIT ${param_idx}"
        params.append(limit)

        conn = await get_connection()
        try:
            rows = await conn.fetch(sql, *params)
            if not rows:
                logger.debug("No recent MRA reports found.")
                return {
                    "success": True,
                    "message": "指定された期間内の検索結果は見つかりませんでした。",
                    "results": [],
                }
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の検索結果が見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error getting recent MRA reports: %s", e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_report_by_date(
    publish_date_from: str,
    publish_date_to: str,
    category: str = "",
    sector: str = "",
    limit: int = None
) -> Dict[str, Any]:
    """
    指定した期間（from/to）でMRAレポートの詳細コンテンツを取得します。

    引数:
        publish_date_from: レポート公開開始日（YYYY-MM-DD形式）
        publish_date_to: レポート公開終了日（YYYY-MM-DD形式）
        category: 特定のカテゴリでフィルタリング (オプション)
        sector: 特定のセクターでフィルタリング (オプション)
    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug("Getting MRA report by date range: %s to %s, category=%s, sector=%s, limit=%s", publish_date_from, publish_date_to, category, sector, limit)

        if isinstance(publish_date_from, str):
            publish_date_from = datetime.datetime.strptime(publish_date_from, "%Y-%m-%d").date()
        if isinstance(publish_date_to, str):
            publish_date_to = datetime.datetime.strptime(publish_date_to, "%Y-%m-%d").date()

        sql = """
        SELECT id, date, number, source, content, category, sector, created_at
        FROM mra_reports
        WHERE date BETWEEN $1 AND $2
        """
        params = [publish_date_from, publish_date_to]
        param_idx = 3
        if category:
            sql += f" AND category = ${param_idx}"
            params.append(category)
            param_idx += 1
        if sector:
            sql += f" AND sector = ${param_idx}"
            params.append(sector)
            param_idx += 1
        sql += " ORDER BY date DESC, created_at DESC"
        if limit is not None:
            sql += f" LIMIT ${param_idx}"
            params.append(limit)

        logger.info("Executing SQL: %s with params: %s", sql, params)

        conn = await get_connection()
        try:
            rows = await conn.fetch(sql, *params)
            if not rows:
                logger.debug("No MRA report found for date range: %s to %s", publish_date_from, publish_date_to)
                return {
                    "success": True,
                    "message": "指定された期間のレポートは見つかりませんでした。",
                    "results": [],
                }
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件のレポートが見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error getting MRA report by date range %s to %s: %s", publish_date_from, publish_date_to, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_indicator_recent_results(
    days: int = 30, limit: int = 20, country: list[str] = None, indicator_category: str = "", frequency: str = ""
) -> Dict[str, Any]:
    """
    指定された日数以内の最近のweb検索結果を取得します。

    引数:
        days: 何日前までの検索結果を取得するか (デフォルト: 30)
        limit: 返す結果の最大数 (デフォルト: 20)
        country: 特定の国のリストでフィルタリング (オプション)
        indicator_category: 特定の指標カテゴリでフィルタリング (オプション)
        frequency: 特定の頻度でフィルタリング (オプション)

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug(
            "Getting recent indicator results: days=%s, limit=%s, "
            "country=%s, indicator_category=%s, frequency=%s",
            days, limit, country, indicator_category, frequency
        )
        date_threshold = datetime.datetime.now() - datetime.timedelta(days=days)

        sql = """
        SELECT id, indicator_name, country, indicator_category, frequency, result, previous, forecast, importance, published_at
        FROM indicator_search_result
        WHERE published_at >= $1
        """
        params = [date_threshold]
        param_idx = 2

        if country:
            placeholders = ", ".join([f"${i}" for i in range(param_idx, param_idx + len(country))])
            sql += f" AND country IN ({placeholders})"
            params.extend(country)
            param_idx += len(country)
        if indicator_category:
            sql += f" AND indicator_category = ${param_idx}"
            params.append(indicator_category)
            param_idx += 1
        if frequency:
            sql += f" AND frequency = ${param_idx}"
            params.append(frequency)
            param_idx += 1

        sql += f" ORDER BY importance DESC, published_at DESC LIMIT ${param_idx}"
        params.append(limit)

        conn = await get_connection()
        try:
            rows = await conn.fetch(sql, *params)
            if not rows:
                logger.debug("No recent indicator results found.")
                return {
                    "success": True,
                    "message": "指定された期間内の検索結果は見つかりませんでした。",
                    "results": [],
                }
            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                # date型をstringに変換
                if isinstance(row_dict.get("published_at"), (datetime.date, datetime.datetime)):
                    row_dict["published_at"] = row_dict["published_at"].strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の検索結果が見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error getting recent indicator results: %s", e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_indicator_column_info(column_name: str) -> Dict[str, Any]:
    """
    データベースに保存されている指定のカラムの指標の値の一覧と各国の件数を返します。

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug("Getting indicator column info for: %s", column_name)
        # SQLインジェクション防止: 許可カラム名のみ許可
        allowed_columns = {
            "indicator_name",
            "country",
            "indicator_category",
            "frequency",
            "result",
            "previous",
            "forecast",
            "importance",
            "published_at",
        }
        if column_name not in allowed_columns:
            logger.error("Invalid column name: %s", column_name)
            return {"success": False, "message": f"不正なカラム名です: {column_name}", "results": []}

        conn = await get_connection()
        try:
            query = f"""
                SELECT {column_name}, COUNT(*) as count
                FROM indicator_search_result
                GROUP BY {column_name}
                ORDER BY count DESC
            """
            rows = await conn.fetch(query)
            if not rows:
                logger.debug("No data found for column: %s", column_name)
                return {
                    "success": True,
                    "message": "保存されている検索結果がありません。",
                    "results": [],
                }

            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}種類の{column_name}が見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error getting indicator column info for %s: %s", column_name, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_schema() -> Dict[str, Any]:
    """
    PostgreSQLデータベースのスキーマ情報（テーブル名と各カラム）を返します。

    返値:
        {"success": bool, "message": str, "schema": str}
    """
    try:
        logger.info("get_schema called to retrieve database schema information.")
        schema_info = ""

        conn = await get_connection()

        try:

            rows = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )

            # テーブル名を取得
            if not rows:
                logger.debug("No tables found in the database.")
                return {
                    "success": True,
                    "message": "データベースにテーブルがありません。",
                    "schema": "",
                }
            schema_info += "データベーススキーマ情報:\n"
            for row in rows:
                table_name = row['table_name']
                schema_info += f"テーブル: {table_name}\n"
                # 各テーブルのカラム情報を取得
                columns = await conn.fetch(
                    """
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_name = $1
                    """,
                    table_name,
                )

                if not columns:
                    schema_info += "  - カラム情報がありません。\n"
                else:
                    schema_info += "  - カラム情報:\n"
                    # 各カラムの情報を追加
                    columns = [(col['column_name'], col['data_type']) for col in columns]
                    if not columns:
                        schema_info += "    - カラム情報がありません。\n"
                    else:
                        # カラム名とデータ型を表示
                        schema_info += "    - カラム名とデータ型:\n"
                        # 各カラムの情報を追加
                        for col in columns:
                            schema_info += f"      - {col[0]} ({col[1]})\n"
            schema_info += "\n"
            # スキーマ情報を返す
        finally:
            await conn.close()
        if not schema_info:
            logger.info("No schema information found in the database.")
            return {
                "success": True,
                "message": "データベースにスキーマ情報がありません。",
                "schema": "",
            }
        logger.debug("Schema information retrieved successfully.")
        return {
            "success": True,
            "message": "スキーマ情報を取得しました。",
            "schema": schema_info,
        }
    except Exception as e:
        logger.error("Error retrieving schema information: %s", e)
        return {"success": False, "message": f"スキーマ取得エラー: {e}", "schema": ""}


async def get_search_keywords_by_sector(sector: str) -> Dict[str, Any]:
    """
    指定されたセクターに関連する保存された検索キーワードを取得します。

    引数:
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.info("get_search_keywords_by_sector called with sector: %s", sector)

        conn = await get_connection()

        try:
            rows = await conn.fetch(
                """
                SELECT id, keyword, keyword_type, sector, created_at
                FROM search_keywords
                WHERE sector = $1
                """,
                sector,
            )

            if not rows:
                logger.debug("No search keywords found for sector: %s", sector)
                return {
                    "success": True,
                    "message": f"セクター '{sector}' に関連する検索キーワードは見つかりませんでした。",
                    "results": [],
                }
            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の検索キーワードが見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error retrieving search keywords for sector %s: %s", sector, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_search_keywords_by_keyword_type(keyword_type: str) -> Dict[str, Any]:
    """
    指定されたキーワードタイプに関連する保存された検索キーワードを取得します。

    引数:
        keyword_type: キーワードの種類（例: "commodity", "country"）

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.info("get_search_keywords_by_keyword_type called with keyword_type: %s", keyword_type)

        conn = await get_connection()

        try:
            rows = await conn.fetch(
                """
                SELECT id, keyword, keyword_type, sector, created_at
                FROM search_keywords
                WHERE keyword_type = $1
                """,
                keyword_type,
            )

            if not rows:
                logger.debug("No search keywords found for keyword type: %s", keyword_type)
                return {
                    "success": True,
                    "message": f"キーワードタイプ '{keyword_type}' に関連する検索キーワードは見つかりませんでした。",
                    "results": [],
                }
            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の検索キーワードが見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error retrieving search keywords by keyword type %s: %s", keyword_type, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_search_keywords_by_sector_and_keyword_type(sector: str, keyword_type: str) -> Dict[str, Any]:
    """
    指定されたセクターとキーワードタイプに関連する保存された検索キーワードを取得します。

    引数:
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）
        keyword_type: キーワードの種類（例: "commodity", "country"）

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.info(
            "get_search_keywords_by_sector_and_keyword_type called with "
            "sector: %s, keyword_type: %s", sector, keyword_type
        )
        conn = await get_connection()

        try:
            rows = await conn.fetch(
                """
                SELECT id, keyword, keyword_type, sector, created_at
                FROM search_keywords
                WHERE keyword_type = $1
                AND sector = $2
                """,
                keyword_type, sector
            )

            if not rows:
                logger.debug("No search keywords found for sector: %s, keyword type: %s", sector, keyword_type)
                return {
                    "success": True,
                    "message": f"キーワードタイプ '{keyword_type}' に関連する検索キーワードは見つかりませんでした。",
                    "results": [],
                }

            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の検索キーワードが見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error retrieving search keywords for sector %s and keyword type %s: %s", sector, keyword_type, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_commodity_country_relations_by_sector(sector: str) -> Dict[str, Any]:
    """
    指定されたセクターに関連する商品と国の関係を取得します。

    引数:
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug("get_commodity_country_relations_by_sector called with sector: %s", sector)

        conn = await get_connection()

        try:
            rows = await conn.fetch(
                """
                SELECT id, commodity_keyword, related_country_keyword, relation_type, sector, created_at
                FROM commodity_country_relations
                WHERE sector = $1
                """,
                sector,
            )

            if not rows:
                logger.debug("No commodity_country_relations found for sector: %s", sector)
                return {
                    "success": True,
                    "message": f"セクター '{sector}' に関連する商品と国の関係は見つかりませんでした。",
                    "results": [],
                }

            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の関係が見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()

    except Exception as e:
        logger.error("Error retrieving commodity_country_relations for sector %s: %s", sector, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_commodity_commodity_relations_by_sector(sector: str) -> Dict[str, Any]:
    """
    指定されたセクターに関連する商品と商品間の関係を取得します。

    引数:
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug("get_commodity_commodity_relations_by_sector called with sector: %s", sector)
        conn = await get_connection()
        try:
            rows = await conn.fetch(
                """
                SELECT id, commodity_keyword, related_commodity_keyword, relation_type, sector, created_at
                FROM commodity_commodity_relations
                WHERE sector = $1
                """,
                sector,
            )

            if not rows:
                logger.debug("No commodity_commodity_relations found for sector: %s", sector)
                return {
                    "success": True,
                    "message": f"セクター '{sector}' に関連する商品間の関係は見つかりませんでした。",
                    "results": [],
                }

            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の商品間の関係が見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error retrieving commodity_commodity_relations for sector %s: %s", sector, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_commodity_production_consumptions_by_sector(sector: str) -> Dict[str, Any]:
    """
    指定されたセクターに関連する商品と関係する国のその商品に対する生産・消費情報を取得します。

    引数:
        sector: セクター名 （"原油・石油製品", "天然ガス・LNG", "石炭", "鉄鋼・鉄鋼原料", "LME非鉄金属", "貴金属", "金融"）

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug("get_commodity_production_consumptions_by_sector called with sector: %s", sector)
        conn = await get_connection()
        try:
            rows = await conn.fetch(
                """
                SELECT id, commodity_keyword, related_country_keyword, sector, production, consumption, created_at
                FROM commodity_production_consumptions
                WHERE sector = $1
                """,
                sector,
            )

            if not rows:
                logger.debug("No commodity production/consumption found for sector: %s", sector)
                return {
                    "success": True,
                    "message": f"セクター '{sector}' に関連する商品と生産・消費情報は見つかりませんでした。",
                    "results": [],
                }

            # asyncpgのRowはdictに変換できる
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の生産・消費情報が見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error retrieving commodity production/consumption for sector %s: %s", sector, e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def get_country_keywords() -> Dict[str, Any]:
    """
    キーワードとして保存されている国の名前を取得します。

    返値:
        {"success": bool, "message": str, "results": List[Dict]}
    """
    try:
        logger.debug(
            "get_country_keywords called"
        )
        conn = await get_connection()

        try:
            rows = await conn.fetch(
                """
                SELECT DISTINCT keyword
                FROM search_keywords
                WHERE keyword_type = 'country'
                """
            )

            if not rows:
                logger.debug("No search keywords found for keyword type: 'country'")
                return {
                    "success": True,
                    "message": "キーワードタイプ 'country' に関連する検索キーワードは見つかりませんでした。",
                    "results": [],
                }

            # asyncpgのRowはdictに変換できる
            results = [dict(row) for row in rows]
            return {
                "success": True,
                "message": f"{len(results)}件の検索キーワードが見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error retrieving search keywords for keyword type 'country': %s", e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


async def execute_select_query(query: str) -> Dict[str, Any]:
    """
    PostgreSQLデータベースに対してSELECTクエリを実行し、結果を返します。
    """
    logger.info("Executing SELECT query: %s", query)
    if not query.strip().lower().startswith("select"):
        return {
            "success": False,
            "message": "Error: SELECT文のみ許可されています。",
            "results": [],
        }
    try:
        conn = await get_connection()
        try:
            if not query.strip().endswith(";"):
                query += ";"
            logger.debug("Executing query: %s", query)
            rows = await conn.fetch(query)
            if not rows:
                logger.debug("No results found for query: %s", query)
                return {
                    "success": True,
                    "message": "No results found.",
                    "results": [],
                }
            # カラム名はRowのkeys()で取得
            results = []
            for row in rows:
                row_dict = dict(row)
                for k, v in row_dict.items():
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        # 日付型は文字列に変換
                        row_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
                results.append(row_dict)
            return {
                "success": True,
                "message": f"{len(results)}件の結果が見つかりました。",
                "results": results,
            }
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Error executing SELECT query: %s", e)
        return {"success": False, "message": f"検索結果取得エラー: {e}", "results": []}


# 初期化処理
# init_database()
