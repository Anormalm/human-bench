"""Vercel WSGI entrypoint and browser-based blinded annotation interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = ROOT / "data" / "web" / "demo_bundle.json"

HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>说人话 Bench — Blind Annotation</title><style>
:root{--ink:#171717;--muted:#686868;--line:#dedbd5;--paper:#f7f5f0;--card:#fff;--accent:#204e3a}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,"Noto Sans SC",system-ui,sans-serif}main{max-width:1080px;margin:auto;padding:40px 24px 80px}.top{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;border-bottom:1px solid var(--line);padding-bottom:20px}h1{margin:0;font-size:32px;letter-spacing:-.03em}.kicker{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:700}.muted{color:var(--muted)}.meta,.setup,.question{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-top:18px}.meta-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.value{margin-top:4px;font-weight:600}.responses{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}.response{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px;min-height:190px;white-space:pre-wrap;line-height:1.75}.badge{display:inline-flex;width:30px;height:30px;border-radius:50%;align-items:center;justify-content:center;background:var(--ink);color:white;font-weight:700;margin-bottom:14px}.question h2{font-size:16px;margin:0 0 14px}.choices{display:flex;gap:10px;flex-wrap:wrap}.choices button{border:1px solid var(--line);background:white;border-radius:9px;padding:11px 16px;cursor:pointer;font-weight:650}.choices button.active{background:var(--accent);color:white;border-color:var(--accent)}.actions{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}select,input{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;background:white}.footer{display:flex;justify-content:space-between;align-items:center;margin-top:20px;gap:12px}.primary{background:var(--accent);color:white;border:0;border-radius:9px;padding:12px 18px;font-weight:700;cursor:pointer}.secondary{background:transparent;border:1px solid var(--line);border-radius:9px;padding:11px 15px;cursor:pointer}.progress{font-variant-numeric:tabular-nums}.facts{font-size:13px;line-height:1.6;margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}.error{color:#9c2c2c;font-weight:600;min-height:1.5em}.done{text-align:center;padding:70px 20px}.hidden{display:none}@media(max-width:760px){.responses,.actions,.meta-grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
</style></head><body><main>
<div class="top"><div><div class="kicker">Context-conditioned evaluation</div><h1>说人话 Bench</h1><div class="muted">盲测文本是否适合具体的人、关系与场景，而不是猜它是不是 AI 写的。</div></div><div class="progress" id="progress">Loading…</div></div>
<section class="setup" id="setup"><div class="actions"><label>标注者 ID<input id="annotator" placeholder="例如 pilot-rater-01"></label><label>人群标签（可选）<input id="population" placeholder="例如 student / engineer"></label></div></section>
<div id="task" class="hidden"><section class="meta"><div class="meta-grid" id="meta"></div><div style="margin-top:18px"><div class="label">场景</div><div id="context" style="margin-top:6px;line-height:1.7"></div></div><div style="margin-top:14px"><div class="label">任务</div><div id="instruction" style="margin-top:6px;line-height:1.7"></div></div><div class="facts" id="facts"></div></section>
<div class="responses"><article class="response"><div class="badge">A</div><div id="textA"></div></article><article class="response"><div class="badge">B</div><div id="textB"></div></article></div>
<section class="question"><h2>在这个具体场景中，你更愿意使用哪一个版本？</h2><div class="choices" id="preference"><button data-value="A">选择 A</button><button data-value="tie">差不多 / 平局</button><button data-value="B">选择 B</button></div><div class="actions"><label>A 的处理方式<select id="actionA"><option value="">请选择</option><option value="send">原样发送</option><option value="revise">修改后使用</option><option value="reject">不用 / 重写</option></select></label><label>B 的处理方式<select id="actionB"><option value="">请选择</option><option value="send">原样发送</option><option value="revise">修改后使用</option><option value="reject">不用 / 重写</option></select></label></div><div style="margin-top:16px"><label>信心程度（1–5）<input id="confidence" type="range" min="1" max="5" value="3"><span id="confidenceValue">3</span></label></div><div class="error" id="error"></div><div class="footer"><button class="secondary" id="export">导出已有标注</button><button class="primary" id="next">保存并继续</button></div></section></div>
<section class="meta done hidden" id="done"><h2>本轮标注完成</h2><p class="muted">标注只保存在当前浏览器。请导出 JSONL 文件并交给 benchmark 管理者。</p><button class="primary" id="exportDone">导出标注</button></section>
</main><script>
let bundle={items:[]},index=0,preference="";const answers=JSON.parse(localStorage.getItem("shuorenhua_answers")||"[]");const $=id=>document.getElementById(id);const esc=s=>String(s??"");
function render(){if(index>=bundle.items.length){$("task").classList.add("hidden");$("done").classList.remove("hidden");$("progress").textContent=`${answers.length} completed`;return}const x=bundle.items[index];$("task").classList.remove("hidden");$("progress").textContent=`${index+1} / ${bundle.items.length}`;$("meta").innerHTML=[["文体",x.genre],["关系",x.relationship],["意图",x.intent],["渠道",x.channel]].map(([a,b])=>`<div><div class="label">${a}</div><div class="value">${esc(b)}</div></div>`).join("");$("context").textContent=x.context;$("instruction").textContent=x.instruction;$("textA").textContent=x.response_a_text;$("textB").textContent=x.response_b_text;$("facts").textContent=`必须保留：${x.required_facts.join("、")||"无指定事实"}｜不得改变：${x.prohibited_changes.join("、")||"无"}`;preference="";document.querySelectorAll("#preference button").forEach(b=>b.classList.remove("active"));$("actionA").value="";$("actionB").value="";$("error").textContent=""}
document.querySelectorAll("#preference button").forEach(b=>b.onclick=()=>{preference=b.dataset.value;document.querySelectorAll("#preference button").forEach(q=>q.classList.toggle("active",q===b))});$("confidence").oninput=e=>$("confidenceValue").textContent=e.target.value;
$("next").onclick=()=>{const annotator=$("annotator").value.trim(),a=$("actionA").value,b=$("actionB").value;if(!annotator||!preference||!a||!b){$("error").textContent="请填写标注者 ID、偏好和两个处理方式。";return}const x=bundle.items[index];answers.push({pair_id:x.pair_id,scenario_id:x.scenario_id,annotator_id:annotator,response_a:x.response_a,response_b:x.response_b,preference,action_a:a,action_b:b,confidence:Number($("confidence").value),population:$("population").value.trim()?{group:$("population").value.trim()}: {},spans:[]});localStorage.setItem("shuorenhua_answers",JSON.stringify(answers));index++;render()};
function download(){if(!answers.length){$("error").textContent="还没有可导出的标注。";return}const body=answers.map(x=>JSON.stringify(x)).join("\n")+"\n";const url=URL.createObjectURL(new Blob([body],{type:"application/x-ndjson"}));const a=document.createElement("a");a.href=url;a.download="shuorenhua_judgments.jsonl";a.click();URL.revokeObjectURL(url)}$("export").onclick=download;$("exportDone").onclick=download;
fetch("/api/bundle").then(r=>r.json()).then(x=>{bundle=x;index=Math.min(answers.length,bundle.items.length);render()}).catch(e=>{$("progress").textContent="Load failed";$("setup").innerHTML=`<div class="error">${e}</div>`});
</script></body></html>'''


def _response(start_response: Callable, status: str, content_type: str, body: bytes) -> list[bytes]:
    start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


def app(environ: dict, start_response: Callable) -> Iterable[bytes]:
    path = environ.get("PATH_INFO", "/")
    if path == "/health":
        body = json.dumps({"status": "ok", "service": "shuorenhua-bench", "version": "0.2.0"}).encode("utf-8")
        return _response(start_response, "200 OK", "application/json; charset=utf-8", body)
    if path == "/api/bundle":
        if not BUNDLE_PATH.exists():
            body = json.dumps({"error": "annotation bundle not built"}).encode("utf-8")
            return _response(start_response, "503 Service Unavailable", "application/json", body)
        return _response(start_response, "200 OK", "application/json; charset=utf-8", BUNDLE_PATH.read_bytes())
    if path in {"/", ""}:
        return _response(start_response, "200 OK", "text/html; charset=utf-8", HTML.encode("utf-8"))
    return _response(start_response, "404 Not Found", "application/json; charset=utf-8", b'{"error":"not found"}')

