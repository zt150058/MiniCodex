# MiniCodex

MiniCodex 是一个 Windows 优先、Python 编写的本地 Coding Agent。它自行实现显式 Agent 循环、上下文管理、本地工具、安全策略、验证门槛和审计日志，并通过 provider-neutral `ModelClient` 接入 OpenAI Responses API。

- [考核提交说明](README.txt)
- [安装、运行与故障排查](docs/USAGE.md)
- [OpenAI Responses API 接入说明](docs/OPENAI_API.md)

安装后运行 `coding-agent --help` 查看真实 CLI 参数。项目只允许一组受控的文件和命令操作，面向 Windows 环境，并且不是操作系统级沙箱。
