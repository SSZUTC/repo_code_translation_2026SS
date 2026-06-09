"""Pipeline test1 - 调用 ClaudeCode 处理复杂任务并保存结果

使用方法：在 claudecode 目录的上级目录执行:
    python claudecode/pipelines/test1.py

或者在 claudecode 目录下执行:
    python pipelines/test1.py

结果会以 JSON 格式保存到 claudecode/pipelines/test1_result.json
"""
import subprocess
import os
import sys
import json
import re


# ============================================================
# 任务描述 - 请在此处填写
# ============================================================
TASK_PROMPT = """
你是一位资深 Python 开发者和代码审查专家。

请分析以下代码仓库中的问题：

问题描述：astropy 的 modeling 模块中，`separability_matrix` 函数在处理嵌套的 CompoundModel 时，
无法正确计算可分离性（separability）。具体来说，当模型之间存在嵌套结构时，
inputs 和 outputs 的依赖关系被错误地标记为不可分离。

你的任务：
1. 使用 view_file 或 bash 工具查看 astropy/modeling/separable.py 的相关实现
2. 重点分析 `separability_matrix` 函数和 `_coord_matrix` 函数
3. 找出 bug 的根本原因
4. 给出修复建议的思路

最后你需要生成解决问题的patch文件，比如"diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py\n--- a/astropy/modeling/separable.py\n+++ b/astropy/modeling/separable.py\n@@ -242,7 +242,7 @@ def _cstack(left, right):\n         cright = _coord_matrix(right, 'right', noutp)\n     else:\n         cright = np.zeros((noutp, right.shape[1]))\n-        cright[-right.shape[0]:, -right.shape[1]:] = 1\n+        cright[-right.shape[0]:, -right.shape[1]:] = right\n \n     return np.hstack([cleft, cright])\n \n"
返回如下json格式的结果：
{
    "patch": "解决问题的patch",
    "problem": "问题发生的原因",
    "todo": "解决思路"
}
"""

# ============================================================
# 配置
# ============================================================
# 仓库路径（相对于当前脚本所在目录的上级目录）
REPO_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "data", "repo", "astropy"
)
# 确认模式
CONFIRM_MODE = "interactive"
# 是否启用子 Agent 委派
ENABLE_DELEGATION = True


def _fix_json_newlines(snippet: str) -> str:
    """把 JSON 字符串值内部的未转义换行符转义为 \\n。

    Agent 返回的 JSON 里 patch 字段常常包含真实的换行字符（diff 内容），
    而 json.loads 不允许字符串值中出现未转义的换行。
    这里用一个简单的状态机：识别字符串边界，把字符串内部的 \\n 进行转义。
    """
    out = []
    in_str = False
    escape_next = False
    for ch in snippet:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == '\\' and in_str:
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str and ch == '\n':
            # 字符串值内部的换行 -> 转义成 \\n
            out.append('\\n')
            continue
        if in_str and ch == '\r':
            # 跳过 \\r
            continue
        out.append(ch)
    return ''.join(out)


def extract_json(text):
    """从文本中提取 JSON 对象（容忍字符串中的换行、代码块包裹等）"""
    if not text:
        return None

    # 去掉可能包裹的代码块标记
    cleaned = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'```\s*', '', cleaned)

    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace < 0 or last_brace <= first_brace:
        return None
    candidate = cleaned[first_brace:last_brace + 1]

    # 1) 先尝试直接解析
    try:
        return json.loads(candidate)
    except Exception:
        pass

    # 2) 修复字符串值内的换行后再解析
    try:
        fixed = _fix_json_newlines(candidate)
        return json.loads(fixed)
    except Exception:
        pass

    # 3) 最后尝试让 json.JSONDecoder 自己找对象边界（更鲁棒）
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(candidate)
        return obj
    except Exception:
        return None


def run():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    claudecode_dir = os.path.dirname(script_dir)
    run_script = os.path.join(claudecode_dir, "run_claude.py")

    repo_abs = os.path.abspath(REPO_PATH)

    # ⭐ 关键改动：让 run_claude.py 直接把结构化结果写入文件，
    #    不再需要从 stdout 里解析 JSON
    result_path = os.path.join(script_dir, "test1_result.json")
    cmd = [
        sys.executable,
        run_script,
        TASK_PROMPT.strip(),
        repo_abs,
        "--confirm-mode", CONFIRM_MODE,
        "--result-json", result_path,
    ]
    if not ENABLE_DELEGATION:
        cmd.append("--disable-delegation")

    print(f"ClaudeCode Pipeline Test1")
    print(f"仓库: {repo_abs}")
    print(f"确认模式: {CONFIRM_MODE}")
    print(f"子 Agent 委派: {'启用' if ENABLE_DELEGATION else '禁用'}")
    print("=" * 80)

    result = subprocess.run(
        cmd, cwd=claudecode_dir,
        capture_output=True, text=True
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("\n[STDERR]:")
        print(result.stderr)

    # ========== 1) 保存完整调用轨迹（stdout + stderr，方便调试） ==========
    trace_path = os.path.join(script_dir, "test1_trace.json")
    trace_obj = {
        "command": " ".join([
            f"'{c}'" if " " in c else c for c in cmd
        ]),
        "working_dir": claudecode_dir,
        "return_code": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
    }
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(trace_obj, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 完整调用轨迹已保存到: {trace_path}")

    # ========== 2) 直接读取 run_claude.py 写入的结构化结果（不再从 stdout 解析） ==========
    json_obj = None
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            json_obj = json.load(f)
    except Exception as e:
        print(f"⚠️  读取 {result_path} 失败: {e}")

    if not json_obj:
        # 回退方案：从 stdout 里尝试提取
        json_obj = extract_json(result.stdout) or {
            "patch": "",
            "problem": "",
            "todo": "",
            "raw_output": result.stdout,
        }
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(json_obj, f, ensure_ascii=False, indent=2)

    print(f"✅ 结构化结果已保存到: {result_path}")
    print(json.dumps(json_obj, ensure_ascii=False, indent=2)[:1000])


if __name__ == "__main__":
    run()
