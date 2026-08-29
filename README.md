# MiniCodex

MiniCodex 是一个 Windows 优先、Python 编写的本地 Coding Agent。它自行实现显式 Agent 循环、上下文管理、本地工具、安全策略、验证门槛和审计日志，并通过 provider-neutral `ModelClient` 接入默认的 OpenAI Responses API 或显式配置的 compatible Chat Completions endpoint。

- [考核提交说明](README.txt)
- [安装、运行与故障排查](docs/USAGE.md)
- [Responses 与 compatible Chat Completions 接入说明](docs/OPENAI_API.md)

安装后运行 `coding-agent --help` 查看真实 CLI 参数。`--api-mode` 默认是 `responses`；选择 `chat-completions` 时必须显式提供 HTTPS `--base-url`。可配置 URL 不代表兼容所有服务，目标 endpoint 必须支持标准函数工具调用与 `tool_call_id` 配对。项目只允许一组受控的文件和命令操作，并且不是操作系统级沙箱。
