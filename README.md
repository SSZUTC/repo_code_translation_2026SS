# Repo 级代码翻译 Pipeline

这是一个课程演示用的 repo-level code translation 项目。它模拟了真实代码迁移时需要的完整工程链路：

```text
分析源仓库 -> 生成项目规划 -> 逐文件生成 -> 编译/测试验证 -> 根据错误修复
```

当前支持两个方向：

- Java -> Python
- Python -> Java

项目入口是 `translate_repo.py`，核心实现位于 `src/`。

## 设计目标

这个项目解决的问题是：当一个仓库有多层目录、模型、服务、数据库、测试和 UI 资源时，不能直接把每个文件孤立丢给 LLM。真实迁移至少需要四类信息：

- 源项目结构：有哪些包、类、函数、测试、资源、构建文件。
- 目标项目结构：迁移后应该有哪些目标文件、模块和分层。
- 文件级上下文：生成某个目标文件时，需要参考哪些源文件和已生成目标文件。
- 验证反馈：生成后必须通过编译、单测；失败时要根据错误定位要修的文件。

## 环境

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

默认读取当前目录下的 `.env`, 需要配置一下信息：


```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
JAVA_PATH=xxx
JAVA_HOME=xxx
```

说明：

- `OPENAI_API_KEY` / `OPENAI_BASE_URL` 用于 OpenAI-compatible LLM 调用。
- `JAVA_PATH` / `JAVA_HOME` 用于 Python -> Java 方向的 Maven 编译和测试。
- java 版本 推荐 jdk-11
- **Python 3.10.19**（不建议 Python 3.11+，部分底层依赖在新版上需本地编译）
- 可用的 OpenAI-compatible API Key（默认使用 [OpenRouter](https://openrouter.ai/)，`base_url = https://openrouter.ai/api/v1`）

## 数据集

数据集位于 `datasets/`，详细说明见：

```text
datasets/README.md
```

目录按源项目语言组织：

```text
datasets/
  java-projects/       # Java 源项目，用于 Java -> Python
    chat-room/
    java-string-similarity/
  python-projects/     # Python 源项目，用于 Python -> Java
    seatgeek_fuzzywuzzy/
    wroberts_pytimeparse/
```

每个项目目录本身就是源仓库，命令中的 `--source` 直接指向项目目录：

```text
datasets/<source-language-projects>/<project-name>/
```


## Pipeline 流程

### 1. Analyze：分析源仓库

职责：

- 扫描源项目文件。
- 识别源码、测试、资源、构建文件。
- Java 方向使用 `tree-sitter-language-pack` 解析 Java CST，并提取 package、import、type、field、constructor、method、annotation 等 AST 摘要。
- 生成项目 File Tree，用于描述源仓库目录和文件类别。
- Java 方向会把 File Tree 和每个 Java 文件的 class framework 交给 LLM，生成项目动态语义分析报告。
- Python 方向使用标准库 `ast` 提取函数、类和 import 信息。
- 推断项目框架，例如 Maven、Spring、Flask、SQLAlchemy、pytest。

对应代码：

```text
src/analysis/java_analyzer.py
src/analysis/python_analyzer.py
src/common/models.py
```

示例：

```bash
python translate_repo.py \
  --direction java-python \
  --source datasets/java-projects/taskflow-board-python \
  --results-root results/java-python/taskflow-board-python \
  analyze
```

Python -> Java 时修改方向参数：

```bash
python translate_repo.py \
  --direction python-java \
  --source datasets/python-projects/taskflow-board-java \
  --results-root results/python-java/taskflow-board-java \
  analyze
```


输出：

```text
results/<direction>/<project>/analysis/python_analysis.json
results/<direction>/<project>/analysis/ast_tree.json
results/<direction>/<project>/analysis/file_tree.json
results/<direction>/<project>/analysis/project_semantics.md
```

### 2. Plan：生成项目规划

职责：

- 根据源项目分析结果规划目标语言项目结构。
- 生成目标文件列表。
- 为每个目标文件建立初始任务：目标路径、角色、参考源文件、预期符号、说明、计划导出的 class/function、计划 import 的包和模块。
- 细化每个目标文件的实现契约、依赖关系和 retrieval query。
- 创建目标项目基础文件，例如 `pom.xml`、`requirements.txt`、包目录等。
- Java -> Python 方向会把动态语义分析、源文件树和 Java class framework 交给 LLM，生成 Python 3.10 项目总体规划，包括架构设计、目录模块、Python 文件树和 requirements。

对应代码：

```text
src/planning/planner.py
src/planning/python_to_java.py
src/planning/__init__.py
src/pipeline/repo_translator.py
src/pipeline/python_to_java_translator.py
src/common/run_logger.py
```

输出：

```text
results/<direction>/<project>/plans/<target>_project_sketeon.json
results/<direction>/<project>/plans/<target>_project_plan.json
results/<direction>/<project>/translated/
```

示例：

```bash
python translate_repo.py \
  --direction java-python \
  --source datasets/java-projects/taskflow-board-python \
  --results-root results/java-python/taskflow-board-python \
  plan
```

项目规划默认会调用 LLM 做目标架构优化；确定性规则只作为初始草案和兜底结构。

规划细化结果会写入：

```text
results/<direction>/<project>/plans/<target>_project_sketeon.json
```

日志中会看到类似：

```text
[plan:detail] 细化 Java 文件规划 src/main/java/...
```

### 3. Translate：逐文件生成

职责：

- 按 translation plan 逐个处理目标文件。
- 根据 refined plan 中的 query 和参考文件列表，检索相关源文件。
- 同时检索已生成的目标文件，避免生成代码和已有结构冲突。
- 对资源文件，例如 CSS、JS、HTML，直接复制或轻量适配。
- 对源码文件，构造 prompt，注入源上下文、目标上下文和文件级契约。
- 调用 LLM 生成具体实现。
- 保存生成结果到 `translated/`。

对应代码：

```text
src/pipeline/java_to_python_pipeline.py
src/pipeline/python_to_java_pipeline.py
src/prompts/java_to_python_translation.py
src/prompts/python_to_java_translation.py
src/common/llm_client.py
src/common/retriever.py
src/common/io_utils.py
```

输出：

```text
results/<direction>/<project>/translated/
results/<direction>/<project>/plans/<target>_project_sketeon.json
results/<direction>/<project>/logs/retrieval/*.json
results/<direction>/<project>/logs/progress.log
results/<direction>/<project>/logs/events.jsonl
```

示例：

```bash
python translate_repo.py \
  --direction java-python \
  --source datasets/java-projects/taskflow-board-python \
  --results-root results/java-python/taskflow-board-python \
  --model gpt-5.5 \
  translate
```

Python -> Java 示例：

```bash
python translate_repo.py \
  --direction python-java \
  --source datasets/python-projects/taskflow-board-java \
  --results-root results/python-java/taskflow-board-java \
  --model gpt-5.5 \
  translate
```

### 4. Validate：编译/测试验证

职责：

- Java -> Python：运行 Python 编译和 pytest。
- Python -> Java：运行 Maven 测试。
- 保存每条验证命令的 stdout、stderr、return code。

对应代码：

```text
src/validation/validator.py
```

输出：

```text
results/<direction>/<project>/validation/validation_report.json
```

示例：

```bash
python translate_repo.py \
  --direction java-python \
  --source datasets/java-projects/taskflow-board-python \
  --results-root results/java-python/taskflow-board-python \
  validate
```

Python -> Java：

```bash
python translate_repo.py \
  --direction python-java \
  --source datasets/python-projects/taskflow-board-java \
  --results-root results/python-java/taskflow-board-java \
  validate
```

### 5. Refine：根据错误修复

职责：

- 如果验证失败，解析编译/测试错误。
- 定位最可能需要修复的目标文件。
- 为每个失败文件重新检索源上下文和目标上下文。
- 把错误信息、当前文件内容、参考源文件一起交给 LLM。
- 覆盖对应目标文件后重新验证。

对应代码：

```text
src/refinement/validation_refiner.py
src/pipeline/repo_translator.py
src/pipeline/python_to_java_translator.py
src/prompts/java_to_python_refine.py
src/prompts/python_to_java_refine.py
```

输出：

```text
results/<direction>/<project>/logs/refine/*.json
results/<direction>/<project>/validation/validation_report.json
```

示例：

```bash
python translate_repo.py \
  --direction java-python \
  --source datasets/java-projects/taskflow-board-python \
  --results-root results/java-python/taskflow-board-python \
  --model gpt-5.5 \
  --refine-iterations 5 \
  refine
```

## 一次性运行完整流程

`run` 命令会执行：

```text
分析源仓库 -> 生成项目规划 -> 逐文件生成 -> 编译/测试验证 -> 根据错误修复（验证失败时触发）
```

Java -> Python：

```bash
python translate_repo.py \
  --direction java-python \
  --source datasets/java-projects/taskflow-board-python \
  --results-root results/java-python/taskflow-board-python \
  --model gpt-5.5 \
  --refine-iterations 5 \
  run
```

Python -> Java：

```bash
python translate_repo.py \
  --direction python-java \
  --source datasets/python-projects/taskflow-board-java \
  --results-root results/python-java/taskflow-board-java \
  --model gpt-5.5 \
  --refine-iterations 5 \
  run
```

## 输出目录

使用 `--results-root` 后，所有中间结果、日志和最终项目都会写到该目录下：

```text
results/<direction>/<project-name>/
  translated/                  # 生成的目标项目
  analysis/                    # 源项目分析结果
  plans/                       # 项目规划 prompt、LLM 总体规划、统一执行规划
  logs/                        # 运行日志、retrieval 日志、refine 日志
  validation/                  # 验证报告
  RUN_SUMMARY.md               # 单次运行总结，可选
```

关键文件：

- `analysis/python_analysis.json`：完整 Python 静态分析结果。
- `analysis/ast_tree.json`：Java 文件的 tree-sitter AST/CST 摘要。
- `analysis/file_tree.json`：源仓库 File Tree。
- `analysis/project_semantics.md`：LLM 基于 File Tree 和 Java class framework 生成的项目语义分析报告。
- `plans/python_project_plan.json` / `plans/java_project_plan.json`：LLM 生成的目标项目总体规划，包含架构设计、目录模块、文件树和依赖配置。
- `plans/python_project_sketeon.json` / `plans/java_project_sketeon.json`：目标项目的 AST 级文件骨架。Python 方向记录 Module、imports、exports、ClassDef、FunctionDef；Java 方向记录 CompilationUnit、package、imports、class/interface/enum。
- `plans/sketelon/`：由 AST 骨架展开出来的空目标项目，包含 import、空 class/function 或 Java package/class 占位。
- `logs/progress.log`：面向课堂展示的人类可读进度日志。
- `logs/events.jsonl`：结构化事件日志。
- `logs/retrieval/*.json`：每个目标文件使用的检索上下文。
- `logs/refine/*.json`：每次修复使用的错误和上下文。
- `validation/validation_report.json`：编译/测试验证结果。

## 代码结构

```text
translate_repo.py               # CLI 入口，解析命令并选择翻译方向
src/
  analysis/                     # Java/Python 源仓库分析
  common/                       # 数据模型、LLM client、检索、文件读写、日志工具
  planning/                     # 目标架构规划、目标文件计划、细化文件规划
  prompts/                      # 翻译、Judge、Refine prompt 模板
  validation/                   # Python/Java 编译和测试验证
  refinement/                   # 验证失败分析和修复目标选择
  pipeline/                     # Java->Python 与 Python->Java 流程编排
datasets/                       # 演示数据集
results/                        # 运行结果和中间产物
```

核心编排类：

- `src/pipeline/repo_translator.py`：Java -> Python。
- `src/pipeline/python_to_java_translator.py`：Python -> Java。
