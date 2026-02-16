**Plan (Local-First, Windows Runner + Phone Control First)**

1. **Phase 0 (1 week): Spec + safety contract**
- Define action schema: `click`, `type`, `hotkey`, `scroll`, `launch_app`, `wait`, `assert`.
- Define guardrails: allowlisted apps, risky-action approvals, full audit + screenshot trail.
- Define success metrics: task success rate, step retry rate, human takeover rate.

2. **Phase 1 (2 weeks): Windows runner MVP**
- Build `alter-runner-windows` service:
  - Screen capture stream (Windows Graphics Capture).
  - UI tree extraction + actions via `pywinauto` (UIA backend).
  - Low-level fallback input only when UIA cannot act.
- Keep this runner isolated from Alter core via RPC (don’t couple orchestration to OS APIs).

3. **Phase 2 (2 weeks): Local vision + planner loop**
- Add Observe → Plan → Act → Verify loop.
- Use **UIA-first**, vision second:
  - UIA element exists: act directly.
  - UIA missing/ambiguous: run VL model on frame.
- Add “stuck detector” + recovery (undo/back/reopen app/replan).

4. **Phase 3 (2 weeks): Phone live view + remote approvals**
- WebRTC stream from runner to phone app.
- Phone app supports:
  - live screen,
  - action timeline,
  - approve/deny risky actions,
  - emergency stop / takeover.
- Start with single active session per runner.

5. **Phase 4 (2 weeks): Robustness hardening**
- Deterministic retries + timeouts per action.
- Post-action verification (UI state + visual confirmation).
- Crash recovery with resumable task state.
- Add replayable traces for debugging.

6. **Phase 5 (2 weeks): Cross-platform expansion**
- Android runner next (Appium UiAutomator2 + accessibility).
- macOS/Linux after Android; keep same capability interface.
- iOS automation later (higher setup friction: macOS + WDA/XCUITest path).

---

**Model stack (mostly local)**

**Default local stack (recommended)**
- Planner/reasoner: `qwen3:14b` (or `qwen3:8b` if hardware limited).
- Vision understanding: `qwen3-vl:8b` (upgrade to `30b` on strong GPU).
- GUI parsing helper: OmniParser v2 (local checkpoints).
- Retrieval memory embeddings: `qwen3-embedding:4b` (or `0.6b` lightweight).
- Optional “hard reasoning pass”: `deepseek-r1:8b` when primary planner is uncertain.

**Lightweight local stack**
- Planner: `qwen3:4b` or `8b`
- Vision: `qwen3-vl:4b` or `gemma3:4b`
- Embeddings: `qwen3-embedding:0.6b`

**High-end local stack**
- Planner: `qwen3:30b`
- Vision: `qwen3-vl:30b`
- Embeddings: `qwen3-embedding:8b`

---

**Cloud fallback (only when local confidence is low)**
- Primary free-ish fallback: Gemini API free tier (rate-limited).
- Secondary free fallback: OpenRouter free router / `:free` model variants.
- Paid fallback (if needed later): OpenAI vision endpoints.

---

**Why this is robust**
- UIA-first reduces brittle pixel clicking.
- Vision is used where accessibility trees fail.
- Every action is verified before moving on.
- Human-in-the-loop for high-risk operations.
- Replayable traces make failures debuggable and fixable.

---

Locked scope :

- `Automation target`: **Windows only** (no Android/macOS runners ever).
- `Android role`: **controller app only** (send tasks, watch live screen, approve/stop actions).

Updated architecture:

1. `alter-core` (planner, memory, auth, policy, audit).
2. `alter-runner-windows` (capture + UI control + execution loop).
3. `alter-controller-android` (live stream + command + approvals).

Updated local-first model stack:

1. Planner: `qwen3:14b` (fallback `qwen3:8b`).
2. Vision: `qwen3-vl:8b` (upgrade `qwen3-vl:30b` on strong GPU).
3. Embeddings/memory: `qwen3-embedding:4b` (or `0.6b` lightweight).
4. OCR fallback: local OCR engine (Tesseract/PaddleOCR) for text-heavy UI.
5. Cloud fallback only when needed: Gemini/OpenRouter free-tier routes.

Revised roadmap (Windows-first only):

1. Week 1: protocol/spec + permissions + audit schema.
2. Week 2-3: Windows runner MVP (UIA actions + capture stream).
3. Week 4-5: planner loop (observe/plan/act/verify/recover).
4. Week 6-7: Android controller app (WebRTC stream + approvals + emergency stop).
5. Week 8: reliability hardening (retries, recovery, trace replay, safety gates).



**Sources**
- Ollama vision/tool calling/OpenAI compatibility:  
  https://docs.ollama.com/capabilities/vision  
  https://docs.ollama.com/capabilities/tool-calling  
  https://docs.ollama.com/api/openai-compatibility
- Local model options:  
  https://ollama.com/library/qwen3-vl  
  https://ollama.com/library/qwen3  
  https://ollama.com/library/qwen3-embedding  
  https://ollama.com/library/gemma3  
  https://ollama.com/library/deepseek-r1
- Windows capture APIs:  
  https://learn.microsoft.com/en-us/windows/uwp/audio-video-camera/screen-capture  
  https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api
- Windows GUI automation:  
  https://pywinauto.readthedocs.io/en/latest/getting_started.html
- Streaming:  
  https://www.w3.org/TR/webrtc/  
  https://docs.livekit.io/transport/self-hosting/
- Android automation/capture:  
  https://appium.io/docs/en/latest/  
  https://developer.android.com/reference/android/accessibilityservice/AccessibilityService  
  https://developer.android.com/media/grow/media-projection
- Benchmarks/research tooling:  
  https://os-world.github.io/  
  https://arxiv.org/abs/2404.07972  
  https://github.com/microsoft/WindowsAgentArena  
  https://github.com/microsoft/OmniParser  
  https://github.com/bytedance/UI-TARS
- Free API fallback details:  
  https://ai.google.dev/gemini-api/docs/rate-limits  
  https://openrouter.ai/docs/guides/routing/routers/free-models-router  
  https://openrouter.ai/docs/guides/routing/model-variants/free  
  https://docs.github.com/en/billing/concepts/product-billing/github-models