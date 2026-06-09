# code-agent —— sweagent & claudeCode


## 目录结构

```
code-agent/                     # 项目根目录
├── demo.py                     # 最小可运行Demo（用于测试执行环境与 API 是否有效）
├── requirements.txt            # 依赖
├── requirements_old.txt        # 历史依赖（备份）
├── agent/
│   ├── sweagent/               # sweagent
│   │   ├── run_agent.py        # 入口脚本：python run_agent.py "任务" /path/to/repo
│   │   ├── llm/
│   │   │   ├── config.py       # LLM 配置（API Key / 模型 / base_url）
│   │   │   ├── agent.py        # Agent 本体（构建 tools / prompt / executor）
│   │   │   └── callbacks.py    # 运行过程回调（日志 / trace）
│   │   ├── tools/              # 工具集，可自由拓展
│   │   │   ├── bash_tool.py    # bash_execute 工具
│   │   │   ├── edit_tool.py    # edit_file 工具
│   │   │   └── view_tool.py    # view_file 工具
│   │   ├── utils/
│   │   │   └── logger.py       # 日志记录
│   │   ├── experiments/        # 测试 / 实验脚本
│   │   │   ├── test1.py        # swebench_verified 第 1 条（astropy__astropy-12907）
│   │   │   ├── test2.py        # django__django-12419（网络安全题）
│   │   │   └── test3.py        # django__django-14376（三方包过时题）
│   │   └── output/             # 参考输出
│   │       ├── test1_result.json / test1_trace.json  #结果与轨迹文件
│   │       ├── test2_result.json / test2_trace.json
│   │       └── test3_result.json / test3_trace.json
│   └── claudecode/             # claude code
│       ├── run_claude.py       # 入口脚本：python run_claude.py "任务" /path/to/repo
│       ├── llm/
│       │   ├── config.py       # LLM 配置
│       │   └── agent.py        # Agent 本体（含安全审查 / delegation）
│       ├── safety/
│       │   └── guard.py        # 高风险命令审查、交互式确认
│       ├── delegation/
│       │   └── manager.py      # 子 Agent 委派（code_analysis / test_executor 等）
│       ├── tools/
│       │   └── factory.py      # 工具工厂（为子 Agent 打包精简工具集）
│       ├── utils/
│       │   └── logger.py
│       ├── experiments/        # 同 sweagent/experiments/
│       │   ├── test1.py
│       │   ├── test2.py
│       │   └── test3.py
│       └── output/             # 参考输出
│           ├── test1_result.json / test1_trace.json    #结果与轨迹文件
│           ├── test2_result.json / test2_trace.json
│           └── test3_result.json / test3_trace.json
└── dataset/                    # SWE-Bench 风格的测试数据与待测仓库
    ├── swebench_verified.json  # 测试集（SWE-Bench 格式，每条一个 instance_id）
    ├── case_description.txt    # 两条重点案例的人工描述（网络安全 + 三方包过时）
    └── repo/
        ├── github_repo_location.txt  # 仓库来源地址清单
        ├── astropy/            # astropy 源码（需 git checkout 到对应 base_commit）
        └── django/             # django 源码（需 git checkout 到对应 base_commit）
```

## 环境要求

