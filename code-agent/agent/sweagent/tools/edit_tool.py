"""
文件编辑工具（SWE-Agent 标准）
"""
import os
from langchain.tools import Tool
from utils.logger import logger


class EditFileTool:
    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def edit_file(self, args_str: str) -> str:
        try:
            # ====================== 关键修复：去掉所有引号 ======================
            args_str = args_str.strip().strip('"').strip("'")
            # ====================================================================

            parts = args_str.split("|", 2)
            if len(parts) != 3:
                return (
                    "ERROR：格式错误！\n"
                    "正确：relative_path|search_str|replace_str\n"
                    f"输入：{args_str}"
                )

            relative_path, search_str, replace_str = parts
            relative_path = relative_path.strip()
            search_str = search_str.strip()
            replace_str = replace_str.strip()

            full_path = os.path.join(self.working_dir, relative_path)
            full_path = os.path.abspath(full_path)
            if not full_path.startswith(self.working_dir):
                return "ERROR：不允许修改工作目录外的文件"

            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            if search_str not in content:
                return f"ERROR：未找到要替换的内容"

            new_content = content.replace(search_str, replace_str)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return f"SUCCESS：已修改 {relative_path}"

        except Exception as e:
            return f"ERROR：编辑失败: {str(e)}"

    def get_langchain_tool(self) -> Tool:
        return Tool(
            name="edit_file",
            description=(
                f"Edit file with exact search-replace.\n"
                f"INPUT FORMAT: 'relative_path|search_str|replace_str'\n"
                f"TIP: If many changes needed, run MULTIPLE times.\n"
                f"EXAMPLE: main.py|old|new"
            ),
            func=self.edit_file
        )


def create_edit_file_tool(working_dir: str) -> Tool:
    tool = EditFileTool(working_dir)
    return tool.get_langchain_tool()