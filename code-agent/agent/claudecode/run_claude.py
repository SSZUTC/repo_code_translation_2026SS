"""ClaudeCode 主入口脚本

用法：
    python run_claude.py "你的任务描述" /path/to/repo

特性：
    - 高风险操作安全审查（默认需要用户确认）
    - 支持委派子 Agent 处理复杂子任务
"""
import os
import sys
import json
import argparse
from typing import Optional

# 确保可以从本地包导入
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from llm.config import LLMConfig, DEFAULT_LLM_CONFIG
from llm.agent import ClaudeCodeAgent
from safety.guard import ConfirmationMode
from utils.logger import get_logger, setup_logger

logger = get_logger()


def run_claude(
    task: str,
    repo_path: str,
    provider: str = "openai",
    model: str = "openai/gpt-4o",
    api_key: str = "",
    confirm_mode: str = "interactive",
    disable_delegation: bool = False,
    result_path: Optional[str] = None,
):
    repo_path = os.path.abspath(repo_path)
    if not os.path.exists(repo_path):
        logger.error(f"仓库路径不存在: {repo_path}")
        return

    setup_logger()

    logger.info("=" * 80)
    logger.info("ClaudeCode 启动")
    logger.info("=" * 80)
    logger.info(f"任务: {task[:150]}")
    logger.info(f"仓库路径: {repo_path}")
    logger.info(f"模型: {provider}/{model}")
    logger.info(f"确认模式: {confirm_mode}")
    logger.info(f"子 Agent 委派: {'禁用' if disable_delegation else '启用'}")
    logger.info("=" * 80)

    # 配置
    key = api_key or os.getenv(f"{provider.upper()}_API_KEY", "") or DEFAULT_LLM_CONFIG.api_key
    config = LLMConfig(
        provider=provider,
        api_key=key,
        model=model,
        temperature=0.1,
    )

    # 创建 Agent
    agent = ClaudeCodeAgent(
        config=config,
        working_dir=repo_path,
        confirm_mode=ConfirmationMode(confirm_mode),
        enable_delegation=not disable_delegation,
    )

    # 执行任务
    result = agent.run(task)

    # 输出结果
    logger.info("=" * 80)
    logger.info("最终结果")
    logger.info("=" * 80)
    print("\n" + str(result.get("output", "")) + "\n")

    # ========== 输出中间步骤（让 trace 文件能捕获完整调用链） ==========
    steps = result.get("intermediate_steps", []) or []
    if steps:
        logger.info("=" * 80)
        logger.info(f"完整调用轨迹（共 {len(steps)} 步）")
        logger.info("=" * 80)
        for step in steps:
            print(f"\n--- Step {step.get('step', '?')}  tool=[{step.get('tool', '')}] ---")
            thought = step.get("thought", "")
            if thought:
                print(f"THOUGHT: {thought[:800]}")
            tool_input = step.get("tool_input", "")
            if tool_input:
                print(f"ACTION INPUT: {tool_input[:800]}")
            obs = step.get("observation", "")
            if obs:
                print(f"OBSERVATION: {obs[:800]}")

    # 安全摘要
    safety = result.get("safety_summary")
    if safety:
        logger.info(f"安全审查摘要: {safety}")

    delegation = result.get("delegation_summary")
    if delegation:
        logger.info(f"子 Agent 委派摘要: {delegation}")

    # 如果提供了结果输出路径，直接 dump 完整结构化结果
    if result_path:
        try:
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"结构化结果已写入: {result_path}")
        except Exception as e:
            logger.warning(f"写入结果文件失败: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="ClaudeCode - 带安全审查和子 Agent 委派的代码助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本使用（需要交互式确认高风险操作）
  python run_claude.py "分析 astropy 项目中 separability_matrix 的实现" ../data/repo/astropy

  # 自动允许高风险操作（仅用于测试环境！）
  python run_claude.py "列出目录并做一些操作" ./repo --confirm-mode auto_allow

  # 禁用子 Agent 委派（只使用基础工具）
  python run_claude.py "简单的代码浏览任务" ./repo --disable-delegation
""")

    parser.add_argument("task", type=str, help="任务描述")
    parser.add_argument("repo_path", type=str, help="代码仓库路径")
    parser.add_argument("--provider", type=str, default="openai", help="LLM provider")
    parser.add_argument("--model", type=str, default="openai/gpt-4o", help="模型名称")
    parser.add_argument("--api-key", type=str, default="", help="API key（或使用环境变量）")
    parser.add_argument(
        "--confirm-mode", type=str, default="interactive",
        choices=["interactive", "auto_allow", "auto_deny"],
        help="高风险操作确认模式: interactive(默认) | auto_allow | auto_deny"
    )
    parser.add_argument(
        "--disable-delegation", action="store_true",
        help="禁用子 Agent 委派系统（减少 token 使用）"
    )
    parser.add_argument(
        "--result-json", type=str, default=None,
        help="把完整结构化结果写入这个 JSON 文件（不会被 stdout 噪声干扰）"
    )

    args = parser.parse_args()

    run_claude(
        task=args.task,
        repo_path=args.repo_path,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        confirm_mode=args.confirm_mode,
        disable_delegation=args.disable_delegation,
        result_path=args.result_json,
    )


if __name__ == "__main__":
    main()
