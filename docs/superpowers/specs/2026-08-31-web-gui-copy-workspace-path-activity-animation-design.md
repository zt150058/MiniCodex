# Web GUI 代码复制、工作区路径与活动动画设计

**日期：** 2026-08-31  
**状态：** 已批准  
**范围：** 本地 Web GUI 展示层与首页 bootstrap；不改变 Agent、Session、工具、模型、预算或权限语义。

## 1. 目标

在不增加依赖、不引入不安全 HTML sink、也不伪造运行进度的前提下，完成四项紧凑 GUI 改造：

1. 为 MiniCodex 回复中的 fenced Markdown 代码块提供便捷复制按钮。
2. 移除顶部运行阶段中的模型、摘要、provider 请求和工具调用计数。
3. 在顶部原计数位置显示当前工作区的规范化绝对路径和文件夹图标；左侧品牌区只保留放大的 MiniCodex。
4. 仅在当前 run 的活动回复卡左侧显示轻量三点脉冲动画，使耗时模型或工具调用有持续但不误导的视觉反馈。

## 2. 非目标

- 不改变 run progress、SSE、预算或审计事件的服务端数据结构。
- 不从运行事件、工具输出、模型文本或 REST 新增绝对路径投影。
- 不增加文件选择器、打开目录、复制工作区路径或操作系统 Shell 集成。
- 不为 inline code、用户原始 Markdown 或非 fenced 文本添加复制按钮。
- 不增加真实百分比、预计剩余时间、随机进度、音效或高强度动画。
- 不引入 Markdown、图标、剪贴板或动画依赖。

## 3. 顶部布局与工作区绝对路径

左侧 `.brand-row` 保留现有代码标记图标和 `MiniCodex`，删除 `workspace-name` 与文件夹名。品牌文字提高到约 20px，并继续在窄侧栏中安全收缩。

主区 `.run-header` 继续显示当前会话标题、状态、已运行时间和取消按钮。原 `run-phase` fact 整体替换为工作区路径 fact：

- 使用代码内联 SVG 文件夹图标，不请求外部资产；
- `workspace-path` 文本为 `controller.workspace.resolve(strict=False)` 的字符串表示；
- 桌面端单行省略，完整值同时放在 `title`，辅助技术仍读取完整文本；
- 窄屏限制宽度并优先保留路径，不把主对话区向下挤压；
- `renderRunHeader` 不再把 `main_model_calls`、`summary_model_calls`、`provider_attempts` 或 `tool_calls` 写入 DOM。

首页继续执行既有 loopback、随机端口、Host/Origin、CSP 与 `Cache-Control: no-store` 边界。绝对路径是用户明确批准的本地 GUI 信息披露例外：它只进入转义后的首页文档，不进入 REST、SSE、SQLite、JSONL、模型上下文、报告或异常。首页模板必须恰好包含预期数量的 token/path marker；路径同时用于 text 与 title 时都使用 `html.escape(..., quote=True)`。

## 4. 代码块复制

确定性 Markdown renderer 把每个已闭合 fenced code block 渲染为 `.code-block` 容器，内部仍使用显式 `pre > code` 文本节点，并增加右上角 `.code-copy-button`：

- 初始可见文字与 accessible name 为“复制”；
- 点击时调用注入的 `clipboardWrite(text)`，生产默认值只使用 `navigator.clipboard.writeText`；
- 复制内容是围栏内部的精确规范化文本，不含围栏、语言标签或 renderer 为展示追加的尾换行；
- 单按钮在请求期间禁用，成功显示“已复制”，失败显示“复制失败”，固定 1.5 秒后恢复；
- clipboard 不可用、同步抛错或 Promise 拒绝均只产生固定失败状态，不展示异常文本，也不影响会话连接状态；
- 重绘或 controller 销毁时清除未完成的恢复 timer。

复制按钮和代码仍全部由 `createElement`、`createTextNode` 与固定属性构造；不得使用 `innerHTML`、`outerHTML`、`insertAdjacentHTML` 或 `document.write`。代码正文不得进入 `data-*` 或 HTML attribute。

## 5. 活动回复动画

`appendActivity` 增加显式 `active` 选项。只有 `renderConversation` 投影的当前内存活动或 provisional model text 传入 `active=true`：

- 卡片左侧增加 `aria-hidden=true` 的三点脉冲 indicator；
- 工具开始、工具完成后的等待、验证活动和模型 provisional text 都可显示；
- 持久历史事件、失败/中断、`changes_unverified`、取消提示和任何 terminal 卡不显示动画；
- run 终止、切换会话、SSE reset 或活动被下一条消息替换时，既有重绘自然移除 indicator；
- 动画只表达“MiniCodex 仍在运行”，不表达进度百分比或成功概率。

CSS 使用低对比度、约 1.1 秒的错峰三点脉冲。`prefers-reduced-motion: reduce` 下禁用循环动画并保留静态低对比度指示，避免闪烁。

## 6. 响应式和视觉规则

- 继续使用现有暖色背景、边框、圆角、字体和阴影 token。
- 复制按钮使用与模型刷新/次级按钮一致的暖色边框风格，不遮挡代码第一行；`pre` 为按钮预留顶部或右侧空间。
- 绝对路径与代码块都使用 `min-width: 0` 和安全 overflow；路径单行省略，代码横向滚动。
- 活动动画位于文字左侧，不改变消息最大宽度，也不推动 composer。
- 不改变 `.workspace` 的四行布局、conversation scroll owner 或 composer sticky 行为。

## 7. 测试与验收

Python 静态/HTTP 测试必须覆盖：

- 首页只包含绝对路径 marker 的预期替换，并同时转义 text/title；
- 左侧不存在 `workspace-name`，MiniCodex 品牌放大；
- 顶部存在内联文件夹图标、完整路径与省略 CSS，不再存在运行调用计数字样；
- CSP/no-store/Host/Origin 与资源安全头保持不变；
- 无 inline handler/style 或不安全 HTML sink。

Node 测试必须覆盖：

- 每个闭合 fenced block 只生成一个复制按钮；未闭合围栏仍是纯文本且无按钮；
- 成功复制精确正文、pending 单次调用、成功恢复、失败固定文案和无原始异常；
- 恶意代码内容保持文本，不能创建元素或属性；
- 仅当前活动卡带动画 indicator，terminal/history 卡不带；
- run header 不再呈现模型/摘要/provider/工具计数；
- 现有 Markdown、表格、链接、Enter、Skill、删除、模型选择和 SSE 行为回归通过。

最终必须运行完整离线 Python suite、完整 Node GUI suite、unsafe sink/credential/dependency 扫描和 `git diff --check`。不运行真实 provider 请求，不提交或推送 Git。
