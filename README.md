# MiniCodex

## 项目简介

MiniCodex 是一个面向 Windows、使用 Python 从零实现的本地 Coding Agent。项目不依赖 Agent 框架，核心循环、上下文管理、工具调用、安全校验、修改后验证、会话持久化和审计均在本地完成；模型接入支持 OpenAI Responses API 与显式配置的 compatible Chat Completions endpoint。

## 仓库结构

```text
MiniCodex/
├─ .github/workflows/        GitHub Actions 持续集成
├─ docs/
│  ├─ project/               项目设计、任务与原始需求
│  └─ superpowers/           已批准的设计规格和实施计划
├─ examples/                 离线示例工作区
├─ pyproject.toml            Python 打包、依赖与命令入口配置
├─ src/coding_agent/
│  ├─ application/           应用装配与命令行入口
│  ├─ engine/                Agent 核心执行引擎
│  ├─ providers/             模型服务适配层
│  ├─ operations/            安全策略与本地工具
│  ├─ sessions/              会话与运行生命周期
│  ├─ skills/                声明式 Skill 管理
│  └─ web/                   本地 Web 服务与静态界面
└─ tests/
   ├─ application/           应用与文档合同测试
   ├─ engine/                核心引擎单元测试
   ├─ providers/             模型适配测试
   ├─ operations/            安全策略与工具测试
   ├─ sessions/              会话生命周期测试
   ├─ skills/                Skill 管理测试
   ├─ web/                   Web 服务测试
   ├─ integration/           跨模块集成回归
   ├─ js/                    浏览器逻辑测试
   └─ manual/                人工验证夹具
```

## 目录职责

| 目录 | 职责 |
| --- | --- |
| `src/coding_agent/application/` | 解析运行参数、装配配置并提供 CLI 应用入口。 |
| `src/coding_agent/engine/` | 实现显式同步 Agent 循环、消息状态、上下文、预算、收敛、验证、日志和最终报告。 |
| `src/coding_agent/providers/` | 隔离模型供应商协议，负责 Responses 与 compatible Chat Completions 的数据转换。 |
| `src/coding_agent/operations/` | 实现工作区边界、命令限制以及文件、Shell、Java 等受控本地操作。 |
| `src/coding_agent/sessions/` | 管理持久会话、运行控制、事件投影、删除与启动恢复。 |
| `src/coding_agent/skills/` | 读取、校验和导入不可执行的声明式 Skill，不扩展工具权限。 |
| `src/coding_agent/web/` | 提供仅面向本机的 Web API、认证、启动入口与前端静态资源。 |
| `tests/` | 按生产职责组织单元测试，并集中放置集成、JavaScript 和人工验证内容。 |
| `docs/` | 保存详细使用说明、API 接入说明、项目设计、任务记录与实施资料。 |
| `examples/` | 保存可离线运行的演示工作区，便于验证典型修复流程。 |
| `.github/workflows/` | 定义 push 和 pull request 触发的 Windows 自动测试与打包检查。 |

## 详细文档

- [安装、运行与安全边界](docs/USAGE.md)
- [模型 API 接入说明](docs/OPENAI_API.md)
- [项目设计](docs/project/DESIGN.md)
- [开发任务与验收记录](docs/project/TASKS.md)
