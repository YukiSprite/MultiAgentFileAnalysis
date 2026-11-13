"use strict";

const el = (id) => document.getElementById(id);

const state = {
  session: null,
  runs: new Map(),
  sources: new Map(),
  seen: new Map(),
};

const EVENT_TYPES = [
  "workflow_started",
  "workflow_resumed",
  "workflow_stage_changed",
  "tool_called",
  "agent_started",
  "agent_finished",
  "human_input_requested",
  "human_input_received",
  "workflow_finished",
  "workflow_failed",
  "run_resumed",
  "pause",
  "terminal",
];

const STATUS_LABELS = {
  queued: "排队中",
  running: "诊断中",
  waiting_for_human: "等待现场信息",
  completed: "已完成",
  abstained: "未通过最终审查",
  failed: "运行失败",
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  el("askForm").addEventListener("submit", onSubmit);
  el("switchCorpus").addEventListener("click", switchCorpus);
  el("drawerClose").addEventListener("click", closeDrawer);
  el("scrim").addEventListener("click", closeDrawer);
  await loadCorpora();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = data.error || {};
    throw new Error(error.message || `HTTP ${response.status}`);
  }
  return data;
}

function esc(value) {
  const map = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return String(value ?? "").replace(/[&<>"']/g, (ch) => map[ch]);
}

function showError(node, message) {
  node.textContent = message;
  node.hidden = false;
}

function clearError(node) {
  node.textContent = "";
  node.hidden = true;
}

async function loadCorpora() {
  const box = el("corpora");
  box.innerHTML = "";
  try {
    const data = await api("/api/corpora");
    if (!data.corpora.length) {
      box.innerHTML =
        '<p class="hint">未发现可用知识库。请在 knowledge_base/ 下加入 Markdown 目录或 .mafa-corpus.yaml。</p>';
      return;
    }
    for (const corpus of data.corpora) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "corpus-card";
      button.innerHTML = `<strong>${esc(corpus.name)}</strong>
        <small>${esc(corpus.description || corpus.id)}</small>`;
      button.addEventListener("click", () => createSession(corpus.id));
      box.appendChild(button);
    }
  } catch (error) {
    showError(el("pickerError"), `无法加载知识库：${error.message}`);
  }
}

async function createSession(corpusId) {
  clearError(el("pickerError"));
  const dryRun = el("dryRun").checked;
  try {
    const session = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ corpus_id: corpusId, dry_run: dryRun }),
    });
    state.session = session;
    el("picker").hidden = true;
    el("chat").hidden = false;
    el("switchCorpus").hidden = false;
    el("dryRunWrap").hidden = true;
    el("dryBadge").hidden = !session.dry_run;
    el("corpusName").textContent = session.corpus.name;
    el("docCount").textContent = `· ${session.document_count} 篇文档`;
    el("messages").innerHTML = "";
    el("runMeta").textContent = "";
  } catch (error) {
    showError(el("pickerError"), `创建会话失败：${error.message}`);
  }
}

async function switchCorpus() {
  const session = state.session;
  if (!session) return;
  if (state.runs.size && !window.confirm("切换语料会结束当前会话，确定继续？")) {
    return;
  }
  closeAllSources();
  try {
    await api(`/api/sessions/${session.session_id}`, { method: "DELETE" });
  } catch (error) {
    // A dead session is fine here; the UI is moving on anyway.
  }
  state.session = null;
  state.runs.clear();
  state.seen.clear();
  el("chat").hidden = true;
  el("picker").hidden = false;
  el("switchCorpus").hidden = true;
  el("dryRunWrap").hidden = false;
  el("dryBadge").hidden = true;
  el("runMeta").textContent = "";
  await loadCorpora();
}

async function onSubmit(event) {
  event.preventDefault();
  const input = el("query");
  const query = input.value.trim();
  if (!query || !state.session) return;
  clearError(el("chatError"));
  const button = el("askButton");
  button.disabled = true;
  try {
    appendUserBubble(query);
    input.value = "";
    const run = await api(
      `/api/sessions/${state.session.session_id}/ask`,
      { method: "POST", body: JSON.stringify({ query }) }
    );
    state.runs.set(run.run_id, run);
    renderPendingCard(run);
    subscribe(run.run_id);
  } catch (error) {
    showError(el("chatError"), `提交失败：${error.message}`);
  } finally {
    button.disabled = false;
  }
}

function appendUserBubble(text) {
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  el("messages").appendChild(bubble);
  scrollToBottom();
}

function renderPendingCard(run) {
  const card = document.createElement("div");
  card.className = "card";
  card.id = `run-${run.run_id}`;
  card.innerHTML = `
    <div class="card-head"><span class="stage">${STATUS_LABELS[run.status] || run.status}</span></div>
    <div class="progress"><span class="spinner"></span><span>正在检索与核验…</span></div>
    <ul class="trace-lite"></ul>`;
  el("messages").appendChild(card);
  scrollToBottom();
}

