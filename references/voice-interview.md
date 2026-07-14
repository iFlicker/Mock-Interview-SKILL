# 网页语音面试通道

本文件是网页语音通道、MCP 工具协议和运行时生命周期的唯一规则来源。网页只负责展示、朗读、语音转写、编辑和提交；面试策略、问题历史、证据账本、评分及报告仍由 `SKILL.md`、`interview-policy.md`、`session-state.md` 和 `scoring-rubrics.md` 决定。

## 启动前提

以下条件全部满足前，不得启动服务、打开浏览器或提出正式问题：

1. 已取得有效简历和明确目标职位；
2. 用户已确认完整面试配置和自定义项；
3. 评分蓝图已冻结，会话状态已初始化；
4. 用户已明确选择 `web_voice`。

选择 `agent_text` 时不得运行本文件中的任何启动动作。

## 自动启动

使用 `scripts/voice_interview.py start` 调用跨平台启动层，并只传递面试配置摘要、虚构面试官显示信息、语言和 TTS 默认语速。不得传递完整简历、完整职位材料或评分蓝图。脚本会：

1. 检测 Codex、Claude Code、Cursor、OpenCode 或其他兼容宿主；
2. 检测 macOS、Windows、Linux 及远程环境；
3. 仅使用当前 Python 标准库准备本地 MCP 与网页服务；
4. 自动选择空闲端口并只绑定 `127.0.0.1`；
5. 创建不可预测的 Agent token、session token 和 session ID；
6. 创建网页会话，但不在 `start` 阶段打开浏览器；
7. 返回始终可点击的 `room_url` 和仅供当前 Agent 使用的 `runtime_file`。

服务子进程首次退出时，启动器必须在同一次 `start` 请求内更换端口并按短退避继续尝试，最多 5 次。启动期 stderr 只临时写入权限受限的 runtime 目录，用于生成不含 token 和面试内容的错误分类；成功或最终失败后立即删除。只有全部尝试失败才返回 `service_start_failed`，普通用户不需要再次输入“重试”。宿主工具在自动重试期间返回运行中 cell 时，Agent 必须恢复该 cell，不能并发发起第二个 `start`。

`start` 成功后，Agent 必须先向用户显示“语音面试室已准备好，正在为你打开网页”及可点击的 `room_url`。完成这条用户可见提示后，宿主正式提供内嵌浏览器工具时用该工具打开；否则调用 `scripts/voice_interview.py open --runtime ...`，由启动层跨平台打开系统默认浏览器。不得在打开动作之后才补发“已尝试自动打开”。打开动作成功不代表网页已连接；必须通过事件接口观察到 `web_connected` 或 `web_reconnected`，才能输出开始边界并推送正式问题。

正常用户提示不得包含命令、端口、MCP 配置、token、runtime 文件或进程日志。启动失败时只说明语音面试室暂时不可用，并提供切回文字面试的选择。远程容器、SSH、Codespaces、Gitpod 或 CI 环境默认拒绝启动本地网页，不得伪装 localhost 可访问。

## MCP 传输与宿主适配

服务实现 `mock-interview-voice/1.0`，同时提供：

- `POST /mcp`：本地 Streamable HTTP 风格 JSON-RPC 工具端点，使用 Agent Bearer token；
- `scripts/voice_mcp_server.py`：stdio MCP 入口，供能够预配置本地进程的宿主使用；
- `scripts/voice_interview.py call`：同一 MCP 工具的当前会话控制入口，在宿主无法热加载新 MCP 时使用。
- `scripts/voice_interview.py wait`：持续持有当前 Agent 回合的等待入口；内部仍使用最长 25 秒的 MCP 短等待，并在每次超时时输出不含用户内容的心跳。

三种入口调用同一 `SessionStore` 契约，不得出现不同的面试逻辑。宿主适配器必须如实记录限制：Codex 新增 MCP 配置后需要重启客户端；Claude Code CLI 支持本地作用域配置；Cursor 只有扩展 API 可以热注册，`mcp.json` 通常需要宿主重新加载；OpenCode 使用配置文件且 `mcp add` 为交互流程。当前会话不能热加载时，自动使用本地控制入口，不要求用户配置，也不得声称工具已经动态注册。

### 持续等待所有权

一个 runtime 同一时间最多允许一个 `wait` 进程。启动入口在 runtime 临时目录中取得跨进程等待租约，并在收到回答、控制事件、发生错误或进程正常退出时释放；进程异常终止后，下一次等待会回收失效租约。并发启动第二个等待者时必须立即返回 `status: already_waiting` 和 `action: resume_existing_wait`，不得形成两个读取同一事件流的进程。

