(() => {
  "use strict";
  const PROTOCOL_VERSION = "mock-interview-voice/1.0";

  const elements = {
    messages: document.querySelector("#messages"),
    name: document.querySelector("#interviewer-name"),
    role: document.querySelector("#interviewer-role"),
    connection: document.querySelector("#connection-status"),
    pause: document.querySelector("#pause-button"),
    end: document.querySelector("#end-button"),
    skip: document.querySelector("#skip-button"),
    switchText: document.querySelector("#switch-button"),
    input: document.querySelector("#answer-input"),
    send: document.querySelector("#send-button"),
    mic: document.querySelector("#mic-button"),
    micLabel: document.querySelector("#mic-label"),
    interim: document.querySelector("#interim"),
    notice: document.querySelector("#notice"),
    rate: document.querySelector("#speech-rate"),
    visualizer: document.querySelector("#visualizer-container"),
    canvas: document.querySelector("#voice-canvas"),
    themeToggle: document.querySelector("#theme-toggle"),
    avatar: document.querySelector("#interviewer-avatar"),
  };

  const pathMatch = location.pathname.match(/^\/room\/([a-f0-9]+)$/i);
  const token = new URLSearchParams(location.hash.slice(1)).get("token") || sessionStorage.getItem("mockInterviewToken") || "";
  const sessionId = pathMatch ? pathMatch[1] : "";
  if (token) sessionStorage.setItem("mockInterviewToken", token);
  history.replaceState(null, "", location.pathname);

  const state = {
    cursor: 0,
    status: "ready",
    language: "zh-CN",
    socket: null,
    retryCount: 0,
    pollActive: false,
    rendered: new Set(),
    renderedBoundaries: new Set(),
    lastQuestionId: null,
    answeredQuestions: new Set(),
    pending: new Map(),
    submitInFlight: false,
    activityKind: null,
    activityNode: null,
    activityTimer: null,
    controlInFlight: false,
    pendingControl: null,
    pendingReplyId: null,
    voiceUsed: false,
    keyboardUsed: false,
    recognition: null,
    micRequested: false,
    micStartedAt: null,
    voiceDurationMs: 0,
    recognitionFailed: false,
    speech: null,
    agentConnected: null,
    reconnecting: sessionStorage.getItem("mockInterviewConnected") === "1",
    clientId: sessionStorage.getItem("mockInterviewClientId") || uuid(),
    
    // Web Audio 与 Canvas 声波状态
    audioStream: null,
    audioCtx: null,
    analyser: null,
    animationId: null,
    cleanupCanvasResize: null,
    isHoldToTalk: false,
  };
  sessionStorage.setItem("mockInterviewClientId", state.clientId);

  function uuid() {
    return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function setConnection(kind, text) {
    elements.connection.className = `connection ${kind}`;
    elements.connection.textContent = text;
  }

  function showNotice(text) {
    elements.notice.textContent = text;
    elements.notice.hidden = !text;
  }

  function applyAgentConnection(connected) {
    state.agentConnected = Boolean(connected);
    if (state.status === "ended" || state.status === "switched_to_text") return;
    if (state.agentConnected) {
      setConnection("connected", "已连接");
      updateActivity();
    } else {
      setConnection("failed", "无法连接");
      clearActivity();
    }
  }

  function nearBottom() {
    const el = elements.messages;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 90;
  }

  function appendNode(node, forceScroll = false) {
    const shouldScroll = forceScroll || nearBottom();
    elements.messages.append(node);
    if (shouldScroll) node.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  function formatTime(value) {
    const date = new Date(value || Date.now());
    return Number.isNaN(date.valueOf()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function clearActivity() {
    if (state.activityTimer) window.clearTimeout(state.activityTimer);
    state.activityTimer = null;
    state.activityKind = null;
    state.activityNode?.remove();
    state.activityNode = null;
  }

  function setActivity(kind, text) {
    if (state.activityKind === kind && state.activityNode?.isConnected) {
      state.activityNode.querySelector(".activity-text").textContent = text;
      return;
    }
    clearActivity();
    const wrapper = document.createElement("div");
    wrapper.className = "message interviewer activity-message";
    wrapper.setAttribute("role", "status");
    wrapper.setAttribute("aria-live", "polite");
    wrapper.setAttribute("aria-atomic", "true");
    const bubble = document.createElement("div");
    bubble.className = "bubble activity-bubble";
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    spinner.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.className = "activity-text";
    label.textContent = text;
    bubble.append(spinner, label);
    wrapper.append(bubble);
    state.activityKind = kind;
    state.activityNode = wrapper;
    appendNode(wrapper);
    if (kind === "opening") {
      state.activityTimer = window.setTimeout(() => {
        if (state.activityKind === "opening" && state.activityNode?.isConnected) {
          state.activityNode.querySelector(".activity-text").textContent = "已连接，面试官仍在准备。...";
        }
      }, 10000);
    }
  }

  function updateActivity() {
    const unavailable = !state.agentConnected || ["paused", "ended", "switched_to_text"].includes(state.status);
    if (unavailable || state.submitInFlight) {
      clearActivity();
      return;
    }
    if (!state.lastQuestionId) {
      setActivity("opening", "已连接，面试官正在准备。...");
      return;
    }
    if (state.answeredQuestions.has(state.lastQuestionId)) {
      setActivity("thinking", "思考中...");
      return;
    }
    clearActivity();
  }

  function setSendBusy(busy) {
    elements.send.replaceChildren();
    if (busy) {
      const spinner = document.createElement("span");
      spinner.className = "spinner spinner-on-primary";
      spinner.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.className = "sr-only";
      label.textContent = "发送中";
      elements.send.append(spinner, label);
      elements.send.setAttribute("aria-label", "回答发送中");
      return;
    }
    elements.send.textContent = "发送";
    elements.send.removeAttribute("aria-label");
  }

  function createSpeechText(text) {
    const container = document.createElement("span");
    container.className = "speech-text";
    let offset = 0;
    for (const character of Array.from(text)) {
      const span = document.createElement("span");
      span.className = "speech-unit pending";
      span.dataset.offset = String(offset);
      span.dataset.length = String(character.length);
      span.textContent = character;
      container.append(span);
      offset += character.length;
    }
    return container;
  }

  const PLAY_SVG = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>`;
  const STOP_SVG = `<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"></rect></svg>`;

  function renderInterviewer(message, autoSpeak = false) {
    if (state.rendered.has(message.message_id)) return;
    state.rendered.add(message.message_id);
    if (message.message_type === "interviewer_question") {
      clearActivity();
      state.lastQuestionId = message.message_id;
      applySessionStatus(state.status);
    }
    const wrapper = document.createElement("article");
    wrapper.className = "message interviewer";
    wrapper.dataset.messageId = message.message_id;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.dataset.reading = "false";
    bubble.append(createSpeechText(message.display_text));
    const meta = document.createElement("div");
    meta.className = "bubble-meta";
    const reading = document.createElement("span");
    reading.className = "reading-status";
    const replay = document.createElement("button");
    replay.type = "button";
    replay.className = "replay";
    replay.setAttribute("aria-label", "重新朗读这条面试官消息");
    replay.innerHTML = PLAY_SVG;
    replay.addEventListener("click", () => toggleSpeech(message));
    const time = document.createElement("time");
    time.textContent = formatTime(message.timestamp);
    meta.append(reading, replay, time);
    bubble.append(meta);
    wrapper.append(bubble);
    appendNode(wrapper);
    if (autoSpeak && message.auto_speak !== false) speak(message);
  }

  function renderCandidate(reply) {
    if (state.rendered.has(reply.reply_id)) return;
    state.rendered.add(reply.reply_id);
    state.answeredQuestions.add(reply.question_id);
    const wrapper = document.createElement("article");
    wrapper.className = "message candidate";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    const text = document.createElement("span");
    text.textContent = reply.text;
    const meta = document.createElement("div");
    meta.className = "bubble-meta";
    const delivery = document.createElement("span");
    delivery.className = "delivery-status";
    delivery.textContent = "已发送";
    const time = document.createElement("time");
    time.textContent = formatTime(reply.timestamp);
    meta.append(delivery, time);
    bubble.append(text, meta);
    wrapper.append(bubble);
    appendNode(wrapper);
    applySessionStatus(state.status);
    updateActivity();
  }

  function systemMessage(text) {
    const node = document.createElement("div");
    node.className = "system-message";
    node.textContent = text;
    appendNode(node);
  }

  function boundaryKind(message) {
    if (message.message_type === "interview_end") return "end";
    const compactText = String(message.display_text || "").replace(/[-—\s]/g, "");
    if (message.message_type === "system_status" && compactText === "面试开始") return "start";
    return null;
  }

  function renderBoundary(kind) {
    if (state.renderedBoundaries.has(kind)) return;
    state.renderedBoundaries.add(kind);
    systemMessage(kind === "start" ? "面试开始" : "面试结束");
  }

  function renderSystemMessage(message) {
    if (state.rendered.has(message.message_id)) return;
    state.rendered.add(message.message_id);
    const kind = boundaryKind(message);
    if (kind) renderBoundary(kind);
    else systemMessage(message.display_text);
  }

  function applySessionStatus(status) {
    state.status = status;
    const paused = status === "paused";
    const closed = status === "ended" || status === "switched_to_text";
    const awaitingNextQuestion = Boolean(
      state.lastQuestionId && state.answeredQuestions.has(state.lastQuestionId)
    );
    elements.pause.textContent = paused ? "继续面试" : "暂停面试";
    elements.input.disabled = paused || closed || awaitingNextQuestion;
    elements.send.disabled = paused || closed || awaitingNextQuestion || state.submitInFlight;
    elements.mic.disabled = paused || closed || awaitingNextQuestion || !state.recognition;
    elements.skip.disabled = paused || closed;
    if (paused || closed || awaitingNextQuestion) stopRecognition(true);
    if (closed) {
      stopSpeech();
      elements.pause.disabled = true;
      elements.end.disabled = true;
      elements.switchText.disabled = true;
    }
    updateActivity();
  }

  function handleEvent(event) {
    state.cursor = Math.max(state.cursor, event.sequence || 0);
    const payload = event.payload || {};
    switch (event.type) {
      case "interviewer_message":
        renderInterviewer(payload.message, true);
        break;
      case "candidate_reply":
        renderCandidate(payload.reply);
        break;
      case "system_message":
        renderSystemMessage(payload.message);
        break;
      case "interview_paused":
        applySessionStatus("paused");
        systemMessage("面试已暂停");
        break;
      case "interview_resumed":
        applySessionStatus("active");
        systemMessage("面试已继续");
        break;
      case "question_skipped":
        systemMessage("已请求跳过当前问题");
        break;
      case "interview_ended":
        applySessionStatus("ended");
        renderBoundary("end");
        break;
      case "switch_to_text":
        applySessionStatus("switched_to_text");
        systemMessage("已切回当前应用的文字面试，问题历史和回答均已保留");
        break;
      default:
        break;
    }
  }

  async function loadSnapshot() {
    if (!sessionId || !token) throw new Error("面试链接无效或已失效。");
    const response = await fetch(`/api/session/${sessionId}/snapshot?token=${encodeURIComponent(token)}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "无法打开面试会话。");
    elements.name.textContent = data.interviewer.name || "面试官";
    elements.avatar.textContent = (data.interviewer.name || "面").charAt(0);
    elements.role.textContent = data.interviewer.role || "模拟面试官";
    state.language = data.language || "zh-CN";
    elements.rate.value = String(data.tts?.rate || 1);
    for (const item of data.timeline || []) {
      if (item.kind === "interviewer") renderInterviewer(item.data, false);
      if (item.kind === "candidate") renderCandidate(item.data);
      if (item.kind === "system") renderSystemMessage(item.data);
    }
    state.cursor = data.cursor || 0;
    applySessionStatus(data.status);
    applyAgentConnection(data.agent_connected);
    if (data.status === "ended") renderBoundary("end");
  }

  function connectWebSocket() {
    if (state.status === "ended" || state.status === "switched_to_text") return;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${location.host}/ws?session_id=${encodeURIComponent(sessionId)}&token=${encodeURIComponent(token)}&after=${state.cursor}&reconnect=${state.reconnecting ? 1 : 0}&client_id=${encodeURIComponent(state.clientId)}`;
    const socket = new WebSocket(url);
    state.socket = socket;
    setConnection(state.retryCount ? "retrying" : "connecting", state.retryCount ? "连接中断，正在重试" : "正在连接面试服务");
    socket.addEventListener("open", () => {
      state.retryCount = 0;
      state.pollActive = false;
      state.reconnecting = true;
      sessionStorage.setItem("mockInterviewConnected", "1");
      setConnection("connecting", "正在连接面试服务");
    });
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "connected" || message.type === "agent_status") {
        applyAgentConnection(message.agent_connected);
      }
      if (message.type === "event") handleEvent(message.event);
      if (message.type === "ack" || message.type === "error") {
        const pending = state.pending.get(message.request_id);
        if (pending) {
          state.pending.delete(message.request_id);
          message.type === "ack" ? pending.resolve(message.result) : pending.reject(new Error(message.error?.message || "操作失败"));
        }
      }
    });
    socket.addEventListener("close", () => {
      if (state.status === "ended" || state.status === "switched_to_text") return;
      clearActivity();
      for (const pending of state.pending.values()) pending.reject(new Error("连接暂时中断"));
      state.pending.clear();
      state.retryCount += 1;
      if (state.retryCount <= 5) {
        setConnection("retrying", "连接中断，正在重试");
        window.setTimeout(connectWebSocket, Math.min(800 * 2 ** (state.retryCount - 1), 8000));
      } else {
        setConnection("failed", "无法连接");
        showNotice("暂时无法连接面试服务。页面会继续重试；也可以返回当前应用切换为文字面试。");
        startPolling();
      }
    });
  }

  async function startPolling() {
    if (state.pollActive) return;
    state.pollActive = true;
    try {
      await fetch(`/api/session/${sessionId}/connect?token=${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: state.clientId, reconnected: state.reconnecting }),
      });
    } catch (_error) { /* polling below will keep retrying */ }
    while (state.pollActive && state.status !== "ended" && state.status !== "switched_to_text") {
      try {
        const response = await fetch(`/api/session/${sessionId}/events?token=${encodeURIComponent(token)}&after=${state.cursor}&timeout_ms=20000`, { cache: "no-store" });
        if (!response.ok) throw new Error("poll failed");
        const data = await response.json();
        (data.events || []).forEach(handleEvent);
        applyAgentConnection(data.agent_connected);
        showNotice("");
      } catch (_error) {
        clearActivity();
        setConnection("failed", "无法连接");
        await new Promise((resolve) => setTimeout(resolve, 2500));
      }
    }
  }

  function sendSocket(type, payload) {
    return new Promise((resolve, reject) => {
      if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
        reject(new Error("连接暂时不可用"));
        return;
      }
      const requestId = uuid();
      state.pending.set(requestId, { resolve, reject });
      state.socket.send(JSON.stringify({
        schema_version: PROTOCOL_VERSION,
        message_id: requestId,
        type,
        request_id: requestId,
        payload,
      }));
      window.setTimeout(() => {
        if (state.pending.has(requestId)) {
          state.pending.delete(requestId);
          reject(new Error("操作等待超时"));
        }
      }, 12000);
    });
  }

  async function sendAction(type, payload) {
    if (state.socket?.readyState === WebSocket.OPEN) return sendSocket(type, payload);
    const action = type === "candidate_reply" ? "candidate-reply" : "control";
    const response = await fetch(`/api/session/${sessionId}/${action}?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        schema_version: PROTOCOL_VERSION,
        ...payload,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "操作失败");
    return data;
  }

  function resetSpeechUnits(messageId) {
    document.querySelectorAll(`[data-message-id="${CSS.escape(messageId)}"] .speech-unit`).forEach((unit) => {
      unit.className = "speech-unit pending";
    });
  }

  function setSpeechProgress(messageId, index, mode) {
    const wrapper = document.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`);
    if (!wrapper) return;
    wrapper.querySelectorAll(".speech-unit").forEach((unit) => {
      const start = Number(unit.dataset.offset);
      const end = start + Number(unit.dataset.length);
      if (end <= index) unit.className = "speech-unit spoken";
      else if (start <= index && mode === "exact") unit.className = "speech-unit speaking";
      else unit.className = "speech-unit pending";
    });
  }

  function setReadingStatus(messageId, text, active) {
    const wrapper = document.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`);
    if (!wrapper) return;
    wrapper.querySelector(".bubble").dataset.reading = active ? "true" : "false";
    wrapper.querySelector(".reading-status").textContent = text;
    const replay = wrapper.querySelector(".replay");
    replay.innerHTML = active ? STOP_SVG : PLAY_SVG;
    replay.setAttribute("aria-label", active ? "停止朗读这条消息" : "重新朗读这条面试官消息");
  }

  function stopSpeech() {
    if (!("speechSynthesis" in window)) return;
    const current = state.speech;
    speechSynthesis.cancel();
    if (current) setReadingStatus(current.messageId, "", false);
    state.speech = null;
  }

  function pickVoice(language) {
    const voices = speechSynthesis.getVoices();
    const exact = voices.find((voice) => voice.lang.toLowerCase() === language.toLowerCase());
    if (exact) return exact;
    const prefix = language.split("-")[0].toLowerCase();
    return voices.find((voice) => voice.lang.toLowerCase().startsWith(prefix)) || null;
  }

  function sentenceEnd(text, index) {
    const remainder = text.slice(index);
    const match = remainder.match(/[。！？!?；;\n]/);
    return match ? index + match.index + match[0].length : text.length;
  }

  function speak(message) {
    if (!("speechSynthesis" in window)) {
      showNotice("当前浏览器无法自动朗读问题，仍可阅读文字并继续面试。");
      return;
    }
    stopSpeech();
    resetSpeechUnits(message.message_id);
    const utterance = new SpeechSynthesisUtterance(message.speech_text || message.display_text);
    utterance.lang = message.language || state.language;
    utterance.rate = Number(elements.rate.value || 1);
    const voice = pickVoice(utterance.lang);
    if (voice) utterance.voice = voice;
    const speechState = {
      messageId: message.message_id,
      utterance,
      boundaries: [],
      mode: "status",
      progressCompatible: utterance.text === message.display_text,
    };
    state.speech = speechState;
    utterance.onstart = () => setReadingStatus(message.message_id, "正在朗读", true);
    utterance.onboundary = (event) => {
      if (state.speech !== speechState || !speechState.progressCompatible || !Number.isFinite(event.charIndex)) return;
      speechState.boundaries.push(event.charIndex);
      const distinct = [...new Set(speechState.boundaries)].sort((a, b) => a - b);
      if (distinct.length >= 2 && distinct.at(-1) > distinct[0]) {
        speechState.mode = "exact";
        setSpeechProgress(message.message_id, event.charIndex, "exact");
      } else if (event.name === "sentence") {
        speechState.mode = "sentence";
        setSpeechProgress(message.message_id, sentenceEnd(utterance.text, event.charIndex), "sentence");
      }
    };
    utterance.onend = () => {
      if (state.speech !== speechState) return;
      setSpeechProgress(message.message_id, message.display_text.length, "sentence");
      setReadingStatus(message.message_id, "已朗读", false);
      state.speech = null;
    };
    utterance.onerror = () => {
      if (state.speech === speechState) {
        setReadingStatus(message.message_id, "朗读已停止", false);
        state.speech = null;
      }
    };
    speechSynthesis.speak(utterance);
  }

  function toggleSpeech(message) {
    if (state.speech?.messageId === message.message_id) stopSpeech();
    else speak(message);
  }

  function startWaveformAnimation() {
    stopWaveformAnimation();
    if (!elements.canvas) return;
    
    const canvas = elements.canvas;
    const ctx = canvas.getContext("2d");
    
    const dpr = window.devicePixelRatio || 1;
    const resizeCanvas = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
    };
    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);
    
    let phase = 0;
    
    function draw() {
      state.animationId = requestAnimationFrame(draw);
      
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      ctx.clearRect(0, 0, width, height);
      
      let rms = 0;
      if (state.analyser) {
        const dataArray = new Uint8Array(state.analyser.frequencyBinCount);
        state.analyser.getByteTimeDomainData(dataArray);
        
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          const val = (dataArray[i] - 128) / 128;
          sum += val * val;
        }
        rms = Math.sqrt(sum / dataArray.length);
      }
      
      const maxAmplitude = height * 0.45;
      const amplitude = Math.max(2, rms * maxAmplitude * 4.5); 
      
      phase += 0.08;
      
      const drawSine = (pOffset, color, strokeWidth, op) => {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = strokeWidth;
        ctx.globalAlpha = op;
        
        for (let x = 0; x < width; x++) {
          const edgeDecay = Math.sin((x / width) * Math.PI);
          const y = (height / 2) + Math.sin((x * 0.02) + phase + pOffset) * amplitude * edgeDecay;
          if (x === 0) {
            ctx.moveTo(x, y);
          } else {
            ctx.lineTo(x, y);
          }
        }
        ctx.stroke();
      };
      
      drawSine(0, "#5f5af6", 2.5, 0.85);
      drawSine(Math.PI * 0.4, "#06b6d4", 1.8, 0.6);
      drawSine(Math.PI * 0.8, "#a5b4fc", 1.2, 0.4);
    }
    
    draw();
    
    state.cleanupCanvasResize = () => {
      window.removeEventListener("resize", resizeCanvas);
    };
  }
  
  function stopWaveformAnimation() {
    if (state.animationId) {
      cancelAnimationFrame(state.animationId);
      state.animationId = null;
    }
    if (state.cleanupCanvasResize) {
      state.cleanupCanvasResize();
      state.cleanupCanvasResize = null;
    }
    if (elements.canvas) {
      const canvas = elements.canvas;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }

  function setMicState(kind, text) {
    const mic = elements.mic;
    const prevWidth = mic.getBoundingClientRect().width;

    mic.dataset.state = kind;
    elements.micLabel.textContent = text;
    const listening = kind === "listening" || kind === "requesting";
    mic.setAttribute("aria-pressed", listening ? "true" : "false");
    mic.setAttribute("aria-label", listening ? "关闭麦克风并保留转写文字" : "打开麦克风进行语音输入");
    
    if (listening) {
      elements.visualizer.classList.add("active");
    } else if (kind === "off" || kind === "stopped" || kind === "failed" || kind === "unsupported") {
      elements.visualizer.classList.remove("active");
    }

    // 动态计算新宽度以执行平滑宽度过渡
    mic.style.width = "auto";
    const newWidth = mic.getBoundingClientRect().width;
    mic.style.width = `${prevWidth}px`;
    mic.offsetHeight; // 触发重绘
    mic.style.width = `${newWidth}px`;
  }

  function appendSpeech(text) {
    const incoming = text.trim();
    const separator = /[A-Za-z0-9]$/.test(elements.input.value) && /^[A-Za-z0-9]/.test(incoming) ? " " : "";
    elements.input.value += separator + incoming;
    state.voiceUsed = true;
    elements.input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function initialiseRecognition() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      elements.mic.disabled = true;
      setMicState("unsupported", "此浏览器不支持语音识别");
      showNotice("当前浏览器不支持原生语音识别。你可以继续键盘输入，或尝试 Typeless、微信输入法等系统语音输入工具。");
      return;
    }
    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = state.language;
    recognition.onstart = () => {
      state.recognitionFailed = false;
      state.micStartedAt = Date.now();
      setMicState("listening", "正在聆听");
    };
    recognition.onresult = (event) => {
      let interimText = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) appendSpeech(result[0].transcript);
        else interimText += result[0].transcript;
      }
      elements.interim.textContent = interimText ? `临时识别：${interimText}` : "";
      elements.interim.hidden = !interimText;
    };
    recognition.onerror = (event) => {
      state.micRequested = false;
      state.recognitionFailed = true;
      const messages = {
        "not-allowed": "麦克风权限未开启。请在浏览器地址栏的权限设置中允许麦克风访问。",
        "audio-capture": "没有找到可用的音频输入设备，请检查麦克风连接。",
        "network": "语音识别服务暂时不可用，你可以继续键盘输入。",
      };
      showNotice(messages[event.error] || "语音识别失败，你可以保留已有文字并继续键盘输入。");
      setMicState("failed", "识别失败");
    };
    recognition.onend = () => {
      const wasRequested = state.micRequested;
      state.micRequested = false;
      settleMicDuration();
      elements.interim.hidden = true;
      elements.interim.textContent = "";
      if (state.recognitionFailed) setMicState("failed", "识别失败");
      else setMicState("stopped", wasRequested ? "识别已停止" : "麦克风已关闭");
    };
    state.recognition = recognition;
    applySessionStatus(state.status);
  }

  async function startRecognition() {
    if (!state.recognition || state.micRequested) return;
    stopSpeech();
    state.micRequested = true;
    setMicState("requesting", "正在请求麦克风权限");
    try {
      if (navigator.mediaDevices?.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        state.audioStream = stream;
        
        try {
          state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          state.analyser = state.audioCtx.createAnalyser();
          state.analyser.fftSize = 256;
          const source = state.audioCtx.createMediaStreamSource(stream);
          source.connect(state.analyser);
          
          startWaveformAnimation();
        } catch (e) {
          console.warn("初始化 Web Audio 失败:", e);
        }
      }
      state.recognition.lang = state.language;
      state.recognition.start();
    } catch (error) {
      state.micRequested = false;
      if (state.audioStream) {
        state.audioStream.getTracks().forEach((track) => track.stop());
        state.audioStream = null;
      }
      stopWaveformAnimation();
      if (error.name === "NotAllowedError" || error.name === "SecurityError") {
        showNotice("麦克风权限未开启。请允许此页面访问麦克风后再试。");
      } else if (error.name === "NotFoundError") {
        showNotice("没有找到可用的麦克风，你仍可使用键盘输入。");
      } else {
        showNotice("暂时无法启动麦克风，你仍可使用键盘输入。");
      }
      setMicState("failed", "麦克风启动失败");
    }
  }

  function stopRecognition(userInitiated = false) {
    if (!state.recognition) return;
    state.micRequested = false;
    settleMicDuration();
    
    if (state.audioStream) {
      state.audioStream.getTracks().forEach((track) => track.stop());
      state.audioStream = null;
    }
    if (state.audioCtx) {
      if (state.audioCtx.state !== "closed") {
        state.audioCtx.close().catch(() => {});
      }
      state.audioCtx = null;
    }
    state.analyser = null;
    stopWaveformAnimation();

    try { state.recognition.stop(); } catch (_error) { /* already stopped */ }
    elements.interim.hidden = true;
    elements.interim.textContent = "";
    setMicState("off", userInitiated ? "麦克风已关闭" : "识别已停止");
  }

  function settleMicDuration() {
    if (state.micStartedAt) {
      state.voiceDurationMs += Math.max(0, Date.now() - state.micStartedAt);
      state.micStartedAt = null;
    }
  }

  async function submitAnswer() {
    const text = elements.input.value.trim();
    if (!text || state.submitInFlight) return;
    if (!state.lastQuestionId) {
      showNotice("请等待面试官提出问题后再发送回答。");
      return;
    }
    if (state.answeredQuestions.has(state.lastQuestionId)) {
      showNotice("当前问题的回答已经提交，面试官正在处理。新问题到达后即可继续回答。");
      return;
    }
    stopRecognition(true);
    state.submitInFlight = true;
    clearActivity();
    elements.input.disabled = true;
    elements.send.disabled = true;
    setSendBusy(true);
    state.pendingReplyId ||= uuid();
    const source = state.voiceUsed && state.keyboardUsed ? "mixed" : state.voiceUsed ? "voice" : "keyboard";
    const payload = {
      reply_id: state.pendingReplyId,
      question_id: state.lastQuestionId,
      text,
      source,
      duration_ms: state.voiceUsed ? state.voiceDurationMs : null,
      timestamp: new Date().toISOString(),
    };
    try {
      await sendAction("candidate_reply", payload);
      renderCandidate(payload);
      resetComposerAfterSuccess(text, payload.question_id);
      showNotice("");
    } catch (error) {
      const reconciled = await reconcileReply(state.pendingReplyId, state.lastQuestionId).catch(() => false);
      if (reconciled) {
        resetComposerAfterSuccess(text, payload.question_id);
        showNotice("");
      } else {
        showNotice(`${error.message || "发送失败"}。回答已保留，请稍后重试。`);
      }
    } finally {
      state.submitInFlight = false;
      setSendBusy(false);
      applySessionStatus(state.status);
    }
  }

  function resetComposerAfterSuccess(text, questionId) {
    if (elements.input.value.trim() === text) elements.input.value = "";
    state.answeredQuestions.add(questionId);
    state.pendingReplyId = null;
    state.voiceUsed = false;
    state.keyboardUsed = false;
    state.micStartedAt = null;
    state.voiceDurationMs = 0;
    applySessionStatus(state.status);
  }

  async function reconcileReply(replyId, questionId) {
    if (!replyId || !questionId) return false;
    const response = await fetch(`/api/session/${sessionId}/snapshot?token=${encodeURIComponent(token)}`, { cache: "no-store" });
    if (!response.ok) return false;
    const snapshot = await response.json();
    const item = (snapshot.timeline || []).find((entry) => entry.kind === "candidate" && entry.data.reply_id === replyId && entry.data.question_id === questionId);
    if (!item) return false;
    renderCandidate(item.data);
    return true;
  }

  async function control(command) {
    if (state.controlInFlight) return;
    state.controlInFlight = true;
    if (!state.pendingControl || state.pendingControl.command !== command) {
      state.pendingControl = { command, controlId: uuid() };
    }
    try {
      await sendAction("control", {
        control: command,
        control_id: state.pendingControl.controlId,
      });
      state.pendingControl = null;
      showNotice("");
    } catch (error) {
      showNotice(error.message || "操作失败，请稍后重试。");
    } finally {
      state.controlInFlight = false;
    }
  }

  // 键盘快捷键支持
  let spacePressed = false;
  
  document.addEventListener("keydown", (event) => {
    // 1. 全局快捷键 Alt + M 切换麦克风
    if (event.altKey && event.code === "KeyM") {
      event.preventDefault();
      if (event.repeat) return;
      if (!elements.mic.disabled && state.status !== "paused" && state.status !== "ended") {
        state.micRequested ? stopRecognition(true) : startRecognition();
      }
      return;
    }
    
    // 2. 空格键长按说话
    const activeEl = document.activeElement;
    const isTyping = activeEl && (
      activeEl.tagName === "TEXTAREA" || 
      activeEl.tagName === "INPUT" || 
      activeEl.isContentEditable
    );
    
    if (event.code === "Space" && !isTyping) {
      event.preventDefault();
      if (event.repeat) return;
      
      if (!elements.mic.disabled && state.status !== "paused" && state.status !== "ended" && !state.micRequested) {
        spacePressed = true;
        state.isHoldToTalk = true;
        startRecognition();
      }
    }
  });
  
  document.addEventListener("keyup", (event) => {
    if (event.code === "Space" && spacePressed) {
      spacePressed = false;
      if (state.micRequested && state.isHoldToTalk) {
        stopRecognition(true);
      }
      state.isHoldToTalk = false;
    }
  });

  // 鼠标 / 触摸“按住说话”双模控制
  let micPressTimer = null;
  let micLongPressed = false;
  
  function handleMicStart(e) {
    if (elements.mic.disabled || state.status === "paused" || state.status === "ended") return;
    e.preventDefault();
    micLongPressed = false;
    
    micPressTimer = setTimeout(() => {
      micLongPressed = true;
      state.isHoldToTalk = true;
      if (!state.micRequested) {
        startRecognition();
      }
    }, 250);
  }
  
  function handleMicEnd(e) {
    if (micPressTimer) {
      clearTimeout(micPressTimer);
      micPressTimer = null;
    }
    
    if (micLongPressed) {
      e.preventDefault();
      if (state.micRequested && state.isHoldToTalk) {
        stopRecognition(true);
      }
      state.isHoldToTalk = false;
    }
  }

  elements.input.addEventListener("input", () => { state.keyboardUsed = true; });
  elements.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submitAnswer();
    }
  });
  elements.send.addEventListener("click", submitAnswer);
  
  elements.mic.addEventListener("click", (e) => {
    if (micLongPressed) {
      micLongPressed = false;
      return;
    }
    state.micRequested ? stopRecognition(true) : startRecognition();
    state.isHoldToTalk = false;
  });
  elements.mic.addEventListener("mousedown", handleMicStart);
  elements.mic.addEventListener("mouseup", handleMicEnd);
  elements.mic.addEventListener("mouseleave", handleMicEnd);
  elements.mic.addEventListener("touchstart", handleMicStart, { passive: false });
  elements.mic.addEventListener("touchend", handleMicEnd, { passive: false });

  elements.pause.addEventListener("click", () => control(state.status === "paused" ? "resume" : "pause"));
  elements.skip.addEventListener("click", () => control("skip"));
  elements.end.addEventListener("click", () => {
    if (window.confirm("确定结束本轮面试并返回当前应用查看评价吗？")) control("end");
  });
  elements.switchText.addEventListener("click", () => control("switch_to_text"));
  elements.themeToggle.addEventListener("click", () => {
    const isLight = document.body.classList.toggle("theme-light");
    localStorage.setItem("mock-interview-theme", isLight ? "light" : "dark");
  });

  document.addEventListener("visibilitychange", () => { if (document.hidden && state.micRequested) stopRecognition(false); });
  navigator.mediaDevices?.addEventListener?.("devicechange", () => { if (state.micRequested) { stopRecognition(false); showNotice("音频设备发生变化，语音识别已停止。请确认麦克风后重新打开。"); } });
  window.addEventListener("beforeunload", () => {
    stopSpeech();
    stopRecognition(false);
    const disconnectUrl = `/api/session/${sessionId}/disconnect?token=${encodeURIComponent(token)}`;
    const disconnectBody = new Blob(
      [JSON.stringify({ schema_version: PROTOCOL_VERSION, message_id: uuid(), client_id: state.clientId })],
      { type: "application/json" }
    );
    navigator.sendBeacon?.(disconnectUrl, disconnectBody);
    state.socket?.close();
  });
 
  async function initialise() {
    const savedTheme = localStorage.getItem("mock-interview-theme") || "dark";
    if (savedTheme === "light") {
      document.body.classList.add("theme-light");
    }

    try {
      await loadSnapshot();
      initialiseRecognition();
      if (!("speechSynthesis" in window)) showNotice("当前浏览器无法朗读问题，但仍可查看文字并继续面试。");
      connectWebSocket();
    } catch (error) {
      setConnection("failed", "无法连接");
      showNotice(`${error.message || "无法连接面试服务"} 请返回当前应用切换为文字面试。`);
      elements.input.disabled = true;
      elements.send.disabled = true;
      elements.mic.disabled = true;
    }
  }

  initialise();
})();