function subscribe(runId) {
  const existing = state.sources.get(runId);
  if (existing) existing.close();
  const seen = state.seen.get(runId) || new Set();
  state.seen.set(runId, seen);
  const source = new EventSource(
    `/api/sessions/${state.session.session_id}/runs/${runId}/events`
  );
  state.sources.set(runId, source);
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (seen.has(payload.seq)) return;
      seen.add(payload.seq);
      handleEvent(runId, payload);
    });
  }
}

function closeSource(runId) {
  const source = state.sources.get(runId);
  if (source) {
    source.close();
    state.sources.delete(runId);
  }
}

function closeAllSources() {
  for (const source of state.sources.values()) source.close();
  state.sources.clear();
}

function handleEvent(runId, event) {
  if (event.type === "workflow_stage_changed") {
    updateStage(runId, event.data.message);
  } else if (event.type === "tool_called") {
    appendToolLine(runId, event.data);
  } else if (event.type === "pause") {
    closeSource(runId);
    refreshRun(runId);
  } else if (event.type === "terminal") {
    closeSource(runId);
    refreshRun(runId);
  }
}

function updateStage(runId, message) {
  const card = document.getElementById(`run-${runId}`);
  if (!card) return;
  const stage = card.querySelector(".stage");
  if (!stage) return;
  const match = String(message || "").match(/stage:\s*(\S+)/i);
  stage.textContent = match ? `阶段：${match[1]}` : String(message || "");
}

function appendToolLine(runId, data) {
  const card = document.getElementById(`run-${runId}`);
  if (!card) return;
  const list = card.querySelector(".trace-lite");
  if (!list) return;
  const query = data.query ? ` ${data.query}` : "";
  const item = document.createElement("li");
  item.textContent = `${data.tool_name || "tool"} ${data.path || ""}${query}`;
  list.appendChild(item);
  while (list.children.length > 20) list.removeChild(list.firstChild);
}

async function refreshRun(runId) {
  const session = state.session;
  if (!session) return;
  try {
    const run = await api(
      `/api/sessions/${session.session_id}/runs/${runId}`
    );
    state.runs.set(runId, run);
    renderResult(run);
    el("runMeta").textContent = `最近状态：${STATUS_LABELS[run.status] || run.status}`;
  } catch (error) {
    showError(el("chatError"), `读取运行状态失败：${error.message}`);
  }
}

function renderResult(run) {
  const card = document.getElementById(`run-${run.run_id}`);
  if (!card) return;

  const label = STATUS_LABELS[run.status] || run.status;
  const partial = Boolean(run.is_partial);
  const failed = run.status === "failed";
  let badge = "";
  if (failed) {
    badge = '<span class="badge badge-failed">运行失败</span>';
  } else if (partial) {
    badge = '<span class="badge badge-partial">未通过最终审查</span>';
  } else if (run.status === "completed") {
    badge = '<span class="badge badge-final">已通过审查</span>';
  }

  const answerClass = failed
    ? "answer-failed"
    : partial
    ? "answer-partial"
    : "answer-final";

  const answer = run.answer
    ? `<div class="answer-text">${esc(run.answer)}</div>`
    : `<div class="answer-text muted">${
        failed ? "本次运行没有生成答案。" : "尚无可显示的答案。"
      }</div>`;

  const counts = run.evidence ? run.evidence.length : 0;
  const actions = `
    <div class="card-actions">
      <button type="button" data-action="evidence">证据（${counts}）</button>
      <button type="button" data-action="trace">轨迹</button>
    </div>`;

  card.innerHTML = `
    <div class="card-head"><span>${esc(label)}</span>${badge}</div>
    <div class="${answerClass}">${answer}</div>
    ${run.error ? `<p class="error">${esc(run.error)}</p>` : ""}
    ${actions}`;

  card
    .querySelector('[data-action="evidence"]')
    .addEventListener("click", () => openDrawer(run.run_id, "evidence"));
  card
    .querySelector('[data-action="trace"]')
    .addEventListener("click", () => openDrawer(run.run_id, "trace"));

  if (run.needs_human_input && run.human_request) {
    card.appendChild(renderHitl(run));
  }
  scrollToBottom();
}

function renderHitl(run) {
  const request = run.human_request;
  const section = document.createElement("section");
  section.className = "hitl";
  section.innerHTML = `
    <p><strong>需要补充现场信息</strong></p>
    <p>${esc(request.prompt)}</p>
    <p class="muted">期望输入：${esc(request.expected_input)}</p>
    ${request.reason ? `<p class="muted">原因：${esc(request.reason)}</p>` : ""}
    ${
      request.suggested_command
        ? `<p class="muted">已通过只读门禁的建议命令（请自行执行）：</p><code>${esc(
            request.suggested_command
          )}</code>`
        : ""
    }
    <textarea rows="3" placeholder="粘贴该命令的输出或当前状态…"></textarea>
    <div class="card-actions"><button type="button">提交并继续</button></div>`;

  const button = section.querySelector("button");
  const textarea = section.querySelector("textarea");
  button.addEventListener("click", async () => {
    const content = textarea.value.trim();
    if (!content) return;
    button.disabled = true;
    try {
      await api(
        `/api/sessions/${state.session.session_id}/runs/${run.run_id}/resume`,
        { method: "POST", body: JSON.stringify({ content }) }
      );
      section.remove();
      const card = document.getElementById(`run-${run.run_id}`);
      if (card) {
        const head = card.querySelector(".card-head");
        if (head) head.innerHTML = '<span class="stage">恢复中…</span>';
        const progress = document.createElement("div");
        progress.className = "progress";
        progress.innerHTML =
          '<span class="spinner"></span><span>正在继续诊断…</span>';
        card.appendChild(progress);
      }
      subscribe(run.run_id);
    } catch (error) {
      showError(el("chatError"), `提交现场信息失败：${error.message}`);
      button.disabled = false;
    }
  });
  return section;
}