Codex 调用等待时，外层 `functions.exec` 的 yield 必须长于内层命令，推荐外层 25 秒、内层 20 秒。外层返回 `Script running with cell ID ...` 表示包装层仍在运行，不表示一次 MCP 超时；必须用顶层 `functions.wait` 续读原 `cell_id`，不得创建新的包装 cell。如果得到 shell `session_id`，一次只允许一个 `write_stdin` 续读，等它返回后才能再次轮询。任何情况下都不得为同一会话重新执行 `scripts/voice_interview.py wait`。网页连接门禁使用 `get_session_events`；只有正式问题成功推送后才能取得回答等待租约。

## 版本化 MCP 工具

所有工具结果均为 JSON 对象。MCP `initialize` 返回协议版本、工具能力和“网页不负责面试决策”的服务说明。

### `create_interview_session`

输入：

- `config_summary`：不含完整简历的配置摘要；
- `interviewer`：至少包含 `name` 和 `role`；
- `language`：浏览器语言标记；
- `tts.rate`：可选，默认 `1.0`。

输出包含 `session_id`、不可预测 `session_token`、带 token fragment 的 `room_url`、Agent 连接状态和能力摘要。token 不放在 HTTP query 中，避免进入普通请求日志。

### `send_interviewer_message`

输入至少包含 `session_id`、稳定唯一的 `message_id`、`message_type`、`display_text`、`speech_text`、`auto_speak`、`language` 和时间戳。

`message_type` 可以是 `interviewer_question`、`interviewer_message`、`system_status` 或 `interview_end`。任何期待候选人回答的文本都必须使用 `interviewer_question` 和新的唯一 `message_id`；重新表述、澄清、要求展开和追问也不例外。`interviewer_message` 只能承载不期待回答的陈述。网页开始边界使用 `system_status` 且 `display_text: 面试开始`，结束边界使用 `interview_end` 且 `display_text: 面试结束`；Agent App 仍使用 `SKILL.md` 的长分界线。边界不能伪装成面试官、不能自动朗读。相同 `message_id` 和内容返回 `duplicate: true`；相同 ID 配不同内容返回冲突。只有新面试官消息才自动朗读。

### `wait_for_candidate_reply`

输入包含 `session_id`、可选 `question_id`、`cursor` 和 `timeout_ms`。`question_id` 必须指向已经推送的 `interviewer_question`；传入普通 `interviewer_message` ID 时拒绝等待。单次等待最长 25 秒；超时返回 `status: timeout` 和新的 `next_cursor`。`wait` 启动入口必须在内部继续短轮询，使 Agent 回合保持运行；它不是一次无限阻塞的 MCP 调用。指定问题已经收到回答时，无论 cursor 是否越过该事件，都立即幂等返回原回答，避免网页已锁定而 Agent 永久等待。

回答包含唯一 `reply_id`、`question_id`、用户确认后的文本、可选原始转写、`voice`/`keyboard`/`mixed` 来源、可选持续时间和时间戳。控制事件返回 `status: control` 与控制类型。

### `get_session_events`

使用 `cursor` 获取 sequence 严格递增的事件：候选人回答、暂停、继续、跳过、结束、网页连接、断开、重连和切回文字。每个网页传输消息都携带协议版本和唯一消息或请求 ID；控制指令使用稳定 `control_id` 防止重试或重复点击产生重复事件。读取事件不是破坏性消费；Agent 只通过自己的 cursor 和 `session-state.md` 的回答消费标记保证恰好一次写入正式状态。

### `close_interview_session`

幂等关闭网页会话。正式结束使用 `reason: completed`；切回文字使用 `reason: switch_to_text`，不得把通道切换误记为正式面试结束。网页收到相应事件后停止 TTS、停止麦克风、禁用输入和提交。关闭运行时不得删除问题历史、证据账本或评价数据。

## 正式面试循环

