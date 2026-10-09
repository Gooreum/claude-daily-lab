#!/usr/bin/env python3
"""motion_lite.py — 한 줄 컨셉 → 짧은 애니메이션 설명 영상(단일 HTML).

Claude Motion(2026-10-08 베타, Team/Enterprise 전용)의 동네 버전이다.
  1) Haiku 5.5가 `claude -p --json-schema`로 스토리보드 JSON(장면·도형·자막·애니메이션)을 쓴다.
  2) 이 스크립트가 그 JSON을 단일 HTML에 박는다. 브라우저가 canvas로 재생하고, 버튼 하나로 WebM을 내려받는다.
--dry-run이면 내장 스토리보드로 렌더만 한다(키·네트워크 불필요).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-5-5"
KINDS = ["rect", "circle", "text", "arrow"]
ANIMS = ["none", "fade", "slide-left", "slide-up", "grow", "pulse"]
MAX_SCENES, MAX_SHAPES = 8, 10

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "scenes": {
            "type": "array", "minItems": 2, "maxItems": MAX_SCENES,
            "items": {
                "type": "object",
                "properties": {
                    "caption": {"type": "string"},
                    "duration_s": {"type": "number", "minimum": 1.5, "maximum": 8},
                    "bg": {"type": "string"},
                    "shapes": {
                        "type": "array", "minItems": 1, "maxItems": MAX_SHAPES,
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": KINDS},
                                "x": {"type": "number", "minimum": 0, "maximum": 100},
                                "y": {"type": "number", "minimum": 0, "maximum": 100},
                                "w": {"type": "number", "minimum": 1, "maximum": 100},
                                "h": {"type": "number", "minimum": 1, "maximum": 100},
                                "color": {"type": "string"},
                                "label": {"type": "string"},
                                "anim": {"type": "string", "enum": ANIMS},
                                "delay_s": {"type": "number", "minimum": 0, "maximum": 6},
                            },
                            "required": ["kind", "x", "y", "w", "h", "color", "anim"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["caption", "duration_s", "bg", "shapes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "scenes"],
    "additionalProperties": False,
}

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class StoryboardError(ValueError):
    pass


def validate_storyboard(sb: object) -> dict:
    """스키마와 같은 규칙을 파이썬에서 다시 확인한다 (모델 출력·사용자 JSON 모두)."""
    if not isinstance(sb, dict) or not isinstance(sb.get("title"), str) or not sb["title"].strip():
        raise StoryboardError("title이 없다")
    scenes = sb.get("scenes")
    if not isinstance(scenes, list) or not 2 <= len(scenes) <= MAX_SCENES:
        raise StoryboardError(f"scenes는 2~{MAX_SCENES}개여야 한다")
    for i, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            raise StoryboardError(f"scenes[{i}] 형식")
        if not isinstance(sc.get("caption"), str):
            raise StoryboardError(f"scenes[{i}].caption")
        d = sc.get("duration_s")
        if not isinstance(d, (int, float)) or not 1.5 <= d <= 8:
            raise StoryboardError(f"scenes[{i}].duration_s는 1.5~8초")
        if not isinstance(sc.get("bg"), str) or not COLOR_RE.match(sc["bg"]):
            raise StoryboardError(f"scenes[{i}].bg는 #rrggbb")
        shapes = sc.get("shapes")
        if not isinstance(shapes, list) or not 1 <= len(shapes) <= MAX_SHAPES:
            raise StoryboardError(f"scenes[{i}].shapes는 1~{MAX_SHAPES}개")
        for j, sh in enumerate(shapes):
            where = f"scenes[{i}].shapes[{j}]"
            if not isinstance(sh, dict) or sh.get("kind") not in KINDS:
                raise StoryboardError(f"{where}.kind")
            for k, lo, hi in (("x", 0, 100), ("y", 0, 100), ("w", 1, 100), ("h", 1, 100)):
                v = sh.get(k)
                if not isinstance(v, (int, float)) or not lo <= v <= hi:
                    raise StoryboardError(f"{where}.{k}는 {lo}~{hi}")
            if not isinstance(sh.get("color"), str) or not COLOR_RE.match(sh["color"]):
                raise StoryboardError(f"{where}.color는 #rrggbb")
            if sh.get("anim") not in ANIMS:
                raise StoryboardError(f"{where}.anim")
            if "label" in sh and not isinstance(sh["label"], str):
                raise StoryboardError(f"{where}.label")
            if "delay_s" in sh and (not isinstance(sh["delay_s"], (int, float)) or not 0 <= sh["delay_s"] <= 6):
                raise StoryboardError(f"{where}.delay_s는 0~6")
    return sb  # type: ignore[return-value]


# ---------------------------------------------------------------- storyboard sources

BUILTIN = {
    "title": "Claude Code 모드란?",
    "scenes": [
        {"caption": "Claude Code는 이벤트를 흘려보낸다: 프롬프트, 도구 호출, 턴 완료.", "duration_s": 4, "bg": "#0f172a", "shapes": [
            {"kind": "rect", "x": 10, "y": 40, "w": 22, "h": 20, "color": "#38bdf8", "label": "prompt", "anim": "slide-left"},
            {"kind": "rect", "x": 39, "y": 40, "w": 22, "h": 20, "color": "#a78bfa", "label": "tool.call", "anim": "slide-left", "delay_s": 0.6},
            {"kind": "rect", "x": 68, "y": 40, "w": 22, "h": 20, "color": "#34d399", "label": "turn.complete", "anim": "slide-left", "delay_s": 1.2},
        ]},
        {"caption": "모드는 그 이벤트에 훅을 건다. on(event, ($, e, next) => …)", "duration_s": 4.5, "bg": "#0f172a", "shapes": [
            {"kind": "rect", "x": 39, "y": 40, "w": 22, "h": 20, "color": "#a78bfa", "label": "tool.call", "anim": "none"},
            {"kind": "circle", "x": 50, "y": 15, "w": 14, "h": 14, "color": "#fbbf24", "label": "hook", "anim": "grow"},
            {"kind": "arrow", "x": 50, "y": 24, "w": 1, "h": 14, "color": "#fbbf24", "anim": "fade", "delay_s": 0.8},
        ]},
        {"caption": "next(e)를 부르면 아래 플러그인과 엔진이 돌고, 결과를 바꿔 돌려줄 수 있다.", "duration_s": 5, "bg": "#0f172a", "shapes": [
            {"kind": "circle", "x": 25, "y": 50, "w": 16, "h": 16, "color": "#fbbf24", "label": "hook", "anim": "none"},
            {"kind": "arrow", "x": 36, "y": 50, "w": 26, "h": 1, "color": "#e2e8f0", "label": "next(e)", "anim": "slide-left"},
            {"kind": "rect", "x": 64, "y": 40, "w": 24, "h": 20, "color": "#64748b", "label": "engine", "anim": "fade", "delay_s": 0.5},
            {"kind": "text", "x": 50, "y": 78, "w": 60, "h": 8, "color": "#34d399", "label": "{ ...result, text: '⏱ 2.1s' }", "anim": "slide-up", "delay_s": 1.5},
        ]},
        {"caption": "pane, 알림, 상태 줄, 슬래시 명령까지 $ 하나로. 그게 모드다.", "duration_s": 4.5, "bg": "#0f172a", "shapes": [
            {"kind": "rect", "x": 20, "y": 45, "w": 16, "h": 22, "color": "#38bdf8", "label": "$.ui.open", "anim": "grow"},
            {"kind": "rect", "x": 40, "y": 45, "w": 16, "h": 22, "color": "#a78bfa", "label": "$.ui.notify", "anim": "grow", "delay_s": 0.4},
            {"kind": "rect", "x": 60, "y": 45, "w": 16, "h": 22, "color": "#34d399", "label": "$.ui.status", "anim": "grow", "delay_s": 0.8},
            {"kind": "rect", "x": 80, "y": 45, "w": 16, "h": 22, "color": "#fbbf24", "label": "$.command", "anim": "grow", "delay_s": 1.2},
            {"kind": "text", "x": 50, "y": 82, "w": 60, "h": 8, "color": "#e2e8f0", "label": "claude --plugin-dir ./my-mod", "anim": "pulse", "delay_s": 1.6},
        ]},
    ],
}


def storyboard_from_model(concept: str, model: str = DEFAULT_MODEL, timeout: float = 180.0) -> dict:
    system = (
        "너는 짧은 설명 애니메이션의 스토리보드 작가다. 주어진 컨셉을 3~6개 장면으로 나눠, 장면마다 한 줄 자막(한국어)과 "
        "도형 1~6개를 배치한다. 좌표 x,y는 캔버스 중심 기준 퍼센트(0~100, 50이 가운데), w,h도 퍼센트. "
        "색은 #rrggbb. bg는 어두운 색 하나로 통일하고 도형 색은 2~4가지만 쓴다. label은 짧게. "
        "anim은 등장 효과(fade, slide-left, slide-up, grow, pulse, none), delay_s로 순서를 준다. "
        "글자가 겹치지 않게 x를 벌려라."
    )
    prompt = f"컨셉: {concept}\n스토리보드 JSON을 써라."
    cmd = ["claude", "-p", prompt, "--model", model, "--effort", "low", "--no-session-persistence", "--tools", "",
           "--max-turns", "1", "--output-format", "json", "--system-prompt", system,
           "--json-schema", json.dumps(SCHEMA, ensure_ascii=False)]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    data = json.loads(run.stdout)
    if data.get("is_error"):
        raise StoryboardError(f"모델 호출 실패: {str(data.get('result'))[:200]}")
    sb = validate_storyboard(data.get("structured_output"))
    sb["_meta"] = {"model": model, "cost_usd": data.get("total_cost_usd"), "duration_ms": data.get("duration_ms")}
    return sb


# ---------------------------------------------------------------- html

HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#09090b; --fg:#e4e4e7; --muted:#a1a1aa; --accent:#38bdf8; }
  body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif; }
  main { max-width:1000px; margin:0 auto; padding:16px; }
  h1 { font-size:18px; margin:0 0 10px; font-weight:600; }
  canvas { width:100%; aspect-ratio:16/9; background:#000; border-radius:8px; display:block; }
  .bar { display:flex; gap:8px; align-items:center; margin-top:10px; flex-wrap:wrap; }
  button { background:#18181b; color:var(--fg); border:1px solid #3f3f46; border-radius:6px; padding:6px 12px; cursor:pointer; font:inherit; }
  button:hover { border-color:var(--accent); }
  input[type=range] { flex:1; min-width:120px; }
  .muted { color:var(--muted); font-size:13px; }
  .scenes { margin:12px 0 0; padding:0; list-style:none; display:grid; gap:4px; }
  .scenes li { padding:6px 10px; border-radius:6px; background:#18181b; cursor:pointer; }
  .scenes li.on { outline:1px solid var(--accent); }
</style></head>
<body><main>
<h1 id="title"></h1>
<canvas id="c" width="1280" height="720"></canvas>
<div class="bar">
  <button id="play">▶ 재생</button>
  <input id="seek" type="range" min="0" max="1000" value="0">
  <span id="time" class="muted">0.0s</span>
  <button id="rec">⏺ WebM 저장</button>
  <span id="status" class="muted"></span>
</div>
<ol id="scenes" class="scenes"></ol>
<p class="muted">motion-lite · 스토리보드를 canvas로 재생합니다. "WebM 저장"은 처음부터 끝까지 한 번 재생하며 녹화합니다.</p>
</main>
<script id="sb" type="application/json">__STORYBOARD__</script>
<script>
(() => {
  const SB = JSON.parse(document.getElementById('sb').textContent);
  const c = document.getElementById('c'), ctx = c.getContext('2d');
  const W = c.width, H = c.height;
  document.getElementById('title').textContent = SB.title; document.title = SB.title;
  const starts = []; let total = 0;
  for (const s of SB.scenes) { starts.push(total); total += s.duration_s; }
  const XF = 0.5; // 장면 전환 크로스페이드(초)
  const ease = t => t < 0 ? 0 : t > 1 ? 1 : 1 - Math.pow(1 - t, 3);
  const px = v => v / 100 * W, py = v => v / 100 * H;

  function drawShape(s, t) { // t: 장면 시작 후 초
    const d = s.delay_s || 0, p = ease((t - d) / 0.6);
    if (p <= 0) return;
    let a = 1, dx = 0, dy = 0, sc = 1;
    if (s.anim === 'fade') a = p;
    else if (s.anim === 'slide-left') { a = p; dx = (1 - p) * W * 0.12; }
    else if (s.anim === 'slide-up') { a = p; dy = (1 - p) * H * 0.12; }
    else if (s.anim === 'grow') { a = p; sc = 0.4 + 0.6 * p; }
    else if (s.anim === 'pulse') { a = p; sc = 1 + 0.05 * Math.sin((t - d) * 4); }
    const x = px(s.x) + dx, y = py(s.y) + dy, w = px(s.w) * sc, h = py(s.h) * sc;
    ctx.save(); ctx.globalAlpha = a; ctx.fillStyle = s.color; ctx.strokeStyle = s.color; ctx.lineWidth = 6;
    if (s.kind === 'rect') { rr(x - w / 2, y - h / 2, w, h, 14); ctx.fill(); }
    else if (s.kind === 'circle') { ctx.beginPath(); ctx.ellipse(x, y, w / 2, h / 2, 0, 0, Math.PI * 2); ctx.fill(); }
    else if (s.kind === 'arrow') { arrow(x, y, w, h); }
    if (s.label) {
      const big = s.kind === 'text';
      ctx.fillStyle = big ? s.color : contrast(s.color);
      ctx.font = (big ? 600 : 500) + ' ' + (big ? 34 : 24) + 'px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(s.label, x, s.kind === 'arrow' ? y - 28 : y, Math.max(w, px(40)));
    }
    ctx.restore();
  }
  function rr(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }
  function arrow(x, y, w, h) { // w 또는 h 중 긴 쪽으로 향하는 화살표 (중심 기준)
    const horiz = w >= h, len = horiz ? w : h;
    const x0 = horiz ? x - len / 2 : x, y0 = horiz ? y : y - len / 2, x1 = horiz ? x + len / 2 : x, y1 = horiz ? y : y + len / 2;
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    const a = Math.atan2(y1 - y0, x1 - x0);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x1 - 22 * Math.cos(a - 0.5), y1 - 22 * Math.sin(a - 0.5)); ctx.lineTo(x1 - 22 * Math.cos(a + 0.5), y1 - 22 * Math.sin(a + 0.5)); ctx.closePath(); ctx.fill();
  }
  function contrast(hex) { const n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255; return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? '#0b0b0f' : '#fafafa'; }

  function drawScene(i, t, alpha) {
    const s = SB.scenes[i];
    ctx.save(); ctx.globalAlpha = alpha;
    ctx.fillStyle = s.bg; ctx.fillRect(0, 0, W, H);
    for (const sh of s.shapes) drawShape(sh, t);
    // 자막 띠
    ctx.fillStyle = 'rgba(0,0,0,0.55)'; ctx.fillRect(0, H - 96, W, 96);
    ctx.fillStyle = '#fafafa'; ctx.font = '500 30px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(s.caption, W / 2, H - 48, W - 80);
    ctx.restore();
  }
  function render(time) {
    time = Math.max(0, Math.min(total, time));
    let i = SB.scenes.findIndex((s, k) => time < starts[k] + s.duration_s); if (i < 0) i = SB.scenes.length - 1;
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
    drawScene(i, time - starts[i], 1);
    const into = time - starts[i];
    if (i > 0 && into < XF) drawScene(i - 1, SB.scenes[i - 1].duration_s + into, 1 - into / XF);
    for (const li of list.children) li.classList.toggle('on', +li.dataset.i === i);
    seek.value = Math.round(time / total * 1000); timeEl.textContent = time.toFixed(1) + 's / ' + total.toFixed(1) + 's';
  }

  // 컨트롤
  const play = document.getElementById('play'), seek = document.getElementById('seek'), timeEl = document.getElementById('time');
  const rec = document.getElementById('rec'), status = document.getElementById('status'), list = document.getElementById('scenes');
  SB.scenes.forEach((s, i) => { const li = document.createElement('li'); li.dataset.i = i; li.textContent = (i + 1) + '. ' + s.caption + ' (' + s.duration_s + 's)'; li.onclick = () => { stop(); cur = starts[i]; render(cur); }; list.appendChild(li); });
  let cur = 0, playing = false, t0 = 0, raf = 0, onEnd = null;
  function frame(now) { cur = (now - t0) / 1000; if (cur >= total) { cur = total; render(cur); stop(); if (onEnd) { const f = onEnd; onEnd = null; f(); } return; } render(cur); raf = requestAnimationFrame(frame); }
  function start(from) { cur = from ?? (cur >= total ? 0 : cur); t0 = performance.now() - cur * 1000; playing = true; play.textContent = '⏸ 멈춤'; raf = requestAnimationFrame(frame); }
  function stop() { playing = false; play.textContent = '▶ 재생'; cancelAnimationFrame(raf); }
  play.onclick = () => playing ? stop() : start();
  seek.oninput = () => { stop(); cur = seek.value / 1000 * total; render(cur); };
  rec.onclick = () => {
    if (!('MediaRecorder' in window) || !c.captureStream) { status.textContent = '이 브라우저는 녹화를 지원하지 않습니다.'; return; }
    const mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(m => MediaRecorder.isTypeSupported(m));
    if (!mime) { status.textContent = 'WebM 인코더가 없습니다.'; return; }
    const stream = c.captureStream(30), mr = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 4_000_000 }), chunks = [];
    mr.ondataavailable = e => e.data.size && chunks.push(e.data);
    mr.onstop = () => { const blob = new Blob(chunks, { type: 'video/webm' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = SB.title.replace(/[^\w가-힣-]+/g, '_') + '.webm'; a.click(); status.textContent = '저장됨: ' + a.download + ' (' + (blob.size / 1024 / 1024).toFixed(1) + ' MB)'; rec.disabled = false; };
    rec.disabled = true; status.textContent = '녹화 중… 끝까지 재생합니다.'; stop(); render(0); mr.start(100);
    onEnd = () => setTimeout(() => mr.stop(), 200); start(0);
  };
  render(0);
})();
</script></body></html>
"""


