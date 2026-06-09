"""运行 Code Agent 的主入口

用户传入任务 prompt 和代码仓库地址，Agent 使用绑定到仓库目录的工具执行任务
"""
import os
import argparse
import logging
import asyncio
from pathlib import Path
from dotenv import load_dotenv

from llm.config import LLMConfig, DEFAULT_LLM_CONFIG
from llm.agent import ReActAgent
from tools.bash_tool import create_bash_tool
from tools.edit_tool import create_edit_file_tool
from tools.view_tool import create_view_file_tool

from utils.logger import logger, setup_logger


def run_agent(
    task_prompt: str,
    repo_path: str,
    llm_provider: str = 'openai',
    llm_model: str = 'openai/gpt-4o',
    verbose: bool = False,
    debug: bool = False
):
    """
    运行 Code Agent

    Args:
        task_prompt: 用户任务描述
        repo_path: 代码仓库路径
        llm_provider: LLM 提供商
        llm_model: LLM 模型名称
        verbose: 是否显示详细日志
        debug: 是否启用 DEBUG 模式
    """
    # 设置日志级别
    if debug:
        setup_logger(level=logging.DEBUG)

    # 验证仓库路径
    repo_path = os.path.abspath(repo_path)
    if not os.path.exists(repo_path):
        logger.error(f"仓库路径不存在: {repo_path}")
        return

    if not os.path.isdir(repo_path):
        logger.error(f"仓库路径不是目录: {repo_path}")
        return

    logger.info("=" * 80)
    logger.info("Code Agent 启动")
    logger.info("=" * 80)
    logger.info(f"任务: {task_prompt}")
    logger.info(f"仓库路径: {repo_path}")
    logger.info(f"LLM: {llm_provider}/{llm_model}")
    logger.info("=" * 80)

    # 创建 LLM 配置
    api_key = os.getenv(f'{llm_provider.upper()}_API_KEY', '')
    if not api_key:
        # 如果环境变量为空，使用默认配置中的 API key
        logger.warning(f"未设置 {llm_provider.upper()}_API_KEY 环境变量，将使用默认配置")
        api_key = DEFAULT_LLM_CONFIG.api_key

    config = LLMConfig(
        provider=llm_provider,
        api_key=api_key,
        model=llm_model,
        temperature=0.1,
        max_output_tokens=16384,  # 单次输出最大 token 数
        max_total_tokens=262144   # 能处理的总 token 大小
    )

    # 如果是 ark provider，设置 base_url
    if llm_provider == 'ark':
        config.base_url = ''

    # 创建 Agent
    logger.info("初始化 ReAct Agent...")
    agent = ReActAgent(config)

    # 添加工具，绑定到指定的仓库路径
    logger.info("注册工具...")

    # 1. Bash 工具 - 绑定到仓库路径
    bash_tool = create_bash_tool(
        working_dir=repo_path,  # 绑定到指定的仓库路径
        timeout=60  # 增加超时时间
    )
    agent.add_tool(bash_tool)
    logger.info(f"✓ Bash 工具已注册，工作目录: {repo_path}")

    view_tool = create_view_file_tool(
        working_dir=repo_path
    )
    agent.add_tool(view_tool)
    logger.info(f"✓ View 工具已注册，工作目录: {repo_path}")


    logger.info("=" * 80)
    logger.info("开始执行任务...")
    logger.info("=" * 80)

    # 执行任务
    try:
        result = agent.run(task_prompt)

        logger.info("=" * 80)
        logger.info("任务执行完成")
        logger.info("=" * 80)
        logger.info("结果:")
        print("\n" + result['output'] + "\n")

        if verbose and result.get('intermediate_steps'):
            logger.info("中间步骤:")
            for i, step in enumerate(result['intermediate_steps'], 1):
                logger.info(f"  步骤 {i}: {step}")

        # 获取并打印 token 统计信息
        logger.info("=" * 80)
        logger.info("Token 使用统计")
        logger.info("=" * 80)

        # 由于 get_token_usage_stats 是 async 方法，需要使用 asyncio.run
        stats = asyncio.run(agent.get_token_usage_stats())

        logger.info(f"消息数量: {stats.get('message_count', 0)}")
        logger.info(f"最大总 tokens: {stats.get('max_total_tokens', 0)}")
        logger.info(f"强制停止阈值: {stats.get('force_stop_threshold', 0)}")

        # 如果有 token 统计（仅 openai 和 ark）
        if 'total_tokens' in stats:
            logger.info(f"Provider: {stats.get('provider', 'N/A')}")
            logger.info(f"LLM 调用次数: {stats.get('call_count', 0)}")
            logger.info(f"总 tokens: {stats.get('total_tokens', 0)}")
            logger.info(f"输入 tokens: {stats.get('prompt_tokens', 0)}")
            logger.info(f"输出 tokens: {stats.get('completion_tokens', 0)}")
        else:
            logger.info("注意: 当前 provider 不支持 token 统计")

        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"任务执行失败: {str(e)}")
        raise


def main():
    """命令行入口"""
    # 加载环境变量
    load_dotenv()

    parser = argparse.ArgumentParser(
        description='Code Agent - 基于 LangChain 的代码分析助手',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基础使用
  python run_agent "列出所有 Python 文件" /path/to/repo

  # 复杂任务
  python run_agent "找出所有 TODO 注释并统计数量" /path/to/repo --verbose
        """
    )

    parser.add_argument(
        'task',
        type=str,
        help='任务描述 (英文)'
    )

    parser.add_argument(
        'repo_path',
        type=str,
        help='代码仓库路径'
    )

    parser.add_argument(
        '--provider',
        type=str,
        default='openai',
        choices=['ark', 'openai', 'azure'],
        help='LLM 提供商 (默认: openai)'
    )

    parser.add_argument(
        '--model',
        type=str,
        default='openai/gpt-4o',
        help='LLM 模型名称'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='显示详细日志'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用 DEBUG 模式'
    )

    args = parser.parse_args()

    # 执行任务
    run_agent(
        task_prompt=args.task,
        repo_path=args.repo_path,
        llm_provider=args.provider,
        llm_model=args.model,
        verbose=args.verbose,
        debug=args.debug
    )


if __name__ == "__main__":
    main()
