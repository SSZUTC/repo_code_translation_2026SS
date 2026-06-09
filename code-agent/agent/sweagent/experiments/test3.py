
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

"problem_statement": "MySQL backend uses deprecated \"db\" and \"passwd\" kwargs.\nDescription\n\t\nThe \"db\" and \"passwd\" usage can be seen at ​https://github.com/django/django/blob/ca9872905559026af82000e46cde6f7dedc897b6/django/db/backends/mysql/base.py#L202-L205 in main. mysqlclient recently marked these two kwargs as deprecated (see ​https://github.com/PyMySQL/mysqlclient/commit/fa25358d0f171bd8a63729c5a8d76528f4ae74e9) in favor of \"database\" and \"password\" respectively. mysqlclient added support for \"database\" and \"password\" in 1.3.8 with ​https://github.com/PyMySQL/mysqlclient/commit/66029d64060fca03f3d0b22661b1b4cf9849ef03.\nDjango 2.2, 3.1, and 3.2 all require a minimum version of mysqlclient newer than 1.3.8, so a fix for this could be backported to all currently supported versions of Django.\n",
"hints_text": "Thanks for this report. Django 2.2, 3.1, and 3.2 all require a minimum version of mysqlclient newer than 1.3.8, so a fix for this could be backported to all currently supported versions of Django. Django 2.2 and 3.1 are in extended support so they don't receive bugfixes anymore (except security patches). We'll document the maximum supported version of mysqlclient in these versions as soon as deprecated kwargs are removed. IMO we can backport this to the Django 3.2 since it's LTS.",
        
最后你需要生成解决问题的patch文件，比如"diff --git a/django/db/backends/mysql/base.py b/django/db/backends/mysql/base.py\n--- a/django/db/backends/mysql/base.py\n+++ b/django/db/backends/mysql/base.py\n@@ -200,9 +200,9 @@ def get_connection_params(self):\n         if settings_dict['USER']:\n             kwargs['user'] = settings_dict['USER']\n         if settings_dict['NAME']:\n-            kwargs['db'] = settings_dict['NAME']\n+            kwargs['database'] = settings_dict['NAME']\n         if settings_dict['PASSWORD']:\n-            kwargs['passwd'] = settings_dict['PASSWORD']\n+            kwargs['password'] = settings_dict['PASSWORD']\n         if settings_dict['HOST'].startswith('/'):\n             kwargs['unix_socket'] = settings_dict['HOST']\n         elif settings_dict['HOST']:\ndiff --git a/django/db/backends/mysql/client.py b/django/db/backends/mysql/client.py\n--- a/django/db/backends/mysql/client.py\n+++ b/django/db/backends/mysql/client.py\n@@ -8,7 +8,10 @@ class DatabaseClient(BaseDatabaseClient):\n     def settings_to_cmd_args_env(cls, settings_dict, parameters):\n         args = [cls.executable_name]\n         env = None\n-        db = settings_dict['OPTIONS'].get('db', settings_dict['NAME'])\n+        database = settings_dict['OPTIONS'].get(\n+            'database',\n+            settings_dict['OPTIONS'].get('db', settings_dict['NAME']),\n+        )\n         user = settings_dict['OPTIONS'].get('user', settings_dict['USER'])\n         password = settings_dict['OPTIONS'].get(\n             'password',\n@@ -51,7 +54,7 @@ def settings_to_cmd_args_env(cls, settings_dict, parameters):\n             args += [\"--ssl-key=%s\" % client_key]\n         if charset:\n             args += ['--default-character-set=%s' % charset]\n-        if db:\n-            args += [db]\n+        if database:\n+            args += [database]\n         args.extend(parameters)\n         return args, env\n",
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
    trace_path = os.path.join(script_dir, "test3_trace.json")
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
    output_path = os.path.join(script_dir, "test3_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(json_obj, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存到: {output_path}")
    print("内容:")
    print(json.dumps(json_obj, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
