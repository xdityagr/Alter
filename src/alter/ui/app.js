(() => {
  const log = document.getElementById("log");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const status = document.getElementById("status");
  const landing = document.getElementById("landing");
  const header = document.getElementById("header");
  const skillsPopover = document.getElementById("skills-popover");
  const skillsList = document.getElementById("skills-list");
  const commandsPopover = document.getElementById("commands-popover");
  const commandsList = document.getElementById("commands-list");
  const tokenModal = document.getElementById("token-modal");
  const tokenInput = document.getElementById("token-input");
  const tokenSave = document.getElementById("token-save");
  const tokenHelp = document.getElementById("token-help");
  const onboardModal = document.getElementById("onboard-modal");
  const closeOnboard = document.getElementById("close-onboard");
  const onboardStep = document.getElementById("onboard-step");
  const onboardQuestion = document.getElementById("onboard-question");
  const onboardInput = document.getElementById("onboard-input");
  const onboardHint = document.getElementById("onboard-hint");
  const onboardSkip = document.getElementById("onboard-skip");
  const onboardBack = document.getElementById("onboard-back");
  const onboardNext = document.getElementById("onboard-next");

  // State
  let availableTools = [];
  let isLanding = true;
  let skillsActive = false;
  let skillsQuery = "";
  let selectedSkillIndex = 0;
  let commandsActive = false;
  let commandsQuery = "";
  let selectedCommandIndex = 0;
  let reconnectEnabled = true;
  let reconnectTimer = null;

  const availableCommands = [
    { id: "/help", desc: "Show available commands" },
    { id: "/onboard", desc: "Set your preferences" },
    { id: "/remember", desc: "Save a note to memory" },
    { id: "/mem", desc: "Show/search memory" },
    { id: "/profile", desc: "Show derived profile" },
    { id: "/snapshot", desc: "Capture system snapshot" },
    { id: "/summarize", desc: "Generate a rolling summary" },
    { id: "/status", desc: "Show system status" },
    { id: "/settings", desc: "Open settings" },
    { id: "/clear", desc: "Clear chat view" },
  ];

  // Persist API key across refreshes for this origin.
  // Note: localStorage is per-origin, so localhost and ngrok domains do not share it.
  (() => {
    try {
      const u = new URL(location.href);
      const key = u.searchParams.get("key");
      if (key) {
        localStorage.setItem("alter_key", key);
        // Avoid leaving the key in the URL (easier to copy/share safely).
        u.searchParams.delete("key");
        history.replaceState({}, "", u.toString());
      }
    } catch {
      // Ignore (e.g., blocked storage or URL parsing).
    }
  })();

  function showTokenModal(message) {
    if (!tokenModal) return;
    reconnectEnabled = false;
    if (tokenHelp) {
      tokenHelp.textContent = message ||
        "This server requires an API key to use the API + WebSocket. It will be saved in this browser for this URL.";
    }
    tokenModal.classList.remove("hidden");
    if (tokenInput) {
      tokenInput.value = "";
      setTimeout(() => tokenInput.focus(), 0);
    }
  }

  function hideTokenModal() {
    if (!tokenModal) return;
    tokenModal.classList.add("hidden");
  }

  const onboardQuestions = [
    { key: "name", q: "What should I call you?", hint: "Your name or preferred nickname." },
    { key: "role", q: "What is your primary role?", hint: "e.g. Full Stack Dev, Sysadmin, Student." },
    { key: "voice", q: "How should Alter sound? (tone, vibe, humor)", hint: "Example: excited + playful, but calm when listening. Lame jokes ok." },
    { key: "humor", q: "Humor preferences?", hint: "Example: lame jokes sometimes; keep it light; no emojis." },
    { key: "signature_phrases", q: "Any signature phrases I should use sometimes?", hint: "Example: “okay imma add it”, “why is that?”, “idk man, whatever your heart says”." },
    { key: "verbosity", q: "Default verbosity?", hint: "Example: 1-liners by default, structured detail when needed." },
    { key: "formatting", q: "Preferred structure when answering?", hint: "Example: think it through first: need/why/how; then steps." },
    { key: "planning", q: "When should it show a plan?", hint: "Example: only for big tasks." },
    { key: "risk", q: "When unsure, what should it do?", hint: "Example: ask before acting." },
    { key: "tools", q: "Tool policy: auto-run safe tools or always ask?", hint: "Example: auto-run safe tools; ask for risky." },
    { key: "truthfulness", q: "When info is missing, should it say “I don’t know” explicitly?", hint: "Example: yes." },
    { key: "remember_scope", q: "What should it remember by default?", hint: "Example: preferences, key folders, favorite commands/apps." },
    { key: "apps", q: "Top apps/commands you use a lot?", hint: "Example: VS Code, Windows Terminal, conda, rg, docker, WhatsApp." },
    { key: "secrets", q: "What should it never store in memory?", hint: "Example: passwords, tokens, private keys, personal IDs." },
    { key: "stack", q: "Your dev stack (editor, terminal, WSL, Python env mgmt)?", hint: "Example: VS Code, Windows Terminal, WSL sometimes, conda always." },
    { key: "repo_habits", q: "Coding habits?", hint: "Example: minimal changes; refactor after it works; then cleanup." },
    { key: "error_tone", q: "When debugging, tone?", hint: "Example: diagnostic: what I checked + next steps." },
  ];
  let onboardIndex = 0;

  function showOnboard() {
    if (!onboardModal) return;
    if (!getKey()) {
      showTokenModal();
      return;
    }
    onboardIndex = 0;
    onboardModal.classList.remove("hidden");
    renderOnboard();
    setTimeout(() => onboardInput && onboardInput.focus(), 0);
  }

  function hideOnboard() {
    if (!onboardModal) return;
    onboardModal.classList.add("hidden");
  }

  function renderOnboard() {
    const total = onboardQuestions.length;
    const item = onboardQuestions[onboardIndex];
    if (!item) return;
    if (onboardStep) onboardStep.textContent = `STEP ${onboardIndex + 1} / ${total}`;
    if (onboardQuestion) onboardQuestion.textContent = item.q;
    if (onboardHint) onboardHint.textContent = item.hint || "";
    if (onboardBack) onboardBack.disabled = onboardIndex === 0;
    if (onboardNext) onboardNext.textContent = onboardIndex === total - 1 ? "FINISH" : "NEXT";
    if (onboardInput) onboardInput.value = "";
  }

  async function validateAccessToken(key) {
    try {
      const r = await fetch(`/v1/system/status?key=${encodeURIComponent(key)}`);
      if (r.status === 401 || r.status === 403) return false;
      // If the server errors for some other reason, don't block the user from trying to connect.
      return true;
    } catch {
      // Network errors shouldn't prevent saving; connecting will retry.
      return true;
    }
  }

  function updateStatus(text) {
    status.textContent = text;
    status.style.color = text === "connected" ? "var(--accent)" : "red";
  }

  // --- 1. Markdown & UI Helpers ---
  function parseMarkdown(text) {
    if (!text) return "";
    if (window.marked) return window.marked.parse(text);
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function append(kind, text) {
    // Switch to chat view if in landing
    if (isLanding) {
      isLanding = false;
      landing.classList.add("hidden");
      log.classList.remove("hidden");
      header.classList.remove("hidden");
    }

    const wrap = document.createElement("div");
    wrap.className = `msg ${kind}`;

    // User messages get a bubble wrapper
    if (kind === "user") {
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.innerHTML = parseMarkdown(text);
      wrap.appendChild(bubble);
    }
    // Assistant messages are direct
    else if (kind === "assistant") {
      wrap.innerHTML = parseMarkdown(text);
    }
    // Tools
    else {
      wrap.textContent = text;
    }

    log.appendChild(wrap);
    // Auto-scroll
    window.scrollTo(0, document.body.scrollHeight);
    lucide.createIcons();
    return wrap;
  }

  // --- 2. Focus Mode ---
  input.addEventListener("focus", () => {
    header.classList.add("dimmed");
    log.classList.add("dimmed");
    document.querySelector(".composer").style.borderColor = "var(--accent)";
  });

  input.addEventListener("blur", () => {
    // slight delay to allow clicks on popover
    setTimeout(() => {
      header.classList.remove("dimmed");
      log.classList.remove("dimmed");
      document.querySelector(".composer").style.borderColor = "var(--border)";
    }, 200);
  });

  // --- 3. Skills / Tool Fetching ---
  async function fetchTools() {
    if (!getKey()) return;
    try {
      const qs = getKey() ? `?key=${encodeURIComponent(getKey())}` : "";
      const r = await fetch("/v1/tools" + qs);
      if (r.status === 401) {
        showTokenModal("Access token required (or invalid). Please enter the API key to continue.");
        return;
      }
      const d = await r.json();
      availableTools = d.tools || [];
    } catch (e) {
      console.error("Failed to fetch tools", e);
    }
  }

  // --- 4. Skills Parsing & Interaction ---
  function renderSkills() {
    skillsList.innerHTML = "";
    const filtered = availableTools.filter(t =>
      t.id.toLowerCase().includes(skillsQuery.toLowerCase())
    );

    if (filtered.length === 0) {
      skillsPopover.classList.add("hidden");
      return;
    }

    skillsPopover.classList.remove("hidden");

    filtered.forEach((t, i) => {
      const el = document.createElement("div");
      el.className = `skill-item ${i === selectedSkillIndex ? "selected" : ""}`;
      el.innerHTML = `
        <span class="skill-name">@${t.id}</span>
        <span class="skill-desc">${t.description?.substring(0, 30) || ""}...</span>
      `;
      el.onmousedown = (e) => { // use mousedown to prevent blur
        e.preventDefault();
        insertSkill(t.id);
      };
      skillsList.appendChild(el);
    });
  }

  function insertSkill(toolId) {
    const val = input.value;
    // Replace the last "@..." token (only if it starts a token).
    const m = val.match(/^(.*?)(?:^|\\s)@([^\\s]*)$/);
    if (!m) return;

    const before = m[1] || "";
    const sep = before.length > 0 && !before.endsWith(" ") ? " " : "";
    input.value = `${before}${sep}@${toolId} `;
    input.focus();
    skillsActive = false;
    skillsPopover.classList.add("hidden");
  }

  function renderCommands() {
    if (!commandsList || !commandsPopover) return;
    commandsList.innerHTML = "";

    const filtered = availableCommands.filter(c =>
      c.id.toLowerCase().includes(("/" + commandsQuery).toLowerCase())
    );

    if (filtered.length === 0) {
      commandsPopover.classList.add("hidden");
      return;
    }

    commandsPopover.classList.remove("hidden");

    filtered.forEach((c, i) => {
      const el = document.createElement("div");
      el.className = `cmd-item ${i === selectedCommandIndex ? "selected" : ""}`;
      el.innerHTML = `
        <span class="cmd-name">${c.id}</span>
        <span class="cmd-desc">${(c.desc || "").substring(0, 36)}...</span>
      `;
      el.onmousedown = (e) => {
        e.preventDefault();
        insertCommand(c.id);
      };
      commandsList.appendChild(el);
    });
  }

  function insertCommand(cmd) {
    input.value = `${cmd} `;
    input.focus();
    commandsActive = false;
    if (commandsPopover) commandsPopover.classList.add("hidden");
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      if (commandsActive) {
        e.preventDefault();
        const filtered = availableCommands.filter(c =>
          c.id.toLowerCase().includes(("/" + commandsQuery).toLowerCase())
        );
        if (filtered[selectedCommandIndex]) {
          insertCommand(filtered[selectedCommandIndex].id);
        } else {
          commandsActive = false;
          if (commandsPopover) commandsPopover.classList.add("hidden");
          sendMsg();
        }
      } else if (skillsActive) {
        // Select current skill
        e.preventDefault();
        const filtered = availableTools.filter(t => t.id.toLowerCase().includes(skillsQuery.toLowerCase()));
        if (filtered[selectedSkillIndex]) {
          insertSkill(filtered[selectedSkillIndex].id);
        } else {
          // No specific skill selected, just send? Or close?
          skillsActive = false;
          skillsPopover.classList.add("hidden");
          sendMsg();
        }
      } else {
        e.preventDefault();
        sendMsg();
      }
      return;
    }

    if (commandsActive) {
      if (e.key === "ArrowUp") {
        e.preventDefault();
        selectedCommandIndex = Math.max(0, selectedCommandIndex - 1);
        renderCommands();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        const max = availableCommands.filter(c =>
          c.id.toLowerCase().includes(("/" + commandsQuery).toLowerCase())
        ).length - 1;
        selectedCommandIndex = Math.min(max, selectedCommandIndex + 1);
        renderCommands();
      } else if (e.key === "Escape") {
        commandsActive = false;
        if (commandsPopover) commandsPopover.classList.add("hidden");
      } else if (e.key === "Tab") {
        e.preventDefault();
        const filtered = availableCommands.filter(c =>
          c.id.toLowerCase().includes(("/" + commandsQuery).toLowerCase())
        );
        if (filtered.length > 0) insertCommand(filtered[selectedCommandIndex || 0].id);
      }
    } else if (skillsActive) {
      if (e.key === "ArrowUp") {
        e.preventDefault();
        selectedSkillIndex = Math.max(0, selectedSkillIndex - 1);
        renderSkills();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        const max = availableTools.filter(t => t.id.toLowerCase().includes(skillsQuery.toLowerCase())).length - 1;
        selectedSkillIndex = Math.min(max, selectedSkillIndex + 1);
        renderSkills();
      } else if (e.key === "Escape") {
        skillsActive = false;
        skillsPopover.classList.add("hidden");
      } else if (e.key === " " || e.key === "Tab") {
        // Tab autocompletes if 1 match?
        if (e.key === "Tab") {
          e.preventDefault();
          const filtered = availableTools.filter(t => t.id.toLowerCase().includes(skillsQuery.toLowerCase()));
          if (filtered.length > 0) insertSkill(filtered[selectedSkillIndex || 0].id);
        }
      }
    }
  });

  input.addEventListener("input", (e) => {
    const val = input.value;

    // Slash commands: active when input starts with '/' and no args yet (no space).
    if (val.startsWith("/")) {
      const after = val.substring(1);
      if (!after.includes(" ")) {
        commandsActive = true;
        commandsQuery = after;
        selectedCommandIndex = 0;
        renderCommands();
        // Disable skills popover while in slash mode.
        skillsActive = false;
        skillsPopover.classList.add("hidden");
        return;
      }
    }

    // Tool mentions: only when "@..." is a token start (avoid emails like a@b.com)
    // Match the last occurrence of whitespace/start + "@" + non-space chars without spaces after.
    const m = val.match(/(?:^|\\s)@([^\\s]*)$/);
    if (m) {
      skillsActive = true;
      skillsQuery = m[1] || "";
      selectedSkillIndex = 0;
      renderSkills();
      return;
    }

    commandsActive = false;
    if (commandsPopover) commandsPopover.classList.add("hidden");
    skillsActive = false;
    skillsPopover.classList.add("hidden");
  });

  // --- 5. Core Chat Logic ---

  function getKey() {
    const saved = localStorage.getItem("alter_key");
    return new URLSearchParams(location.search).get("key") || saved || "";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setToolIcon(toolExecutingEl, icon, { spin = false, breathe = false } = {}) {
    if (!toolExecutingEl) return;
    const existing = toolExecutingEl.querySelector("svg,i[data-lucide]");
    const i = document.createElement("i");
    i.setAttribute("data-lucide", icon);
    if (spin) i.classList.add("animate-spin");
    if (breathe) i.classList.add("animate-breathe");
    if (existing) existing.replaceWith(i);
    else toolExecutingEl.prepend(i);
    lucide.createIcons();
  }

  function appendToolExecution(data) {
    markToolsComplete();
    const el = document.createElement("div");
    el.className = "msg tool";
    const toolId = escapeHtml(data.tool_id);
    const isWeb = data.tool_id && data.tool_id.startsWith("web.");
    const iconName = isWeb ? "globe" : "loader";
    const animClass = isWeb ? "animate-breathe" : "animate-spin";
    el.innerHTML = `
       <div class="tool-executing" data-tool-id="${toolId}" data-request-id="${escapeHtml(data.request_id || '')}">
         <i data-lucide="${iconName}" class="${animClass}"></i>
         <span class="tool-label tool-progress-text">Running <strong>${toolId}</strong>...</span>
       </div>
     `;
    log.appendChild(el);
    window.scrollTo(0, document.body.scrollHeight);
    lucide.createIcons();
  }

  function markToolsComplete() {
    // Find active spinners
    document.querySelectorAll(".tool-executing:not(.done)").forEach(el => {
      el.classList.add("done");
      const toolId = el.getAttribute("data-tool-id") || "";
      const label = el.querySelector(".tool-label");
      if (label) {
        label.innerHTML = `Ran <strong>${escapeHtml(toolId)}</strong>`;
      }
      setToolIcon(el, "check", { spin: false });
    });
  }

  function connect() {
    if (!getKey()) {
      updateStatus("auth required");
      showTokenModal();
      return;
    }

    reconnectEnabled = true;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    // Close any previous socket without triggering its reconnect loop.
    if (window._ws) {
      try {
        window._ws.onclose = null;
        window._ws.close();
      } catch { }
    }

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const qs = getKey() ? `?key=${encodeURIComponent(getKey())}` : "";
    const ws = new WebSocket(`${proto}://${location.host}/v1/events${qs}`);

    ws.onopen = () => updateStatus("connected");
    ws.onclose = (ev) => {
      // If no key (or it got cleared), stop reconnecting and prompt.
      if (!getKey()) {
        updateStatus("auth required");
        showTokenModal();
        return;
      }

      // Server rejects WS auth with code 4401.
      if (ev && ev.code === 4401) {
        updateStatus("auth failed");
        try { localStorage.removeItem("alter_key"); } catch { }
        showTokenModal("Access token rejected. Please enter the correct API key.");
        return;
      }

      updateStatus("disconnected");
      if (!reconnectEnabled) return;
      reconnectTimer = setTimeout(connect, 2000);
    };

    let currentStreamDiv = null;

    ws.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }

      if (data.type === "token") {
        hideLoader(); // First token hides the loader
        markToolsComplete();
        if (!currentStreamDiv) currentStreamDiv = append("assistant", "");

        currentStreamDiv._raw = (currentStreamDiv._raw || "") + data.content;
        // Append cursor inside markdown parsing so it stays inline (if marked allows HTML)
        // or effectively at the end of the content.
        // Note: transforming raw text ensures it ends up inside the last <p> if applicable.
        currentStreamDiv.innerHTML = parseMarkdown(currentStreamDiv._raw + '<span class="typing-cursor"></span>');

        window.scrollTo(0, document.body.scrollHeight);
      }
      else if (data.type === "assistant") {
        hideLoader(); // Full response hides loader
        markToolsComplete();
        // Remove cursor from stream div if it exists
        if (currentStreamDiv) {
          currentStreamDiv.innerHTML = parseMarkdown(currentStreamDiv._raw || data.content); // Remove cursor
          currentStreamDiv = null;
        } else {
          append("assistant", data.content);
        }
      }
      else if (data.type === "tool_executing") {
        hideLoader(); // Tool execution hides loader (replaces with tool spinner)
        appendToolExecution(data);
      }
      else if (data.type === "tool_request") {
        hideLoader();
        // Confirm logic reused from previous, but simplified style
        const autoConfirm = localStorage.getItem("alter_auto_confirm") === "true";
        if (autoConfirm && data.confirm_required) {
          ws.send(JSON.stringify({ type: "confirm", request_id: data.request_id, allow: true }));
          append("tool", `Auto-allowed ${data.tool_id}`);
        } else {
          showConfirmCard(data, ws);
        }
      }
      else if (data.type === "tool_progress") {
        // Update the most recent active tool card with progress text
        const active = document.querySelector(".tool-executing:not(.done)");
        if (active) {
          const label = active.querySelector(".tool-label");
          if (label) {
            const toolId = active.getAttribute("data-tool-id") || "";
            label.innerHTML = `<strong>${escapeHtml(toolId)}</strong> <span class="progress-detail">${escapeHtml(data.message || "")}</span>`;
          }
        }
        window.scrollTo(0, document.body.scrollHeight);
      }
      else if (data.type === "error") {
        hideLoader();
        markToolsComplete();
        append("tool", `Error: ${data.message || "Unknown error"}`);
      }
    };

    window._ws = ws; // Expose for sendMsg
  }

  // --- Loader Logic ---
  let loaderEl = null;

  function showLoader() {
    if (loaderEl) return; // Already showing

    loaderEl = document.createElement("div");
    loaderEl.className = "loader-container";
    loaderEl.innerHTML = `
      <div class="loader">
        <div class="square"></div>
        <div class="square"></div>
        <div class="square"></div>
      </div>
    `;
    log.appendChild(loaderEl);
    window.scrollTo(0, document.body.scrollHeight);
  }

  function hideLoader() {
    if (loaderEl) {
      loaderEl.remove();
      loaderEl = null;
    }
  }

  function showConfirmCard(tr, ws) {
    const div = document.createElement("div");
    div.className = "msg tool";
    div.innerHTML = `
        <div class="tool-card">
           <div><strong>Request:</strong> ${tr.tool_id}</div>
           <pre>${JSON.stringify(tr.inputs, null, 2)}</pre>
           <div style="display:flex; gap:1rem; margin-top:0.5rem">
             <button class="btn-allow">ALLOW</button>
             <button class="btn-deny" style="color:#f87171; border-color:#333">DENY</button>
           </div>
        </div>
      `;

    div.querySelector(".btn-allow").onclick = () => {
      ws.send(JSON.stringify({ type: "confirm", request_id: tr.request_id, allow: true }));
      div.remove();
      append("tool", `Allowed ${tr.tool_id}`);
    };

    div.querySelector(".btn-deny").onclick = () => {
      ws.send(JSON.stringify({ type: "confirm", request_id: tr.request_id, allow: false }));
      div.remove();
      append("tool", `Denied ${tr.tool_id}`);
    };

    log.appendChild(div);
    window.scrollTo(0, document.body.scrollHeight);
  }

  async function handleSlashCommand(raw) {
    const parts = raw.trim().split(" ");
    const cmd = (parts[0] || "").toLowerCase();
    const args = parts.slice(1).join(" ").trim();

    const key = getKey();
    const qs = key ? `?key=${encodeURIComponent(key)}` : "";

    if (cmd === "/help") {
      append("assistant",
        [
          "**Commands**",
          "- `/help` — show commands",
          "- `/onboard` — answer a few questions to personalize Alter",
          "- `/remember <note>` — save a note to memory",
          "- `/mem [query]` — show recent memory or search",
          "- `/profile` — show derived profile (evidence-linked)",
          "- `/snapshot` — capture a safe system snapshot to memory",
          "- `/summarize` — generate a rolling summary (for long runs)",
          "- `/status` — show backend/model status",
          "- `/settings` — open settings",
          "- `/clear` — clear chat view",
        ].join("\n")
      );
      return true;
    }

    if (cmd === "/onboard") {
      showOnboard();
      return true;
    }

    if (cmd === "/clear") {
      // Keep connection/session; just clear rendered chat.
      log.innerHTML = "";
      append("assistant", "Cleared.");
      return true;
    }

    if (cmd === "/settings") {
      const btn = document.getElementById("settings-btn");
      if (btn) btn.click();
      return true;
    }

    if (cmd === "/status") {
      if (!key) {
        showTokenModal();
        return true;
      }
      try {
        const s = await fetch("/v1/system/status" + qs).then(r => r.json());
        const backend = s?.model?.backend || "?";
        const model = s?.model?.model_path || s?.model?.model || "?";
        append("assistant", `Backend: **${backend}**\nModel: **${model}**`);
      } catch (e) {
        append("tool", "Error: failed to fetch status");
      }
      return true;
    }

    if (cmd === "/snapshot") {
      if (!key) {
        showTokenModal();
        return true;
      }
      try {
        const r = await fetch("/v1/system/snapshot" + qs, { method: "POST" });
        if (r.status === 401 || r.status === 403) {
          try { localStorage.removeItem("alter_key"); } catch { }
          showTokenModal("Access token required (or invalid). Please enter the API key to continue.");
          return true;
        }
        if (!r.ok) {
          let msg = "Snapshot failed.";
          try {
            const err = await r.json();
            msg = err?.detail || msg;
          } catch { }
          append("tool", `Error: ${msg}`);
          return true;
        }
        const d = await r.json();
        append("assistant", `Snapshot saved: \`${d.mem_id}\``);
      } catch (e) {
        append("tool", "Error: failed to capture snapshot");
      }
      return true;
    }

    if (cmd === "/profile") {
      if (!key) {
        showTokenModal();
        return true;
      }
      try {
        const r = await fetch("/v1/profile" + qs);
        if (r.status === 401 || r.status === 403) {
          try { localStorage.removeItem("alter_key"); } catch { }
          showTokenModal("Access token required (or invalid). Please enter the API key to continue.");
          return true;
        }
        if (!r.ok) {
          let msg = "Failed to load profile.";
          try {
            const err = await r.json();
            msg = err?.detail || msg;
          } catch { }
          append("tool", `Error: ${msg}`);
          return true;
        }
        const d = await r.json();
        const lines = (d?.lines || []).slice(0, 14);
        if (lines.length === 0) {
          append("assistant", "Profile is empty. Run `/onboard` and `/snapshot`.");
          return true;
        }
        append("assistant", ["**User Profile**", ...lines].join("\n"));
      } catch (e) {
        append("tool", "Error: failed to load profile");
      }
      return true;
    }

    if (cmd === "/summarize") {
      if (!key) {
        showTokenModal();
        return true;
      }
      try {
        const r = await fetch("/v1/memory/summarize" + qs, { method: "POST" });
        if (r.status === 401 || r.status === 403) {
          try { localStorage.removeItem("alter_key"); } catch { }
          showTokenModal("Access token required (or invalid). Please enter the API key to continue.");
          return true;
        }
        if (!r.ok) {
          let msg = "Summary failed.";
          try {
            const err = await r.json();
            msg = err?.detail || msg;
          } catch { }
          append("tool", `Error: ${msg}`);
          return true;
        }
        const d = await r.json();
        const content = (d?.content || "").trim();
        if (content) {
          append("assistant", ["**Summary Updated**", content].join("\n"));
        } else {
          append("assistant", `Summary saved: \`${d.mem_id}\``);
        }
      } catch {
        append("tool", "Error: failed to summarize");
      }
      return true;
    }

    if (cmd === "/remember") {
      if (!args) {
        append("assistant", "Usage: `/remember <note>`");
        return true;
      }
      if (!key) {
        showTokenModal();
        return true;
      }
      try {
        const r = await fetch("/v1/memory/remember" + qs, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: args, meta: { source: "slash" } }),
        });
        if (r.status === 401 || r.status === 403) {
          try { localStorage.removeItem("alter_key"); } catch { }
          showTokenModal("Access token required (or invalid). Please enter the API key to continue.");
          return true;
        }
        if (!r.ok) {
          let msg = "Failed to save memory.";
          try {
            const err = await r.json();
            msg = err?.detail || msg;
          } catch { }
          append("tool", `Error: ${msg}`);
          return true;
        }
        const d = await r.json();
        if (d && d.mem_id) {
          append("assistant", `Saved to memory: \`${d.mem_id}\``);
        } else {
          append("assistant", "Saved to memory.");
        }
      } catch (e) {
        append("tool", "Error: failed to save memory");
      }
      return true;
    }

    if (cmd === "/mem") {
      if (!key) {
        showTokenModal();
        return true;
      }
      try {
        let url = "/v1/memory/recent" + qs + "&limit=10";
        if (!qs) url = "/v1/memory/recent?limit=10";
        if (args) {
          url = `/v1/memory/search${qs ? qs + "&" : "?"}q=${encodeURIComponent(args)}&limit=10`;
        }
        const r = await fetch(url);
        if (r.status === 401 || r.status === 403) {
          try { localStorage.removeItem("alter_key"); } catch { }
          showTokenModal("Access token required (or invalid). Please enter the API key to continue.");
          return true;
        }
        if (!r.ok) {
          let msg = "Failed to read memory.";
          try {
            const err = await r.json();
            msg = err?.detail || msg;
          } catch { }
          append("tool", `Error: ${msg}`);
          return true;
        }
        const d = await r.json();
        const events = d?.events || [];
        if (events.length === 0) {
          append("assistant", args ? "No memory hits." : "No memory yet.");
          return true;
        }
        const title = args ? `**Memory (search: ${args})**` : "**Memory (recent)**";
        const lines = [title];
        events.forEach(e => {
          const id = (e.id || "").slice(0, 8);
          const kind = e.kind || "unknown";
          const content = String(e.content || "").replace(/\s+/g, " ").trim().slice(0, 140);
          lines.push(`- \`${kind}\` \`${id}\` ${content}`);
        });
        append("assistant", lines.join("\n"));
      } catch (e) {
        append("tool", "Error: failed to read memory");
      }
      return true;
    }

    append("assistant", `Unknown command: \`${cmd}\`. Try \`/help\`.`);
    return true;
  }

  function sendMsg() {
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    input.blur();

    if (text.startsWith("/")) {
      handleSlashCommand(text);
      return;
    }

    append("user", text);
    showLoader();

    if (window._ws && window._ws.readyState === WebSocket.OPEN) {
      window._ws.send(JSON.stringify({ type: "chat", message: text }));
    } else {
      hideLoader();
      append("tool", "Error: Offline");
    }
  }

  // Bindings
  send.onclick = sendMsg;
  document.getElementById("landing").querySelector(".suggestions").addEventListener("click", (e) => {
    if (e.target.classList.contains("suggestion-chip")) {
      input.value = e.target.textContent;
      input.focus();
    }
  });

  // --- 6. Settings & Models ---
  const settingsBtn = document.getElementById("settings-btn");
  const modal = document.getElementById("settings-modal");
  const closeBtn = document.getElementById("close-settings");
  const saveBtn = document.getElementById("save-settings");
  const providerSel = document.getElementById("provider-select");
  const modelSel = document.getElementById("model-select");
  const currentModelDisplay = document.getElementById("current-model-display");
  const autoConfirmCheck = document.getElementById("auto-confirm-check");

  // Open Settings
  settingsBtn.onclick = async () => {
    modal.classList.remove("hidden");

    // Load Auto Confirm state
    const autoConfirm = localStorage.getItem("alter_auto_confirm") === "true";
    autoConfirmCheck.checked = autoConfirm;

    // Load current provider
    const qs = getKey() ? `?key=${encodeURIComponent(getKey())}` : "";
    try {
      const s = await fetch("/v1/system/status" + qs).then(r => r.json());
      if (s.model && s.model.backend) {
        providerSel.value = s.model.backend;
      }
      if (currentModelDisplay && s.model) {
        currentModelDisplay.textContent = `Currently active: ${s.model.model || s.model.model_path} (${s.model.backend})`;
      }
    } catch (e) { }
    loadModels();
  };

  closeBtn.onclick = () => modal.classList.add("hidden");
  providerSel.onchange = loadModels;

  async function loadModels() {
    modelSel.innerHTML = "<option>Loading...</option>";
    const provider = providerSel.value;
    const key = getKey();
    const prefix = key ? `?key=${encodeURIComponent(key)}&` : "?";

    try {
      // 1. Fetch Status to know active (redundant but safe)
      const qs = key ? `?key=${encodeURIComponent(getKey())}` : "";
      const s = await fetch("/v1/system/status" + qs).then(r => r.json());
      // Handle different naming conventions in status vs config
      const currentModel = s.model ? (s.model.model || s.model.model_path) : "";

      // 2. Fetch list
      const r = await fetch(`/v1/models${prefix}backend=${provider}`);
      const d = await r.json();

      modelSel.innerHTML = "";

      const models = d.models || [];
      if (models.length === 0) {
        const opt = document.createElement("option");
        opt.textContent = "No models found";
        modelSel.appendChild(opt);
      }

      let found = false;
      models.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m.id;
        opt.textContent = m.name;
        // Check exact match or if current model identifier is contained
        if (m.id === currentModel) {
          opt.selected = true;
          found = true;
        }
        modelSel.appendChild(opt);
      });

      // If we didn't find the current model in the list, but we are on the active backend, append it
      // Make sure we are viewing the backend that is actually active
      if (!found && s.model && s.model.backend === provider && currentModel) {
        const opt = document.createElement("option");
        opt.value = currentModel;
        opt.textContent = `${currentModel} (Current)`;
        opt.selected = true;
        modelSel.prepend(opt);
      }

    } catch (e) {
      modelSel.innerHTML = "<option>Error loading models</option>";
      console.error(e);
    }
  }

  saveBtn.onclick = async () => {
    const backend = providerSel.value;
    const model = modelSel.value;
    const auto = document.getElementById("auto-confirm-check").checked;

    localStorage.setItem("alter_auto_confirm", auto);

    const qs = getKey() ? `?key=${encodeURIComponent(getKey())}` : "";

    try {
      await fetch("/v1/system/model" + qs, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend, model })
      });
      modal.classList.add("hidden");

      // Notify via chat
      append("assistant", `System updated: Using **${model}** via **${backend}**.`);

      // Update local state if needed
      window._activeModel = model;
      if (document.querySelector("#status").textContent === "connected") {
        // trigger status update? easiest is just wait for next ping or connection
      }
    } catch (e) {
      alert("Failed to update settings: " + e);
    }
  };

  // --- 7. Global Shortcuts ---
  document.addEventListener("keydown", (e) => {
    // If user is typing in an input/textarea, ignore shortcuts (except Esc)
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
      if (e.key === "Escape") {
        e.target.blur();
      }
      return;
    }

    // Ignore shortcuts if auth modal is open
    if (tokenModal && !tokenModal.classList.contains("hidden")) {
      return;
    }

    if (onboardModal && !onboardModal.classList.contains("hidden")) {
      return;
    }

    // Ignore if modal is open (except allowing Esc to close it, handled by modal logic or here?)
    if (!modal.classList.contains("hidden")) {
      if (e.key === "Escape") modal.classList.add("hidden");
      return;
    }

    if (e.key === "/" || e.key === "?") {
      e.preventDefault();
      input.focus();
    }

    if (e.key === "s" || e.key === "S") {
      // Prevent if any modifier keys or within input
      if (e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        // Toggle instead of just open
        if (modal.classList.contains("hidden")) {
          modal.classList.remove("hidden");
          settingsBtn.click(); // Trigger load logic
        } else {
          modal.classList.add("hidden");
        }
      }
    }
  });

  // Init
  if (tokenSave && tokenInput) {
    const doSave = async () => {
      const key = tokenInput.value.trim();
      if (!key) return tokenInput.focus();

      tokenSave.disabled = true;
      const prev = tokenHelp ? tokenHelp.textContent : "";
      if (tokenHelp) tokenHelp.textContent = "Validating…";

      const ok = await validateAccessToken(key);
      tokenSave.disabled = false;

      if (!ok) {
        showTokenModal("Access token rejected. Please enter the correct API key.");
        return;
      }

      try { localStorage.setItem("alter_key", key); } catch { }
      hideTokenModal();
      fetchTools();
      connect();
      if (tokenHelp) tokenHelp.textContent = prev;
    };

    tokenSave.onclick = doSave;
    tokenInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        doSave();
      }
    });
  }

  if (closeOnboard) closeOnboard.onclick = hideOnboard;
  if (onboardSkip) onboardSkip.onclick = async () => {
    const total = onboardQuestions.length;
    if (onboardIndex >= total - 1) {
      hideOnboard();
      append("assistant", "Onboard complete. Consider running `/snapshot` next.");
      return;
    }
    onboardIndex += 1;
    renderOnboard();
  };

  if (onboardBack) onboardBack.onclick = () => {
    onboardIndex = Math.max(0, onboardIndex - 1);
    renderOnboard();
  };

  async function saveOnboardAnswer() {
    const item = onboardQuestions[onboardIndex];
    if (!item) return;
    const key = getKey();
    if (!key) {
      showTokenModal();
      return;
    }
    const qs = `?key=${encodeURIComponent(key)}`;
    const answer = (onboardInput && onboardInput.value || "").trim();
    if (!answer) {
      // Allow skipping empty answers.
      if (onboardSkip) onboardSkip.click();
      return;
    }
    try {
      const r = await fetch("/v1/memory/remember" + qs, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: answer,
          meta: { source: "onboard", profile_key: item.key, question: item.q }
        }),
      });
      if (!r.ok) {
        // If auth broke mid-onboard, prompt.
        if (r.status === 401 || r.status === 403) {
          try { localStorage.removeItem("alter_key"); } catch { }
          showTokenModal("Access token required (or invalid). Please enter the API key to continue.");
        } else {
          append("tool", "Error: failed to save onboarding answer");
        }
        return;
      }
    } catch {
      append("tool", "Error: failed to save onboarding answer");
      return;
    }

    const total = onboardQuestions.length;
    if (onboardIndex >= total - 1) {
      hideOnboard();
      append("assistant", "Onboard complete. Run `/snapshot` to capture system context.");
      return;
    }
    onboardIndex += 1;
    renderOnboard();
  }

  if (onboardNext) onboardNext.onclick = saveOnboardAnswer;
  if (onboardInput) {
    onboardInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        saveOnboardAnswer();
      } else if (e.key === "Escape") {
        hideOnboard();
      }
    });
  }

  if (!getKey()) {
    updateStatus("auth required");
    showTokenModal();
  } else {
    async function fetchWelcome() {
      if (!getKey()) return;

      const titleEl = document.getElementById("welcome-subtitle");
      const gridEl = document.getElementById("prompt-grid");
      const cacheKey = "alter_welcome_v1";

      const typeTitle = (text) => {
        if (!titleEl) return;
        titleEl.classList.remove("skeleton", "skeleton-text");

        // Clear any ongoing animation
        if (titleEl.dataset.typingInterval) {
          clearInterval(parseInt(titleEl.dataset.typingInterval));
        }

        const currentText = titleEl.textContent;
        if (currentText === text) return; // No change needed

        // Helper to start typing new text
        const startTyping = () => {
          titleEl.textContent = "";
          let i = 0;
          const typeInterval = setInterval(() => {
            titleEl.textContent += text.charAt(i);
            i++;
            if (i >= text.length) clearInterval(typeInterval);
          }, 40);
          titleEl.dataset.typingInterval = typeInterval;
        };

        // If generic/empty, just type. If replacing, backspace first.
        if (!currentText || currentText === "LOADING INTELLIGENCE") {
          startTyping();
        } else {
          // Backspace effect
          let len = currentText.length;
          const delInterval = setInterval(() => {
            titleEl.textContent = currentText.substring(0, len);
            len--;
            if (len < 0) {
              clearInterval(delInterval);
              setTimeout(startTyping, 200); // Wait 200ms before typing
            }
          }, 20); // Faster delete
          titleEl.dataset.typingInterval = delInterval;
        }
      };

      const renderPrompts = (prompts) => {
        if (!gridEl || !prompts || !Array.isArray(prompts)) return;
        gridEl.innerHTML = "";
        prompts.forEach((p, index) => {
          const btn = document.createElement("button");
          btn.className = "suggestion-chip";
          btn.style.animation = `slideUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.1}s both`;
          btn.innerText = p;
          btn.onclick = () => {
            input.value = p;
            input.focus();
          };
          gridEl.appendChild(btn);
        });
      };

      // Rotation Logic
      const startRotation = (titles) => {
        if (!titles || titles.length === 0) return;

        // Clear existing rotation if any
        if (titleEl.dataset.rotationInterval) {
          clearInterval(parseInt(titleEl.dataset.rotationInterval));
        }

        let index = 0;
        // Show first one immediately if not already showing? 
        // Actually, cache logic shows one. Fetch logic shows one.
        // We should just ensure we rotate from current.

        const interval = setInterval(() => {
          index = (index + 1) % titles.length;
          typeTitle(titles[index]);
        }, 10000); // 10 secs

        titleEl.dataset.rotationInterval = interval;
      };

      // 1. Immediate Load (Cache or Seed)
      let currentTitles = [];
      try {
        const cached = localStorage.getItem(cacheKey);
        if (cached) {
          const data = JSON.parse(cached);

          // Handle legacy single title cache vs new array
          if (data.titles && Array.isArray(data.titles)) {
            currentTitles = data.titles;
            typeTitle(currentTitles[0]);
            startRotation(currentTitles);
          } else if (data.title) {
            // Legacy fallback
            typeTitle(data.title);
          }

          // Do NOT render cached prompts.
        } else {
          typeTitle("ALTER EGO");
        }
      } catch (e) { console.error(e); }

      // 2. Network Fetch
      try {
        const qs = getKey() ? `?key=${encodeURIComponent(getKey())}` : "";
        const r = await fetch("/v1/system/welcome" + qs);
        if (!r.ok) return;
        const data = await r.json();

        localStorage.setItem(cacheKey, JSON.stringify(data));

        if (data.titles && Array.isArray(data.titles) && data.titles.length > 0) {
          // If we have new titles, update UI.
          // Type the first one immediately? Or wait for rotation?
          // User wants "smooth transition".
          // If we just loaded cache, we are showing cache[0]. 
          // If new data comes, we should probably switch to new[0] immediately using backspace logic.
          typeTitle(data.titles[0]);
          startRotation(data.titles);
        }

        if (data.prompts) {
          renderPrompts(data.prompts);
        }
      } catch (e) {
        console.error("Welcome fetch failed", e);
      }
    }

    // Init
    fetchTools();
    fetchWelcome();
    connect();
  }
  lucide.createIcons();

})();
