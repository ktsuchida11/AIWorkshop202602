"""
app.py の純粋関数ユニットテスト

対象関数:
  - render_market_report_markdown(report_obj) -> str

Streamlit 依存の関数（run_agent, app, feedback 等）は対象外。
process_hitl_interrupt のテストは test_process_hitl_interrupt.py が担当。

実行方法:
  cd aws_llm/py_app
  uv run pytest tests/test_app.py -v
"""

import os
import sys

HERE = os.path.dirname(__file__)
APP_DIR = os.path.dirname(HERE)
sys.path.insert(0, APP_DIR)

import pytest  # noqa: E402
import app  # noqa: E402
from task_agent.structured_agent import MarketAnalysisReport


# ------------------------------------------------------------------ #
# テスト用データ                                                        #
# ------------------------------------------------------------------ #
MINIMAL_REPORT = {
    "report_id": "RPT-001",
    "created_at": "2025-01-01T09:00:00+09:00",
    "summary": "テスト用サマリーです。",
    "top_findings": [],
    "market_snapshot": [],
    "sources": [],
}

FULL_REPORT = {
    "report_id": "RPT-FULL",
    "meeting_date": "2025-03-20",
    "created_at": "2025-03-21T10:00:00+09:00",
    "author": "テストエージェント",
    "summary": "利上げ観測が高まり、債券市場は軟調に推移した。",
    "top_findings": [
        {
            "title": "金利上昇",
            "detail": "10年債利回りが1.5%を超えた。",
            "severity": "high",
            "confidence": 0.9,
        }
    ],
    "market_snapshot": [
        {
            "name": "日経平均",
            "ticker": "N225",
            "instrument_type": "Equity",
            "price": 38000.0,
            "change_abs": -300.0,
            "change_pct": -0.78,
            "timestamp": "2025-03-21T15:30:00+09:00",
            "data_source": "Yahoo Finance",
        }
    ],
    "charts": ["https://example.com/chart.png"],
    "recommendations": ["ポートフォリオの債券比率を引き下げることを検討する。"],
    "sources": [
        {
            "doc_id": "BOJ-2025-03",
            "url": "https://www.boj.or.jp/",
            "resource": "minutes",
            "published_filename": "boj_minutes_2025_03.pdf",
        }
    ],
    "overall_confidence": 0.85,
    "notes": "一部データが未取得のため暫定値を含む。",
}


# ================================================================== #
# render_market_report_markdown
# ================================================================== #
class TestRenderMarketReportMarkdown:
    def test_report_id_appears_in_output(self):
        """report_id が出力 Markdown に含まれること"""
        result = app.render_market_report_markdown(MINIMAL_REPORT)
        assert "RPT-001" in result

    def test_summary_appears_in_output(self):
        """summary が出力 Markdown に含まれること"""
        result = app.render_market_report_markdown(MINIMAL_REPORT)
        assert "テスト用サマリーです。" in result

    def test_findings_rendered_as_list(self):
        """top_findings が箇条書き（ - ）として出力されること"""
        result = app.render_market_report_markdown(FULL_REPORT)
        assert "金利上昇" in result
        assert "10年債利回りが1.5%を超えた。" in result
        assert "- **金利上昇**" in result

    def test_market_snapshot_renders_as_table(self):
        """market_snapshot が Markdown テーブル（| で囲まれた行）として出力されること"""
        result = app.render_market_report_markdown(FULL_REPORT)
        assert "日経平均" in result
        assert "|" in result  # Markdown テーブルの区切り文字

    def test_optional_fields_omitted_when_none(self):
        """meeting_date・author が None のとき、それらのセクションが出力に含まれないこと"""
        result = app.render_market_report_markdown(MINIMAL_REPORT)
        assert "meeting_date" not in result
        assert "Author" not in result

    def test_full_report_includes_all_sections(self):
        """全フィールドを持つレポートでは各セクションが出力されること"""
        result = app.render_market_report_markdown(FULL_REPORT)
        assert "### Summary" in result
        assert "### Top Findings" in result
        assert "### Market Snapshot" in result
        assert "### Recommendations" in result
        assert "### Sources" in result
        assert "### Notes" in result

    def test_confidence_rendered_as_percentage(self):
        """overall_confidence が % 表示で出力されること"""
        result = app.render_market_report_markdown(FULL_REPORT)
        assert "85%" in result

    def test_invalid_input_falls_back_to_code_block(self):
        """必須フィールドが欠落した dict は ``` コードブロック で安全に表示されること"""
        result = app.render_market_report_markdown({"completely": "wrong"})
        assert "```" in result

    def test_returns_string(self):
        """戻り値が文字列であること"""
        result = app.render_market_report_markdown(MINIMAL_REPORT)
        assert isinstance(result, str)
        assert len(result) > 0


# ================================================================== #
# 診断用テスト: MarketAnalysisReport の直接バリデーション確認          #
# ================================================================== #
class TestMarketAnalysisReportValidation:
    """MarketAnalysisReport.model_validate() を直接呼んで検証する診断テスト"""

    def test_minimal_report_model_validate(self):
        """MINIMAL_REPORT が model_validate で正常に検証されること"""
        try:
            report = MarketAnalysisReport.model_validate(MINIMAL_REPORT)
            assert report.report_id == "RPT-001"
        except Exception as e:
            pytest.fail(f"model_validate(MINIMAL_REPORT) 失敗: {type(e).__name__}: {e}")

    def test_full_report_model_validate(self):
        """FULL_REPORT が model_validate で正常に検証されること（失敗時に詳細エラーを表示）"""
        try:
            report = MarketAnalysisReport.model_validate(FULL_REPORT)
            assert report.report_id == "RPT-FULL"
        except Exception as e:
            pytest.fail(f"model_validate(FULL_REPORT) 失敗: {type(e).__name__}: {e}")
