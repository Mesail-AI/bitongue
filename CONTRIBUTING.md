# 贡献指南

[中文] **·** [English](CONTRIBUTING_en.md)

感谢关注 Bitongue！本文档说明如何搭建开发环境、项目约定，以及提交贡献的完整流程。

## 目录

[AI 协助政策](#ai-协助政策) **·** [开发环境](#开发环境) **·** [代码约定](#代码约定) **·** [贡献流程](#贡献流程) **·** [提交规范](#提交规范) **·** [测试要求](#测试要求) **·** [发布流程](#发布流程维护者) **·** [文档](#文档) **·** [行为准则](#行为准则)

## AI 协助政策

**本项目接受 AI 协助开发的代码。** 但请注意：

- 你（提交者）必须**认真审查**提交的每一行代码，无论它由你本人还是 AI 协助编写；
- AI 协助的代码与本人编写的代码**承担同等责任**——正确性、安全性、许可证合规
  均由提交者负责；
- 提交即视为你完全理解并认可该变更，"这是 AI 写的"不构成缺陷的免责理由。

## 开发环境

本项目使用 [uv](https://docs.astral.sh/uv/) 管理依赖，要求 Python ≥ 3.12，
GNU Make 驱动日常命令（Makefile 已做跨平台适配）。

```bash
git clone git@github.com:Ahsen17/bitongue.git
cd bitongue
make install    # 创建虚拟环境并安装依赖
make check      # lint + 类型检查 + 全部测试
```

常用命令：

| 命令 | 作用 |
|-|-|
| `make sync` | 同步依赖 |
| `make fix` | ruff 自动修复与格式化 |
| `make lint` | pre-commit + mypy（strict） |
| `make pyright` | pyright 类型检查 |
| `make test` | 单元测试 |
| `make test-integration` | 集成测试 |
| `make coverage` | 覆盖率报告（`fail_under = 80`） |
| `make docs-build` | 构建双语文档站 |
| `make changelog` | 由 git-cliff 再生成 CHANGELOG.md |

## 代码约定

- 一切数据结构继承 `bitongue.base.BaseStruct`（msgspec `Struct` 封装），
  不使用 dataclass 或 pydantic；
- 异步只使用 anyio 原语（`create_memory_object_stream`、`fail_after` 等），
  不直接 import asyncio；
- 泛型使用 PEP 695 语法（`class Flowing[T: Event]`）；
- 子包内文件分工固定：`schemas.py`（数据结构）、`protocols.py`（接口 Protocol）、
  `exceptions.py`（异常，均继承 `BitongueError`）；`__init__.py` 显式声明
  `__all__` 再导出；
- 代码风格由 ruff 统一约束：行宽 90、Google 风格 docstring 约定、
  规则组见 `pyproject.toml` 的 `[tool.ruff.lint]`；
- 类型检查执行 mypy strict 与 pyright 双重标准，两者都必须通过。

## 贡献流程

本项目采用 **fork & pull** 模式，请勿直接向主仓库推送分支：

1. 在 [Issues](https://github.com/Ahsen17/bitongue/issues) 中认领或提出问题；
2. 在 GitHub 上 fork `Ahsen17/bitongue`，克隆你的 fork 并从 `main`
   创建特性分支，如 `feat/flowing-metrics`、`fix/expiry-drift`、`docs/quickstart`；
3. 开发并补充测试（见下方[测试要求](#测试要求)）；涉及用户可见改动时，
   同步更新 README（中文 / English）与 `docs/`（中文）、`docs/en/`（英文）两份文档站；
4. 确保本地 `make check` 通过；
5. 推送分支到你的 fork，提交 Pull Request 到 `Ahsen17/bitongue` 的 `main`；
6. PR 描述请说明：改了什么、为什么改、如何验证。CI（`pytest.yml`）必须全绿。

## 提交规范

提交信息遵循
[Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```
<类型>(<范围>?): <描述>

<正文?>

<脚注?>
```

常用类型：`feat`、`fix`、`refactor`、`doc`、`perf`、`style`、`test`、`build`、
`chore`、`revert`。commit-msg 钩子会强制校验格式。

CHANGELOG.md 由 [git-cliff](https://git-cliff.org) 依据提交历史自动生成
（`make changelog`），**原则上禁止手动编辑**。

## 测试要求

- 测试目录镜像源码结构：`src/bitongue/flow/flowing.py` → `tests/flow/test_flowing.py`；
- 一个测试文件只测一个模块；
- 通用 fixture 位于 `tests/conftest.py`，子模块 fixture 位于对应子树的
  `conftest.py`；
- 用例统一组织为 `class TestXX`；
- pytest 为 asyncio auto 模式，测试直接写 `async def`；
- 外部依赖策略：单测使用 fakexx（如 fakeredis），无 fakexx 包的依赖用 async
  mock；集成测试（`test_integration/`，标记 `integration`）使用真实服务；
- 集成测试连接 qdrant 时，通过环境变量 `BITONGUE_TEST_QDRANT_URL`（完整 URL）
  或 `BITONGUE_TEST_QDRANT_HOST` / `BITONGUE_TEST_QDRANT_PORT`（默认
  `localhost:6333`）指定目标；服务不可达时用例自动 skip 而非失败；
- 新增功能必须附带测试，覆盖率不得低于 80%。

## 发布流程（维护者）

版本号遵循 [SemVer 2.0.0](https://semver.org/lang/zh-Hans/)，tag 一律带 `v` 前缀：

- **正式版本**：`x.y.z`，如 `v1.2.0`；
- **非正式版本（beta）**：`x.y.z-beta.N`，如 `v1.2.0-beta.1`；`N` 从 1 开始，
  在同一 `x.y.z` 序列内顺延。

发布时序：

1. 在 pyproject 中更新 `version`，提交
   `chore(release): prepare for vX.Y.Z` 并合入 `main`
   （git-cliff 会跳过该提交，不进 CHANGELOG）；
2. 在 main 上打 tag 并推送：`git tag vX.Y.Z && git push origin vX.Y.Z`；
3. `release.yml` 自动创建 **draft** release，附带该版本 notes（git-cliff 生成）
   与 sdist/wheel 产物；
4. 在本地运行 `make changelog` 再生成 CHANGELOG.md（须在 tag 存在之后运行，
   新版本段落才会出现），以 `doc: update changelog for vX.Y.Z` 提交合入；
5. 在 GitHub Releases 页面人工调整 draft（标记 pre-release 或正式）后 Publish。

## 文档

- 文档站构建：`make docs-build`；本地热重载预览：`make docs-serve`
  （同时监视 `src/` 与 `docs/` 变更）；
- 文档为 Sphinx 双语站：`docs/` 为简体中文主站，`docs/en/` 为英文镜像站，
  两站页面文件名一一对应（主题语言切换器依赖该映射）；
- 修改任何面向用户的行为时，请同步更新 README（中文 / English）与文档站对应页面。

## 行为准则

保持尊重与专业。对事不对人，欢迎新人提问。

## License

提交即表示你同意以 [AGPL-3.0](LICENSE) 许可授权你的贡献。
