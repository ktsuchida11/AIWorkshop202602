import os
import sys
from types import SimpleNamespace
from contextlib import contextmanager
import traceback

# テスト対象のモジュールが同ディレクトリにあるためパスを調整してからインポート
HERE = os.path.dirname(__file__)
APP_DIR = os.path.dirname(HERE)
sys.path.insert(0, APP_DIR)

import aws_llm.py_app.app as app


def __make_fake_st():
    """
        テスト用の偽の st オブジェクトを作成する

        Returns:
            SimpleNamespace: 偽の st オブジェクト
    """
    fake = SimpleNamespace()
    ss = SimpleNamespace()
    ss.messages = []
    ss.waiting_for_approval = False
    ss.hitl_action_requests = None
    ss.hitl_review_configs = None
    fake.session_state = ss
    return fake


def describe_test(name: str, expected: str):
    """テストの説明を出力するヘルパー。

    name: テスト名や要旨
    expected: 合格条件の簡単な説明
    """
    print(f"[TEST] {name}")
    print(f"[EXPECT] {expected}")


@contextmanager
def case_context(name: str, expected: str):
    """コンテキストマネージャーでテストの説明と結果を出力する。

    with test_case("name", "expected"):
        # 実際のテストコード
        ...
    """
    print(f"[TEST] {name}")
    print(f"[EXPECT] {expected}")
    try:
        yield
    except Exception:
        tb = traceback.format_exc()
        print(f"[RESULT] {name}: FAIL")
        print(tb)
        raise
    else:
        print(f"[RESULT] {name}: PASS")


# テストケース
# process_hitl_interrupt の動作確認
# 各種ケースを網羅的にテストする

def test_no_interrupt_returns_false(monkeypatch):
    """
        __interrupt__ が存在しない場合、Falseを返し状態が変更されないことを確認する
    """
    fake = __make_fake_st()
    monkeypatch.setattr(app, "st", fake)

    step = {}
    with case_context(
        "no_interrupt_returns_false",
        "interrupt が無いので False を返し、waiting_for_approval は変更されない",
    ):
        res = app.process_hitl_interrupt(step)
        # __interrupt__ が存在しないため、messages は空のリストであることを確認
        assert res is False
        # 状態が変更されていないことを確認
        assert fake.session_state.waiting_for_approval is False
        # action_requests が None であることを確認
        assert fake.session_state.hitl_action_requests is None


def test_process_dict_interrupt_updates_state(monkeypatch):
    """
        __interrupt__ が辞書形式で渡された場合に
        正常に処理されることを確認する
    """
    fake = __make_fake_st()
    monkeypatch.setattr(app, "st", fake)

    action = {"name": "web_search", "description": "search web", "args": {"query": "pytest"}}
    review = {"allowed_decisions": ["approve", "deny"]}
    step = {"__interrupt__": [{"value": {"action_requests": [action], "review_configs": [review]}}]}

    with case_context(
        "process_dict_interrupt_updates_state",
        "dict の interrupt を処理し True を返す。waiting_for_approval が True になり、action_requests が保存され、messages に通知が追加される",
    ):
        res = app.process_hitl_interrupt(step)
        # 辞書形式のため、messages は空のリストであることを確認
        assert res is True
        # 承認待ち状態になっていることを確認
        assert fake.session_state.waiting_for_approval is True
        # action_requests がリスト形式であることを確認
        assert isinstance(fake.session_state.hitl_action_requests, list)
        # 最初の要素が web_search であることを確認
        assert fake.session_state.hitl_action_requests[0]["name"] == "web_search"
        # メッセージが1件以上存在することを確認
        assert len(fake.session_state.messages) >= 1
        # メッセージ内容に "承認" が含まれていることを確認
        assert "承認" in fake.session_state.messages[-1]["content"]


