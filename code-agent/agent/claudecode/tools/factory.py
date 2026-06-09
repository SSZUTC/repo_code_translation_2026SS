"""工具层 - 基于 sweagent 的工具，但附加安全审查

复用 sweagent 中已验证的工具实现，并在此基础上：
- 增加安全审查包装器
- 增加统一的 view_file / edit_file / bash 工具
"""
import os
import subprocess
from typing import Optional
from langchain.tools import Tool

from utils.logger import get_logger
from safety.guard import SafetyGuard

logger = get_logger()


# ============================================================
# Bash 工具
# ============================================================

class _BashTool:
    def __init__(self, working_dir: Optional[str] = None, timeout: int = 60):
        self.working_dir = working_dir or os.getcwd()
        self.timeout = timeout

    def execute(self, command: str) -> str:
        try:
            logger.info(f"[Bash] {command}")
            result = subprocess.run(
                command, shell=True, cwd=self.working_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=self.timeout, text=True
            )
            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"
            output += f"\nReturn Code: {result.returncode}"
            if len(output) > 15000:
                output = output[:15000] + "\n... (输出被截断)"
            return output
        except subprocess.TimeoutExpired:
            return f"ERROR: 命令超时 (>{self.timeout}秒): {command}"
        except Exception as e:
            return f"ERROR: {e}"


def create_bash_tool(working_dir: str, safety_guard: SafetyGuard, timeout: int = 60) -> Tool:
    """创建带安全审查的 Bash 工具"""
    base = _BashTool(working_dir=working_dir, timeout=timeout)
    safe_execute = safety_guard.wrap_bash_tool(base.execute)
    return Tool(
        name="bash_execute",
        description=(
            f"Execute bash commands in terminal. Working directory: {working_dir}. "
            "Use relative paths. Examples: 'ls -la', 'find . -name *.py', 'cat main.py'. "
            "Note: High-risk commands (rm -rf, sudo, etc.) require user confirmation."
        ),
        func=safe_execute,
    )


# ============================================================
# View File 工具
# ============================================================

class _ViewTool:
    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def view(self, args_str: str) -> str:
        try:
            args_str = args_str.strip().strip('"').strip("'")
            if not args_str:
                return "ERROR: 请提供文件路径"

            # 支持格式: path[:start_line-end_line]
            path = args_str
            start_line, end_line = 0, 200
            if ':' in path:
                path, _, range_part = path.partition(':')
                if '-' in range_part:
                    try:
                        start_line, end_line = map(int, range_part.split('-', 1))
                    except ValueError:
                        pass

            full_path = os.path.abspath(os.path.join(self.working_dir, path))
            if not full_path.startswith(self.working_dir):
                return f"ERROR: 不允许访问工作目录外的文件: {path}"
            if not os.path.isfile(full_path):
                return f"ERROR: 文件不存在: {path}"

            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total = len(lines)
            if start_line > 0:
                start_idx = max(0, start_line - 1)
                end_idx = min(total, end_line)
                snippet = lines[start_idx:end_idx]
                content = "".join(snippet)
                header = f"--- {path} (行 {start_line}-{end_idx}, 共 {total} 行) ---\n"
            else:
                content = "".join(lines)
                header = f"--- {path} (共 {total} 行) ---\n"

            if len(content) > 15000:
                content = content[:15000] + "\n... (输出被截断)"
            return header + content
        except Exception as e:
            return f"ERROR: 读取文件失败: {e}"


def create_view_file_tool(working_dir: str) -> Tool:
    """创建文件浏览工具（只读，无需安全审查）"""
    viewer = _ViewTool(working_dir=working_dir)
    return Tool(
        name="view_file",
        description=(
            "View the content of a file. "
            "INPUT: 'path/to/file.py' OR 'path/to/file.py:10-50' for specific lines. "
            "Only files within the working directory are accessible."
        ),
        func=viewer.view,
    )


# ============================================================
# Edit File 工具
# ============================================================

class _EditTool:
    def __init__(self, working_dir: str):
        self.working_dir = os.path.abspath(working_dir)

    def edit(self, args_str: str) -> str:
        try:
            args_str = args_str.strip().strip('"').strip("'")
            parts = args_str.split("|", 2)
            if len(parts) != 3:
                return "ERROR: 格式错误，应为: path|search_str|replace_str"
            path, search, replace = [p.strip() for p in parts]

            full_path = os.path.abspath(os.path.join(self.working_dir, path))
            if not full_path.startswith(self.working_dir):
                return f"ERROR: 不允许修改工作目录外的文件"
            if not os.path.isfile(full_path):
                return f"ERROR: 文件不存在: {path}"

            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            if search not in content:
                return f"ERROR: 未找到要替换的内容:\n{search}"

            new_content = content.replace(search, replace, 1)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"SUCCESS: 已修改 {path}"
        except Exception as e:
            return f"ERROR: 编辑失败: {e}"


def create_edit_file_tool(working_dir: str, safety_guard: SafetyGuard) -> Tool:
    """创建带安全审查的文件编辑工具"""
    editor = _EditTool(working_dir=working_dir)
    safe_edit = safety_guard.wrap_edit_tool(editor.edit)
    return Tool(
        name="edit_file",
        description=(
            "Edit a file using exact search-replace. "
            "INPUT FORMAT: 'relative_path|search_str|replace_str'. "
            "Only the first match is replaced. Run multiple times if needed. "
            "WARNING: File modifications are subject to safety review."
        ),
        func=safe_edit,
    )
