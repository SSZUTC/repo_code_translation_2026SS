"""Pipeline test1 - 调用 run_agent.py 执行代码分析任务

使用方法：
  1. 在 react/sweagent 目录下执行：python pipelines/test1.py
  2. 结果将以 JSON 格式保存到 pipelines/ 目录下
"""
import subprocess
import os
import json
import re
import sys


# ANSI 颜色码正则：\x1b[...m  \u001b[...m
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def strip_ansi(text):
    """去掉 ANSI 颜色/光标控制序列"""
    if not text:
        return text
    return _ANSI_RE.sub('', text)


TASK_PROMPT = """
你是一个pyhton程序员，你需要根据以下问题描述，先分析问题原因，再思考解决方式。你可以使用一些工具辅助完成任务，如bash,view_file，但不要修改文件内容;

"问题描述": "Add secure default SECURE_REFERRER_POLICY / Referrer-policy header\nDescription\n\t\n#29406 added the ability for the SECURE_REFERRER_POLICY setting to set Referrer-Policy, released in Django 3.0.\nI propose we change the default for this to \"same-origin\" to make Django applications leak less information to third party sites.\nThe main risk of breakage here would be linked websites breaking, if they depend on verification through the Referer header. This is a pretty fragile technique since it can be spoofed.\nDocumentation: ​https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy\nThe MDN support grid is out of date: ​https://caniuse.com/#search=Referrer-Policy\n",
"hints_text": "Hi Adam, Yes, I think this fits our secure by default philosophy. As long as the BC is documented in the release notes I think we should have this.",
    
最后你需要生成解决问题的patch文件，比如"diff --git a/django/conf/global_settings.py b/django/conf/global_settings.py\n--- a/django/conf/global_settings.py\n+++ b/django/conf/global_settings.py\n@@ -637,6 +637,6 @@ def gettext_noop(s):\n SECURE_HSTS_PRELOAD = False\n SECURE_HSTS_SECONDS = 0\n SECURE_REDIRECT_EXEMPT = []\n-SECURE_REFERRER_POLICY = None\n+SECURE_REFERRER_POLICY = 'same-origin'\n SECURE_SSL_HOST = None\n SECURE_SSL_REDIRECT = False\n"
返回如下json格式的结果：
{
    "patch": "解决问题的patch",
    "problem": "问题发生的原因",
    "todo": "解决思路"
}

"""

REPO_PATH = "../data/repo/django"


def extract_json(text):
    """从文本中提取 JSON 对象

    尝试多种方式解析：
    1. 直接在文本中查找匹配的 JSON 字典
    2. 查找 `{` 到 `}` 之间的内容（最大可能）
    3. 去掉反引号包裹的 json 代码块
    """
    if not text:
        return None

    # 去掉代码块标记
    cleaned = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'```\s*', '', cleaned)

    # 尝试找到第一个 { 到最后一个 } 的内容
    try:
        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')
        if first_brace >= 0 and last_brace > first_brace:
            candidate = cleaned[first_brace:last_brace + 1]
            return json.loads(candidate)
    except Exception:
        pass

    # 尝试逐行解析，寻找可以 parse 的 JSON
    lines = cleaned.splitlines()
    accumulated = ""
    for line in lines:
        accumulated += line + "\n"
        try:
            obj = json.loads(accumulated)
            return obj
        except Exception:
            continue

    return None


def run():
    if not TASK_PROMPT.strip():
        print("错误：请先在 TASK_PROMPT 中填写任务描述！")
        return

    # 获取路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sweagent_dir = os.path.dirname(script_dir)  # react/sweagent
    run_agent_script = os.path.join(sweagent_dir, "run_agent.py")

    # 构建命令
    cmd = [
        sys.executable,
        run_agent_script,
        TASK_PROMPT.strip(),
        REPO_PATH
    ]

    print(f"执行命令: python run_agent.py \"{TASK_PROMPT.strip()[:50]}...\" {REPO_PATH}")
    print(f"仓库路径: {os.path.abspath(os.path.join(sweagent_dir, REPO_PATH))}")
    print("=" * 80)

    # 执行 run_agent.py 并捕获输出
    result = subprocess.run(
        cmd,
        cwd=sweagent_dir,
        capture_output=True,
        text=True
    )

    # 去掉 ANSI 颜色码（\u001b[32m 这类），并合并 stdout + stderr
    clean_stdout = strip_ansi(result.stdout or "")
    clean_stderr = strip_ansi(result.stderr or "")

    # 打印输出到控制台
    if clean_stdout:
        print(clean_stdout)
    if clean_stderr:
        print(clean_stderr, file=sys.stderr)

    print("=" * 80)

    # ========== 1) 保存完整调用轨迹（stdout + stderr，方便调试，不影响 JSON 提取） ==========
    trace_path = os.path.join(script_dir, "test2_trace.json")
    trace_obj = {
        "command": " ".join([f"'{c}'" if " " in c else c for c in cmd]),
        "working_dir": sweagent_dir,
        "return_code": result.returncode,
        "stdout": clean_stdout,
        "stderr": clean_stderr,
    }
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(trace_obj, f, ensure_ascii=False, indent=2)
    print(f"✅ 完整调用轨迹已保存到: {trace_path}")

    # ========== 2) 从输出中提取 JSON 结果（先搜 stdout，再搜 stderr） ==========
    # 注意：logger 默认写 stderr，Agent 的 Thought/Action/Observation 可能在 stderr 里
    json_obj = extract_json(clean_stdout)
    if json_obj is None and clean_stderr:
        json_obj = extract_json(clean_stderr)

    if json_obj is None:
        print("警告：未能从输出中解析出 JSON，将保存完整输出为 fallback")
        json_obj = {
            "patch": "",
            "problem": "",
            "todo": "",
            "raw_stdout": clean_stdout,
            "raw_stderr": clean_stderr,
        }

    # 保存 JSON 结果到 pipelines/ 目录下
    output_path = os.path.join(script_dir, "test2_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(json_obj, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存到: {output_path}")
    print("内容:")
    print(json.dumps(json_obj, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