def test_process_object_interrupt_updates_state(monkeypatch):
    """
        __interrupt__ がオブジェクト形式で渡された場合に
        正常に処理されることを確認する
    """
    fake = __make_fake_st()
    monkeypatch.setattr(app, "st", fake)

    class InterruptObj:
        def __init__(self, v):
            self.value = v

    action = {"name": "write_file", "description": "write file", "args": {"file_path": "out.txt"}}
    review = {"allowed_decisions": ["approve"]}
    # interrupt オブジェクトを作成
    obj = InterruptObj({"action_requests": [action], "review_configs": [review]})
    step = {"__interrupt__": [obj]}

    with case_context(
        "process_object_interrupt_updates_state",
        "オブジェクトの .value を読み取り処理する。waiting_for_approval が True になり action_requests が保存される",
    ):
        res = app.process_hitl_interrupt(step)
        # オブジェクト形式のため、messages は空のリストであることを確認
        assert res is True
        # 承認待ち状態になっていることを確認
        assert fake.session_state.waiting_for_approval is True
        # 最初の要素が write_file であることを確認
        assert fake.session_state.hitl_action_requests[0]["name"] == "write_file"


def test_empty_action_requests(monkeypatch):
    """
        __interrupt__ が空の action_requests を持つ場合に
        エラーとなることを確認する
    """
    fake = __make_fake_st()
    monkeypatch.setattr(app, "st", fake)

    step = {"__interrupt__": [{"value": {"action_requests": [], "review_configs": []}}]}
    with case_context(
        "empty_action_requests",
        "action_requests が空でも処理成功（True）となり、waiting_for_approval は True、空リストが保存される",
    ):
        res = app.process_hitl_interrupt(step)
        assert res is True
        assert fake.session_state.waiting_for_approval is True
        assert fake.session_state.hitl_action_requests == []


def test_insufficient_review_configs(monkeypatch):
    """
        __interrupt__ が action_requests よりも少ない
        review_configs を持つ場合に正常に処理されることを確認する
    """
    fake = __make_fake_st()
    monkeypatch.setattr(app, "st", fake)

    action1 = {"name": "a1"}
    action2 = {"name": "a2"}
    review = {"allowed_decisions": ["approve"]}
    step = {"__interrupt__": [{"value": {"action_requests": [action1, action2], "review_configs": [review]}}]}

    with case_context(
        "insufficient_review_configs",
        "review_configs が不足していても処理成功（True）。action_requests の数は保持され、review_configs はそのまま保存される",
    ):
        res = app.process_hitl_interrupt(step)
        assert res is True
        assert len(fake.session_state.hitl_action_requests) == 2
        # review_configs は 1 件だけ存在する
        assert len(fake.session_state.hitl_review_configs) == 1


def test_missing_value_returns_false(monkeypatch):
    """
        __interrupt__ オブジェクトに value が存在しない場合に
        Falseを返し状態が変更されないことを確認する
    """
    fake = __make_fake_st()
    monkeypatch.setattr(app, "st", fake)

    # interrupt オブジェクトに value がないケース
    step = {"__interrupt__": [{}]}
    with case_context(
        "missing_value_returns_false",
        "interrupt に value が無ければ False を返し state は更新されない",
    ):
        res = app.process_hitl_interrupt(step)
        assert res is False
        assert fake.session_state.waiting_for_approval is False


def test_custom_notice_message(monkeypatch):
    """
        カスタムの通知メッセージが指定された場合に
        その内容がメッセージに反映されることを確認する
    """
    fake = __make_fake_st()
    monkeypatch.setattr(app, "st", fake)

    action = {"name": "x"}
    step = {"__interrupt__": [{"value": {"action_requests": [action], "review_configs": []}}]}
    custom = "カスタムの通知メッセージです"
    with case_context(
        "custom_notice_message",
        "notice_message を渡すと messages の最後の要素にその文字列が入る",
    ):
        res = app.process_hitl_interrupt(step, notice_message=custom)
        assert res is True
        assert fake.session_state.messages[-1]["content"] == custom
