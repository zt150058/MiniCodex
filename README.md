# MiniCodex

MiniCodex 是一个 Windows 优先、Python 编写的本地 Coding Agent。它自行实现显式 Agent 循环、上下文管理、本地工具、安全策略、验证门槛和审计日志，并通过 provider-neutral `ModelClient` 接入默认的 OpenAI Responses API 或显式配置的 compatible Chat Completions endpoint。

- [考核提交说明](README.txt)
- [安装、运行与故障排查](docs/USAGE.md)
- [Responses 与 compatible Chat Completions 接入说明](docs/OPENAI_API.md)

安装后运行 `coding-agent --help` 查看一次性 CLI，或运行 `coding-agent-web --workspace <path>` 打开本地 Web GUI。GUI 只绑定 `127.0.0.1` 的随机端口，以进程内 Bearer token、Host/Origin 校验保护 REST/SSE，可查看持久会话、提交 follow-up、选择声明式 Skill 和请求取消；一次只运行一个 Agent。

`--api-mode` 默认是 `responses`；选择 `chat-completions` 时必须显式提供 HTTPS `--base-url`。可配置 URL 不代表兼容所有服务，目标 endpoint 必须支持标准函数工具调用与 `tool_call_id` 配对。项目只允许一组受控的文件和命令操作，并且不是操作系统级沙箱。

除 Python 验证外，MiniCodex 还提供专用 `run_java_tests`：它使用可信本机 JDK 编译工作区 Java 源码，并按稳定顺序执行成对的 `.in`/`.out` 标准输入输出 fixture。只有 `purpose="verification"`、结果完整通过且证据对应最后一次修改时，才可满足未指定 `--verify` 的验证门。Java 命令字符串仍不能通过 `run_command` 执行；该能力不支持 Maven、Gradle 或 JUnit，也不是操作系统级沙箱。
