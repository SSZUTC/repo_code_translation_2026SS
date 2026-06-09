# 数据集说明

本目录保存 repo-level code translation pipeline 的课程演示数据集。数据集按源项目语言组织：

```text
datasets/
  java-projects/       # Java 源项目，用于 Java -> Python
  python-projects/     # Python 源项目，用于 Python -> Java
```

每个项目都是一个可独立分析、规划、翻译和验证的源仓库。生成结果统一写到：

```text
results/<direction>/<project-name>/
  analysis/            # 源项目静态 AST、File Tree、LLM 语义分析
  plans/               # 目标项目总体规划、AST skeleton、空骨架项目
  translated/          # 生成后的目标项目
  logs/                # 进度日志、retrieval 日志、refine 日志
  validation/          # 编译/测试验证报告
```

## Java 源项目

### `java-projects/java-string-similarity`

源项目是 Java 字符串相似度算法库，目标是迁移为 Python 算法库。

包含：

- Maven 项目结构
- 多个独立算法类，例如 Levenshtein、Jaro-Winkler、NGram、Cosine、Jaccard
- 接口和抽象基类
- 单元测试与 public tests
- 纯算法逻辑，外部依赖较少

适合展示：

- Java 类和接口到 Python module/class/function 的结构规划
- AST/File Tree 分析
- 目标 Python 项目规划与 `python_project_sketeon.json`
- 逐文件翻译和测试验证

运行示例：

```bash
venv/bin/python translate_repo.py \
  --direction java-python \
  --source datasets/java-projects/java-string-similarity \
  --results-root results/java-python/java-string-similarity \
  --model gpt-4o \
  run
```

### `java-projects/chat-room`

Java -> Python 的 Web/服务端案例。源项目来自一对一聊天 Spring Boot WebSocket 项目，复杂度高于算法库。

包含：

- Spring Boot / Maven 项目
- WebSocket 聊天业务
- Controller / Service / Repository 风格代码
- 配置文件、Docker Compose、图片和说明文档
- 数据持久化相关接口

适合展示：

- Java Web 项目结构分析
- 服务端业务代码迁移规划
- 配置和资源文件在 repo-level 翻译中的处理

注意：

- 该项目比 `java-string-similarity` 更接近真实 Web 项目，但依赖和运行环境也更复杂。

运行示例：

```bash
venv/bin/python translate_repo.py \
  --direction java-python \
  --source datasets/java-projects/chat-room \
  --results-root results/java-python/chat-room \
  --model gpt-4o \
  run
```

## Python 源项目

### `python-projects/wroberts_pytimeparse`

源项目是时间表达式解析库，目标是迁移为 Java/Maven 项目。

包含：

- 单核心模块 `pytimeparse/timeparse.py`
- setup.py 项目元数据
- 基础测试和 public tests
- 规则解析、字符串处理、数值转换逻辑

适合展示：

- Python 动态函数到 Java class/static method 的迁移
- Python 项目语义分析
- Java 项目规划与 `java_project_sketeon.json`
- Maven 测试验证和 refine 闭环

运行示例：

```bash
venv/bin/python translate_repo.py \
  --direction python-java \
  --source datasets/python-projects/wroberts_pytimeparse \
  --results-root results/python-java/wroberts_pytimeparse \
  --model gpt-4o \
  run
```

### `python-projects/seatgeek_fuzzywuzzy`

Python -> Java 的中等复杂度算法库案例。

包含：

- `fuzz.py`：字符串相似度核心逻辑
- `process.py`：候选项提取与排序逻辑
- `string_processing.py` / `utils.py`：字符串预处理和工具函数
- pytest 测试与 public tests

适合展示：

- 多 Python module 到多 Java class 的规划
- 跨文件 import/retrieval 对翻译质量的影响
- Python 函数签名、可选参数、回调逻辑迁移到 Java 的难点
- refine 如何根据 Maven 编译/测试错误选择修复文件

注意：

- 该项目比 `wroberts_pytimeparse` 更复杂，Python -> Java 更容易出现方法签名不一致、测试期望不一致等问题。
- 适合作为课堂中“为什么 repo-level translation 需要 plan、retrieval、validation、refine”的展示案例。

运行示例：

```bash
venv/bin/python translate_repo.py \
  --direction python-java \
  --source datasets/python-projects/seatgeek_fuzzywuzzy \
  --results-root results/python-java/seatgeek_fuzzywuzzy \
  --model gpt-4o \
  run
```
