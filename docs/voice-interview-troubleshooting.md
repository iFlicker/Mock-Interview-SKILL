# 网页语音面试开发者故障排查

本文面向维护者。普通用户不需要执行这里的命令，也不需要安装或配置 MCP。

## 架构

`voice_interview/store.py` 是唯一会话内核；`server.py` 提供 localhost 网页、WebSocket、HTTP 降级和 MCP HTTP；`mcp.py` 定义 JSON-RPC 与工具 schema；`voice_mcp_server.py` 提供 stdio 入口；`launcher.py` 与 `scripts/voice_interview.py` 负责检测环境、选择端口、启动、打开浏览器和清理。

网页资源位于 `voice_interview/web/`，不需要构建。服务只依赖 Python 标准库。

## 开发环境手动调试

在 Skill 根目录执行以下命令只用于开发：

```bash
python3 scripts/voice_interview.py start \
  --config-summary '{"target_position":"产品经理","interaction_channel":"web_voice"}' \
  --interviewer '{"name":"陈老师","role":"产品负责人"}' \
  --language zh-CN
```

`start` 只准备会话，不打开浏览器。需要验证跨平台打开动作时，使用启动结果中的 runtime 文件：

```bash
python3 scripts/voice_interview.py open --runtime /tmp/mock-interview-voice-.../runtime.json
```

启动命令返回 `runtime_file`、`session_id` 和 `room_url`。使用同一 runtime 调 MCP 工具：

```bash
python3 scripts/voice_interview.py call \
  --runtime /tmp/mock-interview-voice-.../runtime.json \
  --tool send_interviewer_message \
  --arguments '{"session_id":"...","message_id":"q-1","message_type":"interviewer_question","display_text":"请做一个简短的自我介绍。","speech_text":"请做一个简短的自我介绍。","auto_speak":true,"language":"zh-CN"}'
```

问题推送后，正式运行流程必须使用持续等待入口持有当前 Agent 回合。它会在内部执行最长 25 秒的短轮询；输出 `waiting` 心跳是正常状态，不是结束条件：

```bash
python3 scripts/voice_interview.py wait \
  --runtime /tmp/mock-interview-voice-.../runtime.json \
  --question-id q-1 \
  --cursor 2
```

如果 Agent 在回答或控制事件到达前发送了最终答复，宿主会把任务置为 idle；本地桥接可以保存后续网页事件，但不能主动唤醒已结束的 Agent 回合。此时应检查 Skill 是否遗漏了持续等待，不能把问题归因于 WebSocket 或端口。网页顶部根据 Agent MCP 心跳显示连接状态，不再把“本地服务仍可访问”误报为“Agent 已连接”。

同一 runtime 只能有一个 `wait` 进程。Codex 外层执行返回 `Script running with cell ID ...` 时，用 `functions.wait` 续读该 cell；底层返回 shell `session_id` 时续读该 session。不要重新执行命令。误启动第二个等待者会立即得到：

```json
{"status":"already_waiting","action":"resume_existing_wait"}
```

等待所有权记录位于 runtime 目录的 `.wait-owner/`，不包含回答或 token。正常退出时自动删除；进程崩溃后下一次等待会检查 PID 并回收失效记录。排查重复调用时，先确认执行记录中是否对同一 runtime 多次调用了 `voice_interview.py wait`，再检查 Agent 是否误把外层工具 yield 当作 MCP 超时。

完成后清理：

```bash
python3 scripts/voice_interview.py stop --runtime /tmp/mock-interview-voice-.../runtime.json
```

## 自动部署失败原因

- 远程、SSH、云容器或 CI 环境中的 localhost 无法被用户浏览器访问；
- Python 版本不支持项目使用的语法；
- 安全软件阻止本地回环连接或浏览器麦克风权限；
- 临时目录不可写；
- 宿主 MCP 工具清单无法在当前会话热刷新；
- Agent 回合在等待网页回答时被提前结束；
- 系统默认浏览器不可用，但此时服务与 URL 仍可能正常。

端口被占用会自动重新选择，通常不需要人工处理。运行期请求日志仍默认丢弃，以免泄露面试内容；只有启动阶段临时捕获子进程 stderr，并按下述规则立即清理。

启动器现在会在同一次请求内最多尝试 5 次，并使用短退避。每次启动只在 runtime 目录暂存权限为当前用户可读的 stderr；它只用于归类 `port_conflict`、`module_import_failed`、`permission_denied`、`runtime_incompatible` 等启动原因，不记录请求体。启动成功或最终失败后文件立即删除，结构化 `diagnostic` 只保留分类和最后一行摘要。普通用户仍只看到可恢复的自然语言提示。

如果网页显示新提示，但仍认为旧问题已经回答，检查该提示的 `message_type`。重新表述、澄清和要求展开都必须使用新的 `interviewer_question` ID；`interviewer_message` 不会改变网页当前问题。再次等待已经回答的问题会立即返回原回答并带 `duplicate: true`，不应继续阻塞。

## 临时文件与日志位置

每轮运行时文件位于系统临时目录下随机命名的 `mock-interview-voice-*` 目录，正常停止后整个目录会删除。默认没有持久日志文件，也不会把请求体、完整问题、完整回答或 token 写入日志。Claude Code 的临时本地 MCP 条目使用带 session 前缀的唯一名称，停止时自动移除；异常退出后残留条目指向已经停止的 localhost 服务，不包含可继续使用的服务能力，可由下一次维护清理。

## 验证

```bash
python3 scripts/test_voice_interview.py
python3 scripts/test_generate_report.py
python3 scripts/test_skill_contract.py
```

真实浏览器的声音质量、边界事件粒度、麦克风授权 UI 和 STT 准确率必须人工验证。不要用自动化测试声称已经验证真实设备能力。
