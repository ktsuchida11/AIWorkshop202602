import logging


def pytest_configure(config):
    """テスト実行前に Streamlit の一部ロガーのログレベルを上げて警告を抑える。

    ui_test をインポートしたときに表示される
    "Thread 'MainThread': missing ScriptRunContext!" 警告を無視したい場合に有効です。
    """
    logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)
    logging.getLogger("streamlit.runtime.state.session_state_proxy").setLevel(logging.ERROR)