function openDrawer(runId, tab) {
  const run = state.runs.get(runId);
  if (!run) return;
  el("drawerTitle").textContent =
    tab === "evidence" ? `证据（${run.evidence.length}）` : "检索轨迹";
  el("drawerBody").innerHTML =
    tab === "evidence" ? evidenceHtml(run) : traceHtml(run);
  el("drawer").hidden = false;
  el("scrim").hidden = false;
}

function closeDrawer() {
  el("drawer").hidden = true;
  el("scrim").hidden = true;
}

function evidenceHtml(run) {
  if (!run.evidence.length) {
    return '<p class="muted">本次运行没有已核验证据。</p>';
  }
  return run.evidence
    .map((item) => {
      const location = [item.path, item.line_start]
        .filter((value) => value !== null && value !== undefined)
        .join(":");
      const section = item.section ? ` · 章节 ${esc(item.section)}` : "";
      const version = item.version ? ` · 版本 ${esc(item.version)}` : "";
      const cited = item.cited
        ? '<span class="badge badge-final">草稿引用</span>'
        : '<span class="badge">未引用</span>';
      const obligations = item.supports_obligations.length
        ? `<p class="obligations">对应检索义务：${item.supports_obligations
            .map(esc)
            .join("；")}</p>`
        : '<p class="obligations">未声明检索义务</p>';
      return `<article class="evidence">
        <div class="evidence-head">
          <code>${esc(location)}</code>${cited}
        </div>
        <div class="muted" style="font-size:12px">${esc(item.summary)}${section}${version}</div>
        <blockquote>${esc(item.quote)}</blockquote>
        ${obligations}
      </article>`;
    })
    .join("");
}

function traceHtml(run) {
  const blocks = [];
  const plan = run.plan;
  if (plan) {
    const items = plan.obligations
      .map(
        (obligation, index) => `<div class="plan-item">
          <span class="${obligation.covered ? "ok" : "miss"}">${
          obligation.covered ? "✓" : "✗"
        }</span>
          <span>E${index + 1} ${esc(obligation.text)}</span>
        </div>`
      )
      .join("");
    blocks.push(`<div class="trace-block"><h3>证据义务覆盖</h3>${
      items || '<p class="muted">无检索计划。</p>'
    }</div>`);
  }

  if (run.critic) {
    const critic = run.critic;
    const notes = critic.notes.map((note) => `<li>${esc(note)}</li>`).join("");
    const missing = critic.missing_evidence
      .map((item) => `<li>${esc(item)}</li>`)
      .join("");
    blocks.push(`<div class="trace-block"><h3>Critic 决策：${esc(
      critic.decision
    )}</h3>${notes ? `<ul>${notes}</ul>` : ""}${
      missing ? `<h3>缺失前提</h3><ul>${missing}</ul>` : ""
    }</div>`);
  }

  if (run.trace.length) {
    const rows = run.trace
      .map(
        (step) => `<div class="tool-row">${esc(step.tool)} ${esc(
          step.path
        )}${step.query ? ` · ${esc(step.query)}` : ""}${
          step.summary ? ` → ${esc(step.summary)}` : ""
        }</div>`
      )
      .join("");
    blocks.push(
      `<div class="trace-block"><h3>工具调用（最近 ${run.trace.length} 条）</h3>${rows}</div>`
    );
  }

  const attempts = run.attempts || {};
  blocks.push(`<div class="trace-block"><h3>执行次数</h3>
    <div class="tool-row">Explorer ${attempts.explorer ?? 0} · Reasoner ${
    attempts.reasoner ?? 0
  } · Critic ${attempts.critic ?? 0} · 工作流 ${attempts.workflow ?? 0}</div>
  </div>`);

  if (run.errors && run.errors.length) {
    blocks.push(`<div class="trace-block"><h3>运行说明</h3>${run.errors
      .map((item) => `<div class="tool-row">${esc(item)}</div>`)
      .join("")}</div>`);
  }

  return blocks.join("") || '<p class="muted">暂无轨迹。</p>';
}

function scrollToBottom() {
  const messages = el("messages");
  messages.scrollTop = messages.scrollHeight;
}