- **Python 3.10.19**（不建议 Python 3.11+，部分底层依赖在新版上需本地编译，易踩 pydantic-core 的 Rust 工具链坑）
- 可用的 OpenAI-compatible API Key（默认使用 [OpenRouter](https://openrouter.ai/)，`base_url = https://openrouter.ai/api/v1`）

## 一、安装依赖

```bash
cd code-agent
python -m venv venv               #创建虚拟环境，或者自行使用现有环境
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## 二、先跑一个最小 Demo：demo.py

`demo.py` 不依赖任何 sweagent / claudecode 模块，可用来快速验证环境与 API Key 是否正常。

1. 打开 `demo.py`，在第 4 节 **模型** 里填入 API Key：

   ```python
   llm = ChatOpenAI(
       model="openai/gpt-4o",
       api_key="你的 API Key（sk-or-v1-...）",
       base_url="https://openrouter.ai/api/v1",
       temperature=0
   )
   ```

2. 直接运行：

   ```bash
   python demo.py
   ```

   看到 Agent 打印出 `Thought / Action / Observation / Final Answer` 的完整链就说明环境没问题。

## 三、运行 sweagent / claudeCode 主 Agent

1. **配置 API Key**

   - `agent/sweagent/llm/config.py` —— 修改 `DEFAULT_LLM_CONFIG.api_key`
   - `agent/claudecode/llm/config.py` —— 修改 `DEFAULT_LLM_CONFIG.api_key`

   或者也可以用环境变量：

   ```bash
   export OPENAI_API_KEY="sk-or-v1-..."
   ```

2. **执行一条命令测试 Agent 是否正常**

   以列出某个仓库下所有 Python 文件为例：

   **sweagent：**

   ```bash
   cd agent/sweagent
   python run_agent.py "列出所有 Python 文件" /path/to/repo

   # 例如：
   python run_agent.py "列出当前目录下所有 Python 文件" ../../dataset/repo/django
   ```

   **claudeCode：**

   ```bash
   cd agent/claudecode
   python run_claude.py "列出所有 Python 文件" /path/to/repo

   # 带参数的高级用法：
   python run_claude.py "做一些可能有风险的操作" ../../dataset/repo/django --confirm-mode auto_deny
   python run_claude.py "复杂分析任务" ../../dataset/repo/astropy --disable-delegation
   ```

   正常情况下会看到：

   - 启动信息（INFO 日志）
   - Agent 的 Thought / Action / Observation 步骤
   - 最终的 Final Answer
   - claudeCode 额外会打印安全审查摘要、子 Agent 委派摘要

## 四、测试案例

所有测试案例的数据放在 `dataset/swebench_verified.json`（SWE-Bench 格式）。两条重点案例的背景描述可在 `dataset/case_description.txt` 中查看。

### 4.1 准备仓库

先确保 `dataset/repo/` 下有 astropy 与 django 两个仓库。如果没有，可按 `dataset/repo/github_repo_location.txt` 里的地址自行 `git clone`：

```bash
cd dataset/repo
git clone https://github.com/astropy/astropy.git
git clone https://github.com/django/django.git
```

### 4.2 按 instance_id 找到对应记录

在 `dataset/swebench_verified.json` 中，用你编辑器的 **Ctrl+F** 搜索 `instance_id` 的值，可快速定位到具体条目，拿到：

- `problem_statement` —— 题目描述
- `base_commit` —— 需要切到的 SHA
- `patch` —— 官方参考修复（用于对比你的 Agent 结果）

### 4.3 切换到指定 commit

**测试前务必先 checkout 到对应 commit，确保 Agent 看到的代码是问题发生时的状态。**

```bash
# 例如切到 astropy 第 1 条测试案例的 base_commit
cd dataset/repo/astropy
git checkout astropy__astropy-12907 对应的 SHA

# 例如切到 django__django-12419（Referrer Policy 安全题）
cd ../django
git checkout 7fa1a93c6c8109010a6ff3f604fda83b604e0e97

# 切换到 django__django-14376（三方包过时题）
git checkout d06c5b358149c02a62da8a5469264d05f29ac659
```

> 如果本地因为已应用过旧 patch 导致 checkout 报错，先执行 `git checkout -- .` 丢弃所有未提交的改动。

### 4.4 运行 experiments

每条题目都有一个对应的实验脚本，放在 `agent/sweagent/experiments/` 与 `agent/claudecode/experiments/` 下：

| 脚本 | 对应 instance_id | 题目类型 | 仓库 |
|------|------------------|---------|------|
| `test1.py` | SWE-Bench 第 1 条（`astropy__astropy-12907`） | 嵌套 CompoundModel 的 separability_matrix 问题 | astropy |
| `test2.py` | `django__django-12419` | **网络安全缺陷** —— `SECURE_REFERRER_POLICY` 默认值缺失导致 Referer 信息泄漏 | django |
| `test3.py` | `django__django-14376` | **三方包版本问题** —— MySQL `db`/`passwd` 已弃用，需切换到 `database`/`password` | django |

运行方式（以 sweagent 为例，claudecode 同理）：

```bash
cd agent/sweagent
python experiments/test1.py    # 运行第 1 条
python experiments/test2.py    # 运行网络安全题
python experiments/test3.py    # 运行三方包问题

# 或
cd agent/claudecode
python experiments/test1.py
python experiments/test2.py
python experiments/test3.py
```

每次运行会在各自的 `output/` 目录下产生两份文件（自动生成，**不需要手动创建**）：

- `testN_result.json` —— Agent 提取出的结构化结果
  - `patch` —— 生成的修复补丁
  - `problem` —— 问题归因
  - `todo` —— 解决思路
- `testN_trace.json` —— 完整调用轨迹（stdout / stderr / 中间步骤）

## 五、如何判定结果正确

1. 直接查看 `output/testN_result.json` 中的 `patch` 字段，与 `dataset/swebench_verified.json` 中对应条目的 `patch` 字段对比。
2. 用 `git apply` 应用 Agent 的 patch 到对应 commit 的干净仓库，再跑该仓库自带的测试（例如 Django 的 `runtests.py` 或 astropy 的 `pytest`）。
3. `output/testN_trace.json` 可帮你排查 Agent 是否在中间步骤走偏（比如工具调用失败、格式错误等）。

## 六、常见问题

- **`ModuleNotFoundError: No module named 'langchain'`** —— 没激活 venv 或没 `pip install -r requirements.txt`。
- **`OpenAIError: The api_key client option must be set`** —— `llm/config.py` 中的 api_key 没填，或环境变量 `OPENAI_API_KEY` 为空。
- **`ValueError: Prompt missing required variables: {'tool_names'}`** —— Prompt 模板变量不完整，通常是把 prompt 错写成了 f-string。应使用普通字符串，并让 LangChain 自行注入 `{tools}` / `{tool_names}` / `{input}` / `{agent_scratchpad}`。
- **`attempted relative import beyond top-level package`** —— 直接 `python some/deep/script.py` 运行子模块导致的 import 错。请从仓库根目录运行入口脚本（`run_agent.py` / `run_claude.py` 或 `experiments/test*.py`）。
- **git checkout 失败** —— 可能是之前 Agent 应用过 patch 但没回滚，先 `git checkout -- .` 清一下。
- **claudeCode 的 trace 里出现 `Invalid Format: Missing 'Action:' after 'Thought:'`** —— Agent 在最后输出完整答案时偶尔会直接写报告而不遵守 ReAct 格式。通常不影响最终 `patch` 结果的正确性，仅中间步骤记录不完整。
- **output 目录里的文件是从哪儿来的？** —— 由 `experiments/test*.py` 在运行结束后直接写入，路径相对于各 Agent 自己的 `output/` 目录。
