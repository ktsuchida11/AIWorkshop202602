import asyncio
import uuid
import logging
import streamlit as st
import html

from typing import List
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command
from dotenv import load_dotenv

from task_agent.middleware_agent import middleware_agent
from task_agent.structured_agent import structured_agent, MarketAnalysisReport
from task_agent.deep_agent import create_origin_deep_agent
from langchain.agents.middleware._redaction import PIIDetectionError


def render_market_report_markdown(report_obj: dict) -> str:
    """MarketAnalysisReport(dict or model) -> Markdown string"""
    try:
        if isinstance(report_obj, dict):
            report = MarketAnalysisReport.model_validate(report_obj)
        else:
            report = report_obj
    except Exception:
        # パース失敗時はプレーン表示（コードブロックで安全に見せる）
        return f"```\n{html.escape(str(report_obj))}\n```"

    parts = []
    parts.append(f"## Market Analysis Report: {report.report_id}")
    parts.append(
        f"**Meeting date:** {report.meeting_date or 'N/A'}  \n**Created at (JST):** {report.created_at}"
    )
    if report.author:
        parts.append(f"**Author:** {report.author}")

    parts.append("### Summary")
    parts.append(f"{report.summary or ''}")

    if report.top_findings:
        parts.append("### Top Findings")
        for f in report.top_findings:
            sev = f.severity or ""
            conf = f"{(f.confidence or 0)*100:.0f}%" if f.confidence is not None else ""
            parts.append(
                f"- **{f.title}** (_{sev} {conf}_): {f.detail}"
            )

    if report.market_snapshot:
        parts.append("### Market Snapshot")
        # Markdown table header
        parts.append("| Name | Type | Price | Δ (abs) | Δ (%) | Timestamp | Source |")
        parts.append("|---|---|---:|---:|---:|---|---|")
        for m in report.market_snapshot:
            price = "" if m.price is None else f"{m.price}"
            ch_abs = "" if m.change_abs is None else f"{m.change_abs}"
            ch_pct = "" if m.change_pct is None else f"{m.change_pct:.2f}%"
            name = str(m.name)
            inst = str(m.instrument_type or "")
            timestamp = str(m.timestamp or "")
            source = str(m.data_source or "")
            parts.append(
                "| {} | {} | {} | {} | {} | {} | {} |".format(
                    name, inst, price, ch_abs, ch_pct, timestamp, source
                )
            )

    if report.charts:
        parts.append("### Charts")
        for c in report.charts:
            parts.append(f"- [{c}]({c})")

    if report.recommendations:
        parts.append("### Recommendations")
        for i, r in enumerate(report.recommendations, start=1):
            parts.append(f"{i}. {r}")

    if report.sources:
        parts.append("### Sources")
        for s in report.sources:
            lbl = s.doc_id or s.published_filename or ""
            url = s.url or ""
            res = s.resource or ""
            if url:
                parts.append(f"- [{lbl}]({url}) ({res})")
            else:
                parts.append(f"- {lbl} ({res})")

    if report.notes:
        parts.append("### Notes")
        parts.append(f"> {report.notes}")

    if report.overall_confidence is not None:
        parts.append(f"*Overall confidence: {(report.overall_confidence*100):.0f}%*")

    return "\n\n".join(parts)


# Load environment variables early
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# テストときはここを入れ替える
# logger.info("Using Middleware Agent as the backend.")
# agent = middleware_agent
# logger.info("Using Structured Agent as the backend.")
# agent = structured_agent
logger.info("Using Deep Agent as the backend.")
agent = asyncio.run(create_origin_deep_agent("gpt", assistant_id="boj-research-agent"))


