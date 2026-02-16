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
  const autoConfirmCheck = document.getElementById("auto-confirm-check");
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
    { id: "/reset", desc: "Reset all memory" },
  ];

  // ══════════════════════════════════════════════════════
  // WebGL Aurora Background Renderer
  const AURORA_THEMES = {
    // Dark Themes (Deep Black / Subtle Gradient)
    'void': { colors: [0.05, 0.02, 0.10, 0.02, 0.08, 0.12, 0.08, 0.04, 0.15] },
    'ember': { colors: [0.12, 0.02, 0.02, 0.15, 0.08, 0.01, 0.15, 0.05, 0.08] },
    'arctic': { colors: [0.00, 0.08, 0.10, 0.01, 0.05, 0.12, 0.04, 0.08, 0.15] },
    'pure': { colors: [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00] },

    // Light Themes (Bright / Original Intensity)
    'void-light': { colors: [0.42, 0.13, 0.66, 0.05, 0.65, 0.91, 0.55, 0.36, 0.96] },
    'ember-light': { colors: [0.86, 0.15, 0.15, 0.96, 0.62, 0.04, 0.98, 0.44, 0.52] },
    'arctic-light': { colors: [0.02, 0.71, 0.83, 0.23, 0.51, 0.96, 0.58, 0.77, 0.99] },
    'pure-light': { colors: [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00] },
  };

  function initAurora() {
    const canvas = document.getElementById('aurora-bg');
    if (!canvas) return;
    const gl = canvas.getContext('webgl');
    if (!gl) return;

    // Respect reduced motion
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (mq.matches) { canvas.style.display = 'none'; return; }

    const vsSource = `
      attribute vec4 aVertexPosition;
      void main() {
        gl_Position = aVertexPosition;
      }
    `;

    const fsSource = `
      precision mediump float;
      uniform vec2 u_resolution;
      uniform float u_time;
      uniform vec3 u_c1;
      uniform vec3 u_c2;
      uniform vec3 u_c3;

      vec3 permute(vec3 x) { return mod(((x*34.0)+1.0)*x, 289.0); }
      float snoise(vec2 v){
        const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                 -0.577350269189626, 0.024390243902439);
        vec2 i  = floor(v + dot(v, C.yy) );
        vec2 x0 = v - i + dot(i, C.xx);
        vec2 i1;
        i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
        vec4 x12 = x0.xyxy + C.xxzz;
        x12.xy -= i1;
        i = mod(i, 289.0);
        vec3 p = permute( permute( i.y + vec3(0.0, i1.y, 1.0 ))
        + i.x + vec3(0.0, i1.x, 1.0 ));
        vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy), dot(x12.zw,x12.zw)), 0.0);
        m = m*m ;
        m = m*m ;
        vec3 x = 2.0 * fract(p * C.www) - 1.0;
        vec3 h = abs(x) - 0.5;
        vec3 ox = floor(x + 0.5);
        vec3 a0 = x - ox;
        m *= 1.79284291400159 - 0.85373472095314 * ( a0*a0 + h*h );
        vec3 g;
        g.x  = a0.x  * x0.x  + h.x  * x0.y;
        g.yz = a0.yz * x12.xz + h.yz * x12.yw;
        return 130.0 * dot(m, g);
      }

      void main() {
        vec2 st = gl_FragCoord.xy/u_resolution.xy;
        float t = u_time * 0.1;
        
        float n1 = snoise(vec2(st.x * 0.6 + t, st.y * 0.6 - t));
        float n2 = snoise(vec2(st.x * 1.0 - t * 0.5, st.y * 1.0 + t * 0.5));
        
        vec3 color = mix(u_c1, u_c2, smoothstep(-0.3, 0.7, n1));
        color = mix(color, u_c3, smoothstep(-0.4, 0.6, n2));
        
        float dist = distance(st, vec2(0.5));
        color *= 1.0 - dist * 0.5;
        
        gl_FragColor = vec4(color, 1.0);
      }
    `;

    function initShaderProgram(gl, vs, fs) {
      const v = loadShader(gl, gl.VERTEX_SHADER, vs);
      const f = loadShader(gl, gl.FRAGMENT_SHADER, fs);
      const p = gl.createProgram();
      gl.attachShader(p, v);
      gl.attachShader(p, f);
      gl.linkProgram(p);
      return p;
    }

    function loadShader(gl, type, source) {
      const s = gl.createShader(type);
      gl.shaderSource(s, source);
      gl.compileShader(s);
      return s;
    }

    const shaderProgram = initShaderProgram(gl, vsSource, fsSource);
    const programInfo = {
      program: shaderProgram,
      attribLocations: {
        vertexPosition: gl.getAttribLocation(shaderProgram, 'aVertexPosition'),
      },
      uniformLocations: {
        resolution: gl.getUniformLocation(shaderProgram, 'u_resolution'),
        time: gl.getUniformLocation(shaderProgram, 'u_time'),
        c1: gl.getUniformLocation(shaderProgram, 'u_c1'),
        c2: gl.getUniformLocation(shaderProgram, 'u_c2'),
        c3: gl.getUniformLocation(shaderProgram, 'u_c3'),
      },
    };

    const buffers = initBuffers(gl);

    function initBuffers(gl) {
      const positionBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
      const positions = [-1.0, 1.0, 1.0, 1.0, -1.0, -1.0, 1.0, -1.0];
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.STATIC_DRAW);
      return { position: positionBuffer };
    }

    let currentTheme = 'void';
    function getColors() { return AURORA_THEMES[currentTheme] || AURORA_THEMES.void; }

    function render(now) {
      now *= 0.001;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0.0, 0.0, 0.0, 1.0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(programInfo.program);

      gl.bindBuffer(gl.ARRAY_BUFFER, buffers.position);
      gl.vertexAttribPointer(programInfo.attribLocations.vertexPosition, 2, gl.FLOAT, false, 0, 0);
      gl.enableVertexAttribArray(programInfo.attribLocations.vertexPosition);

      gl.uniform2f(programInfo.uniformLocations.resolution, canvas.width, canvas.height);
      gl.uniform1f(programInfo.uniformLocations.time, now);

      const colors = getColors().colors;
      gl.uniform3f(programInfo.uniformLocations.c1, colors[0], colors[1], colors[2]);
      gl.uniform3f(programInfo.uniformLocations.c2, colors[3], colors[4], colors[5]);
      gl.uniform3f(programInfo.uniformLocations.c3, colors[6], colors[7], colors[8]);

      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      requestAnimationFrame(render);
    }
    requestAnimationFrame(render);

    return {
      setTheme(name) { currentTheme = name; }
    };
  }

  const aurora = initAurora();

  // ══════════════════════════════════════════════════════
  // Toasts & Notifications
  // ══════════════════════════════════════════════════════
  function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const t = document.createElement('div');
    t.className = `toast ${type}`;

    let icon = 'info';
    if (type === 'success') icon = 'check-circle';
    if (type === 'error') icon = 'alert-circle';

    t.innerHTML = `<i data-lucide="${icon}" style="width:16px; min-width:16px;"></i> <span>${msg}</span>`;
    container.appendChild(t);
    lucide.createIcons();

    // Animate out
    setTimeout(() => {
      t.classList.add('out');
      t.addEventListener('animationend', () => t.remove());
    }, 4000);
  }

  // ══════════════════════════════════════════════════════
  // Theme System (Refined)
  // ══════════════════════════════════════════════════════
  let currentThemeBase = localStorage.getItem('alter_theme') || 'void';
  let isLightMode = localStorage.getItem('alter_theme_light') === 'true';

  // Init UI (Boxy Toggle)
  const modeDark = document.getElementById('mode-dark');
  const modeLight = document.getElementById('mode-light');

  function updateToggleUI() {
    if (modeDark) {
      modeDark.classList.toggle('active', !isLightMode);
      // Ensure icon color is white if active (overriden by CSS but good to be safe)
    }
    if (modeLight) {
      modeLight.classList.toggle('active', isLightMode);
    }
  }

  if (modeDark && modeLight) {
    updateToggleUI();
    modeDark.onclick = () => { isLightMode = false; updateToggleUI(); updateTheme(); };
    modeLight.onclick = () => { isLightMode = true; updateToggleUI(); updateTheme(); };
  }

  function updateTheme() {
    // 1. Set base theme class (e.g. theme-void)
    // Remove old theme classes first
    document.body.classList.remove('theme-void', 'theme-ember', 'theme-arctic', 'theme-pure');
    document.body.classList.add(`theme-${currentThemeBase}`);

    // 2. Toggle light mode class
    document.body.classList.toggle('theme-light', isLightMode);

    // 3. Update Aurora
    // If light mode, use base + "-light" key
    const auroraKey = isLightMode ? `${currentThemeBase}-light` : currentThemeBase;
    if (aurora) aurora.setTheme(auroraKey);

    // 4. Persistence
    localStorage.setItem('alter_theme', currentThemeBase);
    localStorage.setItem('alter_theme_light', isLightMode);

    // 5. Update Swatches
    document.querySelectorAll('.theme-swatch').forEach(s => {
      s.classList.toggle('active', s.dataset.theme === currentThemeBase);
    });
  }

  // Swatch Click Handlers
  document.querySelectorAll('.theme-swatch').forEach(s => {
    s.onclick = () => {
      currentThemeBase = s.dataset.theme;
      updateTheme();
    };
  });

  // Initial Apply
  updateTheme();

  // ══════════════════════════════════════════════════════
  // Welcome Flow (Arc-style for fresh users)
  // ══════════════════════════════════════════════════════
  const welcomeOverlay = document.getElementById('welcome-flow');
  const welcomeBegin = document.getElementById('welcome-begin');

  function showWelcomeFlow() {
    if (!welcomeOverlay) return;
    welcomeOverlay.classList.remove('hidden');
  }

  function hideWelcomeFlow() {
    if (!welcomeOverlay) return;
    welcomeOverlay.classList.add('fade-out');
    setTimeout(() => {
      welcomeOverlay.classList.add('hidden');
      welcomeOverlay.classList.remove('fade-out');
    }, 800);
  }

  if (welcomeBegin) {
    welcomeBegin.addEventListener('click', () => {
      hideWelcomeFlow();
      setTimeout(() => showOnboard(), 500);
    });
  }

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

  // --- 2. Focus Mode & Auto-grow ---
  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  }

  function resetInputHeight() {
    input.style.height = 'auto';
  }

  input.addEventListener("input", autoGrow);

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

    const selected = skillsList.querySelector(".selected");
    if (selected) selected.scrollIntoView({ block: "nearest" });
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

    const selected = commandsList.querySelector(".selected");
    if (selected) selected.scrollIntoView({ block: "nearest" });
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

  function stripAnsi(str) {
    // 1. Strip ANSI control codes (colors, cursor, etc)
    const ansiRegex = /\x1b\[[0-9;]*[a-zA-Z]/g;
    const oscRegex = /\x1b\][0-9;]*\x07/g;
    let clean = str.replace(ansiRegex, "").replace(oscRegex, "");

    // 2. Handle Carriage Returns (\r) to collapse progress bars/spinners
    // We split by \n, then for each line split by \r and keep the last segment.
    return clean.split('\n').map(line => {
      const parts = line.split('\r');
      return parts[parts.length - 1];
    }).join('\n');
  }

  function summarizeFsTool(toolId, inputs = {}, artifacts = null) {
    try {
      if (toolId === "fs.list") {
        const path = inputs.path || "";
        const n = artifacts && Array.isArray(artifacts.entries) ? artifacts.entries.length : null;
        return `Listed ${path}${n !== null ? ` (${n} entries)` : ""}`;
      }
      if (toolId === "fs.read") {
        const path = inputs.path || "";
        const s = inputs.start_line;
        const e = inputs.end_line;
        if (s || e) return `Read ${path} (lines ${s || 1}-${e || "end"})`;
        return `Read ${path}`;
      }
      if (toolId === "fs.read_multiple") {
        const paths = Array.isArray(inputs.paths) ? inputs.paths : [];
        return `Read ${paths.length} file${paths.length === 1 ? "" : "s"}`;
      }
      if (toolId === "fs.write") {
        const path = inputs.path || (artifacts && artifacts.path) || "";
        const mode = (artifacts && artifacts.mode) || inputs.mode || "overwrite";
        return `Wrote ${path} (${mode})`;
      }
      if (toolId === "fs.edit") {
        const path = inputs.path || "";
        return `Edited ${path}`;
      }
      if (toolId === "fs.rename") {
        const src = inputs.src || (artifacts && artifacts.src) || "";
        const dst = inputs.dst || (artifacts && artifacts.dst) || "";
        if (src && dst) return `Renamed ${src} → ${dst}`;
        return "Renamed file";
      }
    } catch { }
    return "";
  }

  function appendFsDetails(toolId, inputs = {}, artifacts = null, parentEl) {
    if (!parentEl) return false;
    let entries = [];
    let title = "";

    if (toolId === "fs.list" && artifacts && Array.isArray(artifacts.entries)) {
      entries = artifacts.entries;
      title = `Show entries (${entries.length})`;
    } else if (toolId === "fs.read_multiple" && Array.isArray(inputs.paths)) {
      entries = inputs.paths.map(p => ({ path: p, name: String(p).split(/[\\/]/).pop(), is_dir: false }));
      title = `Show files (${entries.length})`;
    } else {
      return false;
    }

    const details = document.createElement("details");
    details.className = "terminal-details fs-details";

    const summary = document.createElement("summary");
    summary.className = "terminal-summary";

    const toggle = document.createElement("span");
    toggle.className = "term-toggle";

    const icon = document.createElement("i");
    icon.setAttribute("data-lucide", "chevron-right");
    icon.className = "term-chevron";

    const txt = document.createElement("span");
    txt.className = "term-toggle-text";
    txt.textContent = title;

    toggle.appendChild(icon);
    toggle.appendChild(txt);
    summary.appendChild(toggle);
    details.appendChild(summary);

    const win = document.createElement("div");
    win.className = "terminal-window fs-window";

    const makeItem = (entry) => {
      const item = document.createElement("div");
      item.className = "fs-item";

      const main = document.createElement("div");
      main.className = "fs-main";

      const ic = document.createElement("i");
      ic.setAttribute("data-lucide", entry.is_dir ? "folder" : "file");
      ic.className = "fs-icon";

      const text = document.createElement("div");
      text.className = "fs-text";

      const name = document.createElement("div");
      name.className = "fs-name";
      name.textContent = entry.name || String(entry.path || "").split(/[\\/]/).pop() || "(unknown)";

      const path = document.createElement("div");
      path.className = "fs-path";
      path.textContent = entry.path || entry.rel_path || "";

      text.appendChild(name);
      if (path.textContent) text.appendChild(path);

      main.appendChild(ic);
      main.appendChild(text);

      const actions = document.createElement("div");
      actions.className = "fs-actions";

      const copyBtn = document.createElement("button");
      copyBtn.className = "fs-action";
      copyBtn.textContent = "Copy";
      copyBtn.onclick = async () => {
        const p = entry.path || entry.rel_path || "";
        if (!p) return;
        try {
          await navigator.clipboard.writeText(p);
          if (typeof showToast === "function") showToast("Path copied", "success");
        } catch {
          if (typeof showToast === "function") showToast("Copy failed", "error");
        }
      };

      const openBtn = document.createElement("button");
      openBtn.className = "fs-action";
      openBtn.textContent = "Open";
      openBtn.onclick = () => {
        const p = entry.path || entry.rel_path || "";
        if (!p) return;
        input.value = `open ${p}`;
        input.focus();
      };

      actions.appendChild(copyBtn);
      actions.appendChild(openBtn);

      item.appendChild(main);
      item.appendChild(actions);
      return item;
    };

    entries.slice(0, 200).forEach(e => win.appendChild(makeItem(e)));
    details.appendChild(win);

    details.addEventListener("toggle", () => {
      txt.textContent = details.open ? title.replace("Show", "Hide") : title;
    });

    parentEl.appendChild(details);
    lucide.createIcons({ nodes: [details] });
    return true;
  }

  function appendToolExecution(data, isAuto = false) {
    markToolsComplete();
    const el = document.createElement("div");
    el.className = "msg tool";
    const toolId = escapeHtml(data.tool_id);
    const isWeb = data.tool_id && data.tool_id.startsWith("web.");
    const iconName = isWeb ? "globe" : "loader";
    const animClass = isWeb ? "animate-breathe" : "animate-spin";
    const autoLabel = isAuto ? ' <span style="font-size:0.7em; color:var(--text-dim); margin-left:0.5rem">(Auto)</span>' : '';

    el.innerHTML = `
       <div class="tool-executing" data-tool-id="${toolId}" data-request-id="${escapeHtml(data.request_id || '')}">
         <i data-lucide="${iconName}" class="${animClass}"></i>
         <span class="tool-label tool-progress-text">Running <strong>${toolId}</strong>...${autoLabel}</span>
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

    const autoAllowed = new Set();

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
        appendToolExecution(data, autoAllowed.has(data.request_id));
        autoAllowed.delete(data.request_id);
      }
      else if (data.type === "tool_request") {
        hideLoader();
        // Confirm logic reused from previous, but simplified style
        const autoConfirm = isAutoConfirmEnabled();
        console.log(`[AutoConfirm] Setting:${autoConfirm} Tool:${data.tool_id} Required:${data.confirm_required}`);

        if (autoConfirm && data.confirm_required) {
          console.log("[AutoConfirm] Auto-allowing tool:", data.tool_id);
          autoAllowed.add(data.request_id);
          ws.send(JSON.stringify({ type: "confirm", request_id: data.request_id, allow: true }));
        } else {
          console.log("[AutoConfirm] Showing confirm card for:", data.tool_id);
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
      else if (data.type === "tool_result") {
        // Find the executing tool card
        const toolId = data.tool_id;
        const reqId = data.request_id;
        // Try to find by request ID first, else active spinner
        let el = null;
        if (reqId) {
          el = document.querySelector(`.tool-executing[data-request-id="${escapeHtml(reqId)}"]`);
        }
        if (!el) {
          el = document.querySelector(".tool-executing:not(.done)");
        }

        if (el) {
          // Mark as done if not already
          if (!el.classList.contains("done")) {
            el.classList.add("done");
            el.querySelector(".animate-spin")?.classList.remove("animate-spin");
            el.querySelector(".animate-breathe")?.classList.remove("animate-breathe");
            setToolIcon(el, "terminal-square", { spin: false });
            const label = el.querySelector(".tool-label");
            if (label) {
              const summary = summarizeFsTool(toolId, data.inputs || {}, data.artifacts || null);
              label.innerHTML = summary
                ? `Ran <strong>${escapeHtml(toolId)}</strong> — ${escapeHtml(summary)}`
                : `Ran <strong>${escapeHtml(toolId)}</strong>`;
            }
          }

          // Append terminal output if there is any output data
          // Strip ANSI codes (colors, cursor movements) for cleaner display
          const stdout = stripAnsi(data.stdout || "");
          const stderr = stripAnsi(data.stderr || "");
          const cmd = data.command || "";
          const result = data.result || "";

          // Use result as fallback display text when stdout/cmd are empty (e.g. fs.list artifacts)
          const displayOut = stdout.trim() ? stdout : result;

          if (displayOut.trim() || stderr.trim() || cmd) {
            const termId = "term-" + (reqId || Math.random().toString(36).substr(2, 9));
            const details = document.createElement("details");
            details.className = "terminal-details";
            // Default to open if stderr exists (error), else closed
            if (stderr.trim()) details.open = true;

            const isError = data.status === "error";

            details.innerHTML = `
              <summary class="terminal-summary">
                <span class="term-toggle">
                  <i data-lucide="chevron-right" class="term-chevron"></i>
                  <span class="term-toggle-text">${isError ? 'Error Output' : 'Show Output'}</span>
                </span>
              </summary>
              <div class="terminal-window">
                ${cmd ? `<div class="term-cmd">${escapeHtml(cmd)}</div>` : ""}
                ${displayOut.trim() ? `<pre class="term-out">${escapeHtml(displayOut)}</pre>` : ""}
                ${stderr ? `<pre class="term-err">${escapeHtml(stderr)}</pre>` : ""}
              </div>
            `;

            // Toggle text on open/close
            details.addEventListener("toggle", () => {
              const txt = details.querySelector(".term-toggle-text");
              if (txt) txt.textContent = details.open ? "Hide Output" : "Show Output";
            });

            el.parentElement.appendChild(details);
            lucide.createIcons({ nodes: [details] });
          }

          // FS-specific viewer (list/read_multiple)
          appendFsDetails(toolId, data.inputs || {}, data.artifacts || null, el.parentElement);
        }
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
    loaderEl.className = "msg assistant typing";
    loaderEl.innerHTML = `
      <div class="loader-box">
        <div class="typing-square"></div>
        <div class="typing-square"></div>
        <div class="typing-square"></div>
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

  // --- WebSocket Logic ---




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
          "- `/reset` — reset all memory (destructive!)",
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

    if (cmd === "/reset") {
      if (!key) { showTokenModal(); return true; }
      if (!confirm("Are you sure? This will wipe ALL memory, identities, and state.")) return true;
      try {
        const r = await fetch("/v1/memory/reset" + qs, { method: "DELETE" });
        if (r.status === 401 || r.status === 403) {
          showTokenModal("Access token required.");
          return true;
        }
        const d = await r.json();
        append("assistant", `Memory reset complete. Deleted **${d.deleted || 0}** events.`);
      } catch (e) {
        append("tool", "Error: failed to reset memory");
      }
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

  // --- Memory Reset Handler ---
  // --- Memory Reset Handler ---
  const memResetBtn = document.getElementById("memory-reset-btn");
  if (memResetBtn) {
    memResetBtn.onclick = async () => {
      if (!confirm("Are you sure? This will wipe ALL memory, identities, and state. This cannot be undone.")) return;
      const key = getKey();
      if (!key) { showTokenModal(); return; }
      const qs = `?key=${encodeURIComponent(key)}`;
      try {
        memResetBtn.disabled = true;
        memResetBtn.textContent = "RESETTING...";
        const r = await fetch("/v1/memory/reset" + qs, { method: "DELETE" });
        if (r.status === 401 || r.status === 403) {
          showTokenModal("Access token required.");
          return;
        }
        const d = await r.json();
        memResetBtn.textContent = "DONE ✓";
        setTimeout(() => { memResetBtn.textContent = "RESET ALL MEMORY"; memResetBtn.disabled = false; }, 2000);
        showToast(`Memory reset complete. Deleted ${d.deleted || 0} events.`, 'success');
      } catch (e) {
        memResetBtn.textContent = "RESET ALL MEMORY";
        memResetBtn.disabled = false;
        showToast("Error: failed to reset memory", 'error');
      }
    };
  }

  function sendMsg() {
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    resetInputHeight();
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
  
  // Persist auto-confirm immediately when toggled (once, not per-open)
  if (autoConfirmCheck) {
    try {
      autoConfirmCheck.checked = localStorage.getItem("alter_auto_confirm") === "true";
    } catch { }
    autoConfirmCheck.addEventListener("change", () => {
      try {
        localStorage.setItem("alter_auto_confirm", autoConfirmCheck.checked ? "true" : "false");
      } catch { }
      console.log("[Settings] Auto-confirm set to:", autoConfirmCheck.checked);
    });
  }

  // Open Settings
  settingsBtn.onclick = async () => {
    modal.classList.remove("hidden");

    // Load Auto Confirm state
    try {
      if (autoConfirmCheck) {
        autoConfirmCheck.checked = localStorage.getItem("alter_auto_confirm") === "true";
      }
    } catch { }

    // Load current provider
    const qs = getKey() ? `?key=${encodeURIComponent(getKey())}` : "";
    try {
      const s = await fetch("/v1/system/status" + qs).then(r => r.json());
      if (s.model && s.model.backend) {
        providerSel.value = s.model.backend;
      }
      if (currentModelDisplay && s.model) {
        currentModelDisplay.textContent = `Currently active: ${s.model.model || s.model.model_path} (${s.model.backend})`;
        // Initialize active model state to prevent false "Switched" toasts
        if (window._activeModel === undefined) {
          window._activeModel = s.model.id || s.model.model || s.model.model_path;
        }
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
    // Guard against duplicate clicks
    if (saveBtn.disabled) return;
    saveBtn.disabled = true;
    const origText = saveBtn.textContent;
    saveBtn.textContent = "APPLYING...";

    const backend = providerSel.value;
    const model = modelSel.value;
    const auto = document.getElementById("auto-confirm-check").checked;

    // Check if changed
    const oldModel = window._activeModel;
    const changed = (model !== oldModel);

    localStorage.setItem("alter_auto_confirm", auto);

    const qs = getKey() ? `?key=${encodeURIComponent(getKey())}` : "";

    try {
      await fetch("/v1/system/model" + qs, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend, model })
      });
      modal.classList.add("hidden");

      if (changed) {
        showToast(`System updated: Using ${model}`, 'success');
      } else {
        showToast("Settings saved", 'info');
      }

      window._activeModel = model;
    } catch (e) {
      showToast("Failed to update settings", 'error');
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = origText;
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
      const hadKeyBeforeSave = Boolean(getKey());

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
      if (!hadKeyBeforeSave) {
        // First-time auth: reload so startup init runs fetchWelcome + welcome/onboard gating.
        location.reload();
        return;
      }
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

        // Check if fresh user (no identity) → show welcome flow
        // Check if fresh user (no identity) → show welcome flow
        if (data.has_identity === false) {
          showWelcomeFlow();
        }

        if (data.titles && Array.isArray(data.titles) && data.titles.length > 0) {
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
  function isAutoConfirmEnabled() {
    try {
      const stored = localStorage.getItem("alter_auto_confirm");
      if (stored === "true") return true;
      if (autoConfirmCheck && autoConfirmCheck.checked) {
        localStorage.setItem("alter_auto_confirm", "true");
        return true;
      }
    } catch { }
    return false;
  }