1. 观察网页连接事件；只在首次连接成功后把 `start_boundary_emitted` 设为 `true`，在 Agent App 输出长开始条，并以 `system_status` 和短文案“面试开始”幂等推送网页边界。
2. 按既有面试策略生成一个问题，先写入唯一 `question_history` 项，再用相同问题 ID 推送网页。
3. 问题推送成功后，在同一 Agent 回合只启动一次 `scripts/voice_interview.py wait` 并持续读取原运行会话。它以不超过 25 秒的短调用接收回答或控制事件；每次超时只更新 cursor 并发出心跳。不得因为外层工具暂时 yield、超时、用户沉默或网页仍在编辑回答而重新执行 `wait`、发送 `final_answer`、结束 Agent 回合、关闭会话、停止服务、评分或提出新问题。
4. 首次消费回答 ID 时更新当前问题、证据槽位和证据账本；重复 ID、同问题重复提交或已消费事件直接忽略。
5. 按统一策略决定追问、完成主题、跳过、暂停、恢复或结束。收到回答并推送下一问题后立即启动新的持续等待；暂停时仍持续等待恢复、结束或切回文字事件。语音转写流畅度、浏览器能力和麦克风错误不得作为评分证据。
6. 结束时在 Agent App 输出长结束条，并以 `interview_end` 和短文案“面试结束”只推送一次网页边界；`interview_ended` 事件只转换页面状态，不生成第二条提示。随后调用关闭工具、运行 `scripts/voice_interview.py stop` 释放服务，再按原评分和报告流程在当前 Agent App 输出评价。

本地服务连接和 Agent 连接不是同一概念。Agent 每次 MCP 调用都会刷新心跳；超过心跳窗口后，网页必须把顶部状态改为“无法连接”，不得因为 WebSocket 仍连着本地服务就继续显示“已连接”。

## 网页行为

- 页面自动、静默检测 Agent 连接、TTS、STT 和麦克风权限，只长期显示简洁的连接状态；不提供设备测试或校准流程；
- Agent 已连接但首题尚未到达时，网页显示带旋转图标的临时状态“已连接，面试官正在准备。...”；等待较久时只更新临时文案，不伪造进度或倒计时；
- WebSocket 是首选，断开后指数退避重连；连续失败后自动使用带 cursor 的 HTTP 长轮询；
- 刷新页面从 snapshot 恢复已存在的消息和回答，历史消息不自动重新朗读；
- 用户靠近消息底部时自动滚动，新消息到达但用户正在看历史时不抢走滚动位置；
- TTS 使用 `speechSynthesis`。可靠字符边界时按字符或词高亮；只收到句边界时按句高亮；没有可靠边界时只显示“正在朗读”，不得伪造精确进度；
- 打开麦克风会先停止 TTS。STT 使用 `SpeechRecognition` 或 `webkitSpeechRecognition`，设置 `continuous = true`、`interimResults = true`；临时结果单独展示，最终结果只追加到可编辑输入框；
- 停顿、识别结束或临时结果都不得自动提交。只有发送按钮或 `Ctrl/Command + Enter` 才提交；提交成功后清空，失败保留；
- 回答提交期间发送按钮使用带无障碍文本的旋转图标；服务确认后，候选人气泡显示“已发送”，并在面试官一侧显示带旋转图标的临时状态“思考中...”，直到正式下一问、暂停、断线、结束或切回文字；这些临时状态不得朗读、写入 timeline、问题历史或评分证据；
- STT 不可用不阻止文字输入，并提示可使用 Typeless、微信输入法或其他系统语音输入；
- 页面进入后台、设备变化、关闭页面、结束或切回文字时停止麦克风；结束或切换时同时停止 TTS。

## 安全与隐私

- 只监听 `127.0.0.1`，不默认监听 `0.0.0.0`；
- Agent API 使用独立 Bearer token，网页 API 使用 session token，并校验同源 Origin；
- 默认不录制、保存或上传音频；只把用户确认后的回答文本交给 Agent；
- 默认不把原始临时转写传给服务；不得在日志中打印简历、完整问题、完整回答、URL token 或请求体；
- 页面明确提示浏览器语音识别可能由浏览器厂商的在线服务处理；
- runtime 文件位于系统临时目录、权限尽可能设为仅当前用户可读，并在停止时删除。

## 降级和清理

TTS、STT 或麦克风不可用时保留文字面试室。Agent 或本地服务无法恢复、当前环境为远程，或用户主动切回文字时，保留全部正式状态和当前问题，将 `interaction_channel` 改为 `agent_text`，不重复开始边界，后续在当前应用继续。

所有正常结束、提前结束和切回文字流程都应调用关闭工具及 `stop`。用户沉默、一次或多次等待超时、网页暂时断开或 Agent 仍在等待都不是清理条件。进程已经退出时，清理脚本仍需幂等删除临时运行时文件。无法自动打开浏览器不属于服务失败，只需向用户展示可点击 URL。