def init_session_state():
    """セッション状態を初期化する"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "waiting_for_approval" not in st.session_state:
        st.session_state.waiting_for_approval = False
    if "final_result" not in st.session_state:
        st.session_state.final_result = None
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = None
    # Human-in-the-loop 用
    if "hitl_action_requests" not in st.session_state:
        st.session_state.hitl_action_requests = None
    if "hitl_review_configs" not in st.session_state:
        st.session_state.hitl_review_configs = None


def reset_session():
    """セッション状態をリセットする"""
    st.session_state.messages = []
    st.session_state.waiting_for_approval = False
    st.session_state.final_result = None
    st.session_state.thread_id = None
    st.session_state.hitl_action_requests = None
    st.session_state.hitl_review_configs = None


def process_hitl_interrupt(step, notice_message=None, log_details=True):
    """
    共通の Human-in-the-loop interrupt 処理を行う。

    - step: ストリームから受け取った state dict
    - notice_message: セッションに追加する assistant メッセージ。省略時はデフォルト文言を使う。
    - log_details: action_requests の詳細ログを書くかどうか

    戻り値: interrupt が見つかり処理したら True、そうでなければ False
    """
    if "__interrupt__" not in step or not step["__interrupt__"]:
        return False

    interrupts = step["__interrupt__"]
    interrupt = interrupts[0]

    # interrupt の value を安全に取得
    hitl_value = getattr(interrupt, "value", None)
    if hitl_value is None and isinstance(interrupt, dict):
        hitl_value = interrupt.get("value")

    if hitl_value is None:
        logger.warning("[process_hitl_interrupt] interrupt があるが value が取得できません: %r", interrupt)
        return False

    action_requests = hitl_value.get("action_requests", [])
    review_configs = hitl_value.get("review_configs", [])

    # セッション状態に保存
    st.session_state.hitl_action_requests = action_requests
    st.session_state.hitl_review_configs = review_configs
    st.session_state.waiting_for_approval = True

    # UI 向けメッセージ
    if notice_message is None:
        notice_message = (
            "ツール実行の承認が必要です。内容を確認して APPPROVE / DENY を選択してください。"
        )
    st.session_state.messages.append({"role": "assistant", "content": notice_message})

    # ログ出力（詳細）
    if log_details:
        for i, req in enumerate(action_requests):
            desc = req.get("description")
            name = req.get("name")
            allowed = (
                review_configs[i].get("allowed_decisions") if i < len(review_configs) else None
            )
            logger.info(
                "[process_hitl_interrupt][HITL] action_request[%d]: name=%s, desc=%s, allowed_decisions=%s",
                i,
                name,
                desc,
                allowed,
            )

    return True


def feedback():
    """HITL の承認/却下を受け取る UI"""
    approve_col, deny_col = st.columns(2)

    result = None
    with approve_col:
        if st.button("APPROVE", use_container_width=True):
            result = "APPROVE"
    with deny_col:
        if st.button("DENY", use_container_width=True):
            result = "DENY"

    return result


async def run_agent(input_messages: List[HumanMessage]):
    """
    LangGraph エージェントを実行し、
    - Human-in-the-loop (__interrupt__) があれば承認待ち状態にする
    - なければ最終結果を state から取り出して表示する

    Args:
        input_messages (List[HumanMessage]): ユーザーからの入力メッセージのリスト
    """
    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    logger.info(f"[run_agent] start (thread_id={st.session_state.thread_id})")

    last_state = None  # 最終ステップの state を保存しておく

    # state をストリーム (values モード)
    # 各ステップで state 全体が step に入る
    with st.spinner("処理中...", show_time=True):

        try:
            async for step in agent.astream(
                {"messages": input_messages},
                config=config,
                stream_mode="values",
            ):
                # ここで step は「グラフの状態 (dict)」
                # 例: {"messages": [...], "remaining_steps": ..., "__interrupt__": ...}
                logger.info(
                    "[run_agent] step received (keys=%s)",
                    list(step.keys()),
                )

                last_state = step

                # 1. Human-in-the-loop (__interrupt__) があるか？
                # middleware で設定しているので、ここで interrupt 情報が入る
                # interrupt があれば承認待ちにして UI を切り替え
                if "__interrupt__" in step and step["__interrupt__"]:
                    # 共通処理へ委譲
                    handled = process_hitl_interrupt(step)
                    if handled:
                        # interrupt した時点で一旦終了 → Streamlit に UI 切り替えさせる
                        break

                # 2. 通常ステップの場合はとくに何もしない（last_state にだけ保存）
                #    ログだけ少し詳しめに
                if "messages" in step:
                    logger.info("[run_agent] messages in step: %d messages", len(step["messages"]))
                    msgs = step["messages"]
                    if msgs:
                        last_msg = msgs[-1]
                        # AI の途中結果があればログだけ取っておく
                        if isinstance(last_msg, AIMessage):
                            logger.info(
                                "[run_agent] intermediate AIMessage: %s",
                                repr(last_msg.content)[:200],
                            )

                # Continue to next step...
                if "structured_response" in step:
                    logger.info(
                        "[run_agent] structured_response=%s",
                        repr(step["structured_response"]),
                    )
                    if step["structured_response"] is not None:
                        # レスポンスを MarketAnalysisReport としてパースし、HTML にレンダリングして即座に表示
                        try:
                            sr = step["structured_response"]
                            # sr が dict の場合はそのまま受け取る
                            md_body = render_market_report_markdown(sr)
                            st.session_state.messages.append({"role": "assistant", "content": md_body})
                            st.session_state.final_result = md_body
                            # 表示更新のため rerun
                            logger.info("[run_agent] rendered structured_response and appended to session messages")
                            st.rerun()
                            return
                        except Exception as e:
                            logger.exception("Failed to render structured_response: %s", e)
        # PII 検出エラーのキャッチ
        except PIIDetectionError as e:
           # ユーザーへは「機密情報（APIキー等）が含まれているため処理を中断しました」と返すと親切です
            logger.error(f"⚠️ セキュリティ・ポリシー違反を検知しました: {e}")
            last_msg = "機密情報（APIキー等）が含まれているため処理を中断しました"
            st.session_state.messages.append(
                {"role": "assistant", "content": last_msg}
            )
            st.rerun()
            return
   


    # ===== ここからループ終了後の処理 =====

    # ① HITL で止まった場合：承認待ち UI を出したいので rerun
    if st.session_state.waiting_for_approval:
        logger.info("[run_agent] human-in-the-loop により一時停止しました (approval 待ち)")
        st.rerun()
        return

    # ② last_state が None の場合：エラー処理
    if last_state is None:
        logger.error("[run_agent] last_state が None です。結果が取得できませんでした。")
        st.session_state.messages.append(
            {"role": "assistant", "content": "エラーが発生しました。結果を取得できませんでした。"}
        )
        st.rerun()
        return

    # ③ last_state に messages が含まれていない場合：エラー処理
    if "messages" not in last_state:
        logger.error("[run_agent] last_state に messages が含まれていません: %s", last_state)
        st.session_state.messages.append(
            {"role": "assistant", "content": "エラーが発生しました。メッセージが見つかりませんでした。"}
        )
        st.rerun()
        return

    # ④ 最後の AIMessage を取得
    final_ai = None
    for msg in reversed(last_state["messages"]):
        if isinstance(msg, AIMessage):
            final_ai = msg
            break

    # AIMessage が見つからない場合：エラー処理
    if final_ai is None:
        logger.error(
            "[run_agent] messages はあるが AIMessage が見つかりませんでした: %s",
            last_state["messages"],
        )
        st.session_state.messages.append(
            {"role": "assistant", "content": f"エラーが発生しました。AI の応答が見つかりませんでした。：{last_state['messages']}"}
        )
        st.rerun()
        return

    # ⑤ 正常処理：最終結果を取得して表示
    final_text = final_ai.content
    logger.info("[run_agent] finished normally. final_text=%r", final_text[:200])
    if final_text:
        if "structured_response" in last_state:
            logger.info("[run_agent] last_state=%r", last_state["structured_response"])
        else:
            logger.info("[run_agent] last_state has no structured_response")

    st.session_state.final_result = final_text
    st.session_state.messages.append({"role": "assistant", "content": final_text})

    # UI を最終結果表示モードに切り替え
    st.rerun()


async def apply_hitl_decision(feedback_result: str):
    """
    APPROVE / DENY ボタン押下後に呼び出し、
    - APPROVE: Command(resume=...) でエージェントを再開
    - DENY   : 現在のリクエスト処理を中断して終了（エージェントは再開しない）
    """
    if not st.session_state.thread_id:
        st.error("thread_id がありません。最初からやり直してください。")
        return

    config = {"configurable": {"thread_id": st.session_state.thread_id}}

    # --- DENY の場合はここで処理を打ち切る -------------------------
    if feedback_result == "DENY":
        # 必要に応じて agent にも「deny」を伝えたい場合はコメントアウトを外す
        # try:
        #     decisions = [{
        #         "type": "deny",
        #         "message": "ユーザーがツール実行を拒否しました。"
        #     }]
        #     await agent.ainvoke(
        #         Command(resume={"decisions": decisions}),
        #         config=config,
        #     )
        # except Exception as e:
        #     logger.exception("[apply_hitl_decision] deny 用の再開処理でエラー: %s", e)

        # UI 側の状態を「このリクエストはここで終了」に切り替える
        st.session_state.waiting_for_approval = False
        st.session_state.hitl_action_requests = None
        st.session_state.hitl_review_configs = None

        cancel_msg = "ツール実行が DENY されたため、このリクエストの処理を中断しました。"
        st.session_state.final_result = cancel_msg
        st.session_state.messages.append(
            {"role": "assistant", "content": cancel_msg}
        )

        logger.info("[apply_hitl_decision] tool call denied. Abort current workflow.")
        st.rerun()
        return

    # --- APPROVE の場合: これまで通り Command(resume) で再開 --------
    decisions = [{"type": "approve"}]
    msg = "ツール実行を APPROVE しました。処理を再開します。"

    st.session_state.messages.append({"role": "assistant", "content": msg})
    logger.info("[apply_hitl_decision] decision=%s", decisions)

    last_state = None
    hitl_triggered_again = False

    with st.spinner("承認結果を反映して処理を再開中...", show_time=True):
        async for step in agent.astream(
            Command(resume={"decisions": decisions}),
            config=config,
            stream_mode="values",
        ):
            logger.info(
                "[apply_hitl_decision] step received (keys=%s)",
                list(step.keys()),
            )
            last_state = step

            # 再開後にも interrupt が起きるケースに対応
            # 再開後にも interrupt が起きるケースに対応
            handled = process_hitl_interrupt(
                step,
                notice_message=(
                    "再開後もツール実行の承認が必要です。再度 APPROVE / DENY を選択してください。"
                ),
                log_details=False,
            )
            if handled:
                hitl_triggered_again = True
                logger.info("[apply_hitl_decision] interrupt triggered again.")
                break

    if hitl_triggered_again and st.session_state.waiting_for_approval:
        st.rerun()
        return

    # 最終結果の反映 (APPROVE で最後まで走り切ったケース)
    st.session_state.waiting_for_approval = False
    st.session_state.hitl_action_requests = None
    st.session_state.hitl_review_configs = None

    if last_state and "messages" in last_state:
        final_ai = None
        for msg in reversed(last_state["messages"]):
            if isinstance(msg, AIMessage):
                final_ai = msg
                break

        if final_ai:
            final_text = final_ai.content
            st.session_state.final_result = final_text
            st.session_state.messages.append(
                {"role": "assistant", "content": final_text}
            )
            logger.info(
                "[apply_hitl_decision] finished after approve. final_text=%r",
                final_text[:200],
            )
        else:
            logger.warning(
                "[apply_hitl_decision] AIMessage が見つからないため最終結果を表示できません。"
            )

    st.rerun()


# セッション状態の初期化を実行
init_session_state()


async def app():
    st.title("Webリサーチエージェント")

    # これまでのメッセージを表示
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            st.chat_message("assistant").markdown(msg["content"])

    # 最終結果表示
    if st.session_state.final_result and not st.session_state.waiting_for_approval:
        st.subheader("最終結果")
        # Final result is rendered as Markdown
        st.markdown(st.session_state.final_result)

    # 1) 承認待ちでないとき：通常のチャット入力
    if not st.session_state.waiting_for_approval:
        user_input = st.chat_input("メッセージを入力してください")
        if user_input:
            reset_session()
            st.session_state.thread_id = str(uuid.uuid4())

            st.chat_message("user").markdown(user_input)
            st.session_state.messages.append(
                {"role": "user", "content": user_input}
            )

            messages = [HumanMessage(content=user_input)]
            await run_agent(messages)

    # 2) 承認待ちのとき：HITL UI（action_requests + APPROVE / DENY）
    else:
        st.info("ツールの承認待ちです。内容を確認して、APPROVE / DENY を押してください。")

        if st.session_state.hitl_action_requests:
            for i, action in enumerate(st.session_state.hitl_action_requests):
                # --- name / description ---
                name = action.get("name")
                st.markdown(f"##### 承認確認対象ツール {i+1}")
                st.write(f"**name**: `{action.get('name')}`")
                desc = action.get("description")
                if desc:
                    st.write(desc)

                # --- 引数を取得（arguments フィールド）★ ---
                args = action.get("args", {}) or {}

                # Web Search の場合は query をわかりやすく表示 ★
                # TavilySearch のデフォルト名は "tavily_search" です。
                if name in ("tavily_search", "web_search"):
                    query = args.get("query") or args.get("input")
                    if query:
                        st.markdown(f"**検索クエリ:** `{query}`")

                # Write File の場合は保存先と内容を表示 ★
                elif name == "write_file":
                    file_path = args.get("file_path")
                    if file_path:
                        st.markdown(f"**保存ファイル名:** `{file_path}`")
                    text = args.get("text")
                    if text:
                        with st.container(height=400):
                            st.html(text, width="stretch")

                logger.info("[app] HITL action_request[%d]: %s", i, action)

        decision = feedback()
        if decision:
            await apply_hitl_decision(decision)


# メインの実行
if __name__ == "__main__":

    asyncio.run(app())
