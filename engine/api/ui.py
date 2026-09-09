"""Minimal control page for the two-layer internet plugin."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..config import settings

router = APIRouter()

_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Internet plugin — local-engine-internet</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font-family: ui-sans-serif, system-ui, sans-serif;
           background: #0e1116; color: #e8eaed; }
    main { max-width: 36rem; margin: 3rem auto; padding: 0 1.25rem; }
    h1 { font-size: 1.25rem; font-weight: 600; letter-spacing: .02em; }
    p { color: #9aa3af; line-height: 1.5; }
    .card { background: #171b22; border: 1px solid #2a303a; border-radius: 12px;
            padding: 1.25rem 1.35rem; margin: 1.25rem 0; }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
    .label { font-weight: 600; }
    .sub { font-size: .85rem; color: #9aa3af; margin-top: .25rem; }
    button { appearance: none; border: 0; border-radius: 999px; padding: .55rem 1.1rem;
             font-weight: 600; cursor: pointer; }
    button.on { background: #3dd68c; color: #062814; }
    button.off { background: #3a414d; color: #e8eaed; }
    .layer { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em;
             color: #7d8796; margin-bottom: .45rem; }
    .ok { color: #3dd68c; }
    .dim { color: #7d8796; }
    a { color: #8ab4f8; }
    code { font-size: .85rem; background: #11151b; padding: .1rem .35rem; border-radius: 4px; }
  </style>
</head>
<body>
<main>
  <h1>Internet plugin</h1>
  <p>Two layers. You turn the plugin on or off. When it is on, the model decides
     whether this question needs the live web.</p>

  <div class="card">
    <div class="layer">Layer 1 — master switch</div>
    <div class="row">
      <div>
        <div class="label" id="state">…</div>
        <div class="sub" id="hint"></div>
      </div>
      <button id="toggle" type="button">…</button>
    </div>
  </div>

  <div class="card">
    <div class="layer">Layer 2 — intelligence</div>
    <div class="label">The model chooses</div>
    <p class="sub" style="margin: .5rem 0 0">
      Enabled means tools are available. “What is 2+2?” stays offline.
      “Nvidia’s last reported quarter?” searches. Research desks can still force
      a search with <code>phoenician_web.policy: "required"</code>.
    </p>
    <p class="sub" id="intel"></p>
  </div>

  <p class="sub">Providers: <span id="providers"></span><br/>
     API docs: <a href="/docs">/docs</a> ·
     Plug-in: <code>http://127.0.0.1:__PORT__/v1</code></p>
</main>
<script>
async function load() {
  try {
    const r = await fetch("/v1/plugin");
    if (!r.ok) {
      document.getElementById("state").textContent = "Unavailable";
      document.getElementById("hint").textContent =
        r.status === 401
          ? "ENGINE_API_KEY is set. Open /docs or send Authorization: Bearer."
          : "Could not read plugin status (HTTP " + r.status + ").";
      return;
    }
    const j = await r.json();
    const on = !!j.enabled;
    document.getElementById("state").textContent = on ? "Enabled" : "Disabled";
    document.getElementById("hint").textContent = on
      ? "Internet is available. Layer 2 decides per question."
      : "No search, no fetch. Chat is a plain LLM pass-through.";
    const btn = document.getElementById("toggle");
    btn.textContent = on ? "Disable" : "Enable";
    btn.className = on ? "on" : "off";
    document.getElementById("intel").innerHTML = on
      ? 'Intelligence: <span class="ok">' + (j.intelligence || "auto") + "</span>"
      : 'Intelligence: <span class="dim">off (plugin disabled)</span>';
    document.getElementById("providers").textContent =
      (j.providers && j.providers.length) ? j.providers.join(", ") : "none";
  } catch (err) {
    document.getElementById("state").textContent = "Unavailable";
    document.getElementById("hint").textContent = "Engine is not reachable.";
  }
}
document.getElementById("toggle").onclick = async () => {
  const now = document.getElementById("state").textContent === "Enabled";
  try {
    const r = await fetch("/v1/plugin", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({enabled: !now})
    });
    if (!r.ok) {
      document.getElementById("hint").textContent =
        r.status === 401
          ? "ENGINE_API_KEY is set. The toggle needs Authorization."
          : "Could not update plugin (HTTP " + r.status + ").";
      return;
    }
  } catch (err) {
    document.getElementById("hint").textContent = "Engine is not reachable.";
    return;
  }
  load();
};
load();
</script>
</body>
</html>
"""


@router.get("/ui", response_class=HTMLResponse)
async def plugin_ui() -> str:
    return _PAGE.replace("__PORT__", str(settings.port))
