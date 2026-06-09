"""Bash 命令执行工具

类似于 Mini SWE Agent，提供安全的 Bash 命令执行功能
"""
import subprocess
import os
from typing import Optional, Dict, Any
from langchain.tools import Tool
from utils.logger import logger


class BashTool:
    """Bash 命令执行工具类"""

    def __init__(
        self,
        working_dir: Optional[str] = None,
        timeout: int = 30,
        max_output_length: int = 10000
    ):
        """
        初始化 Bash 工具

        Args:
            working_dir: 工作目录，默认为当前目录
            timeout: 命令执行超时时间（秒）
            max_output_length: 最大输出长度
        """
        self.working_dir = working_dir or os.getcwd()
        self.timeout = timeout
        self.max_output_length = max_output_length

    def execute_command(self, command: str) -> str:
        """
        执行 Bash 命令

        Args:
            command: 要执行的命令

        Returns:
            命令执行的输出结果
        """
        try:
            logger.info(f"执行命令: {command}")

            # 使用 subprocess 执行命令
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
                text=True
            )

            # 组合标准输出和标准错误
            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"

            # 添加返回码
            output += f"\nReturn Code: {result.returncode}"

            # 限制输出长度
            if len(output) > self.max_output_length:
                output = output[:self.max_output_length] + "\n... (输出被截断)"

            logger.info(f"命令执行完成，返回码: {result.returncode}")
            return output

        except subprocess.TimeoutExpired:
            error_msg = f"命令执行超时 (>{self.timeout}秒): {command}"
            logger.error(error_msg)
            return f"ERROR: {error_msg}"

        except Exception as e:
            error_msg = f"命令执行失败: {str(e)}"
            logger.error(error_msg)
            return f"ERROR: {error_msg}"

    def get_langchain_tool(self) -> Tool:
        """
        创建 LangChain Tool 对象

        Returns:
            LangChain Tool 实例
        """
        return Tool(
            name="bash_execute",
            description=(
                f"Execute bash commands in the terminal. "
                f"IMPORTANT: You are currently in the repository root directory. "
                f"All commands execute from this location: {self.working_dir}. "
                f"Use relative paths (e.g., 'src/', './tests/', '*.py') instead of absolute paths. "
                f"Input should be a valid bash command string. "
                f"The tool will return the command's output (stdout and stderr) and return code. "
                f"Example inputs: 'ls -la src/', 'find . -name \"*.py\"', 'cat README.md'"
            ),
            func=self.execute_command
        )


def create_bash_tool(
    working_dir: Optional[str] = None,
    timeout: int = 30,
    max_output_length: int = 10000
) -> Tool:
    """
    创建 Bash 工具的便捷函数

    Args:
        working_dir: 工作目录
        timeout: 超时时间
        max_output_length: 最大输出长度

    Returns:
        LangChain Tool 实例
    """
    bash_tool = BashTool(
        working_dir=working_dir,
        timeout=timeout,
        max_output_length=max_output_length
    )
    return bash_tool.get_langchain_tool()