def render_html(sb: dict) -> str:
    validate_storyboard(sb)
    clean = {k: v for k, v in sb.items() if not k.startswith("_")}
    payload = json.dumps(clean, ensure_ascii=False).replace("</", "<\\/")
    title = sb["title"].replace("<", "&lt;").replace(">", "&gt;")
    return HTML.replace("__TITLE__", title).replace("__STORYBOARD__", payload)


def slugify(s: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", s.strip()).strip("-").lower()
    return s[:40] or "motion"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="한 줄 컨셉 → 애니메이션 설명 영상 HTML")
    ap.add_argument("concept", nargs="?", help="설명할 컨셉 한 줄 (dry-run이면 생략 가능)")
    ap.add_argument("--dry-run", action="store_true", help="모델 없이 내장 스토리보드로 렌더")
    ap.add_argument("--storyboard", type=Path, help="직접 쓴 스토리보드 JSON으로 렌더")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "out")
    ap.add_argument("--save-json", action="store_true", help="스토리보드 JSON도 옆에 저장")
    args = ap.parse_args(argv)
    try:
        if args.storyboard:
            sb = validate_storyboard(json.loads(args.storyboard.read_text(encoding="utf-8")))
        elif args.dry_run:
            sb = BUILTIN
        elif args.concept:
            print(f"🎬 {args.model}에게 스토리보드를 부탁하는 중…", file=sys.stderr)
            sb = storyboard_from_model(args.concept, args.model)
            m = sb.get("_meta", {})
            print(f"   {len(sb['scenes'])}장면, {sum(len(s['shapes']) for s in sb['scenes'])}도형, {m.get('duration_ms', 0) / 1000:.1f}s, ${m.get('cost_usd') or 0:.4f}", file=sys.stderr)
        else:
            ap.error("컨셉을 주거나 --dry-run / --storyboard를 쓰세요")
    except (StoryboardError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired) as e:
        print(f"motion_lite: {e}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{slugify(sb['title'])}.html"
    path.write_text(render_html(sb), encoding="utf-8")
    if args.save_json:
        (args.out / f"{slugify(sb['title'])}.json").write_text(json.dumps({k: v for k, v in sb.items() if not k.startswith('_')}, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(s["duration_s"] for s in sb["scenes"])
    print(f"✅ {path}  ({len(sb['scenes'])}장면, {total:.1f}초) — 브라우저로 열어 재생하거나 WebM으로 저장하세요")
    return 0


if __name__ == "__main__":
    sys.exit(main())
