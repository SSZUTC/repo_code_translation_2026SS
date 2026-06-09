"""
文件查看工具（SWE-Agent 标准）
支持按行号范围查看，带边界判断
"""
import os
import re
from langchain.tools import Tool
from utils.logger import logger


class ViewFileTool:
    """文件查看工具类"""

    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def view_file(self, args_str: str) -> str:
        """
        统一接收一个字符串，格式：relative_path|start_line|end_line
        自动去除引号，兼容模型各种输出格式
        """
        try:
            # ====================== 关键修复：自动去掉所有引号！======================
            args_str = args_str.strip().strip('"').strip("'")
            # =======================================================================

            # 拆分参数
            parts = args_str.split("|")
            if len(parts) != 3:
                return (
                    "ERROR：参数格式错误！\n"
                    "正确格式：relative_path|start_line|end_line\n"
                    "示例：main.py|1|50\n"
                    f"你输入的内容：{args_str}"
                )

            relative_path = parts[0].strip()
            start_line = int(parts[1].strip())
            end_line = int(parts[2].strip())

            # 安全路径检查
            full_path = os.path.join(self.working_dir, relative_path)
            full_path = os.path.abspath(full_path)
            if not full_path.startswith(self.working_dir):
                return "ERROR：不允许访问工作目录外的文件"

            logger.info(f"查看文件: {relative_path} 行: {start_line}-{end_line}")

            # 读取文件
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            total_lines = len(lines)

            # 边界判断
            if start_line > total_lines:
                return f"ERROR：开始行 {start_line} 超过文件最大行数 {total_lines}"
            if end_line > total_lines:
                end_line = total_lines
            if start_line < 1:
                start_line = 1

            # 读取内容
            selected = lines[start_line-1:end_line]
            content = "".join(selected)

            return (
                f"=== 文件: {relative_path} ===\n"
                f"总行数: {total_lines}\n"
                f"显示: {start_line}-{end_line}\n\n"
                f"{content}"
            )

        except FileNotFoundError:
            return f"ERROR：文件不存在：{relative_path}"
        except ValueError:
            return f"ERROR：行号必须是整数！输入：{args_str}"
        except Exception as e:
            return f"ERROR：读取失败: {str(e)}"

    def get_langchain_tool(self) -> Tool:
        return Tool(
            name="view_file",
            description=(
                f"View file content by line range.\n"
                f"INPUT FORMAT: 'relative_path|start_line|end_line'\n"
                f"IMPORTANT: View NO MORE THAN 100 lines at a time.\n"
                f"WORKING DIR: {self.working_dir}\n"
                f"EXAMPLE: main.py|1|50"
            ),
            func=self.view_file
        )


def create_view_file_tool(working_dir: str) -> Tool:
    tool = ViewFileTool(working_dir)
    return tool.get_langchain_tool()