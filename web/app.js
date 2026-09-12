"use strict";
const $ = id => document.getElementById(id);
let bundle = null, report = null, answers = [], current = null, preference = "", spans = [];
let startedAt = 0, selectedSpan = null, storageKey = null, saving = false;
const pct = n => Number.isFinite(n) ? (n * 100).toFixed(1) + "%" : "—";
const num = n => Number.isFinite(n) ? n.toFixed(2) : "—";
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function error(message) { $("error").textContent = message; $("error").classList.remove("hidden"); }
function clearError() { $("error").classList.add("hidden"); }
function go(page) {
  document.querySelectorAll(".page").forEach(x => x.classList.toggle("hidden", x.id !== page));
  document.querySelectorAll(".nav").forEach(x => x.classList.toggle("active", x.dataset.page === page));
  clearError(); window.scrollTo({top: 0, behavior: "smooth"});
}
document.querySelectorAll("[data-page]").forEach(x => x.onclick = () => go(x.dataset.page));
document.querySelectorAll("[data-go]").forEach(x => x.onclick = () => go(x.dataset.go));
function stats(target, values) {
  $(target).replaceChildren(...values.map(([value, label]) => {
    const el = node("div", undefined, "stat");
    el.append(node("strong", value ?? "—"), node("small", label)); return el;
  }));
}
function validBundle(x) {
  if (!x || x.schema_version !== "0.3" || typeof x.study_id !== "string" ||
      typeof x.bundle_id !== "string" || !Array.isArray(x.items) || x.items.length > 100000) {
    throw new Error("This is not a supported v0.3 annotation packet.");
  }
  const ids = new Set();
  for (const item of x.items) {
    for (const field of ["pair_id", "scenario_id", "response_a", "response_b",
      "response_a_text", "response_b_text", "context", "instruction"]) {
      if (typeof item[field] !== "string" || !item[field]) throw new Error("Packet is missing " + field);
    }
    if (ids.has(item.pair_id) || item.response_a === item.response_b) throw new Error("Invalid pair IDs.");
    if (!Array.isArray(item.required_facts) || !Array.isArray(item.prohibited_changes)) throw new Error("Invalid constraints.");
    ids.add(item.pair_id);
  }
  return x;
}
function loadProgress() {
  if (!bundle) return;
  current = null;
  const annotator = $("annotator").value.trim();
  storageKey = "shuorenhua:v03:" + bundle.study_id + ":" + bundle.bundle_id + ":" + annotator;
  const raw = localStorage.getItem(storageKey);
  answers = raw ? JSON.parse(raw) : [];
  if (!Array.isArray(answers)) throw new Error("Saved progress is damaged. Export/recover browser data before proceeding.");
  const items = new Map(bundle.items.map(x => [x.pair_id, x]));
  const seen = new Set();
  for (const answer of answers) {
    const item = items.get(answer.pair_id);
    if (!item || seen.has(answer.pair_id) || answer.study_id !== bundle.study_id ||
        answer.annotator_id !== annotator || answer.response_a !== item.response_a ||
        answer.response_b !== item.response_b) {
      throw new Error("Saved progress does not match this packet. It has not been overwritten.");
    }
    seen.add(answer.pair_id);
  }
  renderTask();
}
function setBundle(x, remember = false) {
  bundle = validBundle(x);
  $("annotator").value = bundle.assignment_id || "";
  $("annotator").disabled = Boolean(bundle.assignment_id);
  $("annotationNotice").textContent = bundle.demo
    ? "SOFTWARE DEMO · These are controlled example texts. Your test annotations are marked synthetic."
    : "Assigned study packet · Your judgments stay in this browser. Export them when finished.";
  loadProgress();
  if (remember) localStorage.setItem("shuorenhua:v03:active-packet", JSON.stringify(bundle));
}
$("annotator").onchange = () => { try { loadProgress(); } catch (e) { error(e.message); } };
function renderTask() {
  const completed = new Set(answers.map(x => x.pair_id));
  current = bundle.items.find(x => !completed.has(x.pair_id));
  $("progress").textContent = answers.length + " / " + bundle.items.length;
  $("progressBar").style.width = (100 * answers.length / Math.max(1, bundle.items.length)) + "%";
  $("navCount").textContent = bundle.items.length ? "(" + (bundle.items.length - answers.length) + ")" : "";
  $("done").classList.toggle("hidden", Boolean(current));
  $("task").classList.toggle("hidden", !current);
  if (!current) return;
  $("contextTags").replaceChildren(...[current.genre, current.relationship, current.intent, current.channel].map(x => node("span", x)));
  $("context").textContent = current.context;
  $("instruction").textContent = current.instruction;
  $("facts").textContent = "必须保留：" + current.required_facts.join("；") + "。限制：" + current.prohibited_changes.join("；");
  $("textA").textContent = current.response_a_text;
  $("textB").textContent = current.response_b_text;
  preference = ""; spans = []; selectedSpan = null;
  $("selectedQuote").value = "";
  $("actionA").value = ""; $("actionB").value = "";
  $("confidence").value = 3; $("confidenceValue").textContent = "3 / 5";
  document.querySelectorAll("#preference button").forEach(x => { x.classList.remove("active"); x.setAttribute("aria-pressed", "false"); });
  $("spanList").replaceChildren(); startedAt = performance.now();
}
document.querySelectorAll("#preference button").forEach(button => {
  button.onclick = () => {
    preference = button.dataset.value;
    document.querySelectorAll("#preference button").forEach(x => {
      const active = x === button; x.classList.toggle("active", active); x.setAttribute("aria-pressed", String(active));
    });
  };
});
$("confidence").oninput = () => $("confidenceValue").textContent = $("confidence").value + " / 5";
$("next").onclick = () => {
  if (!current || saving) return;
  clearError();
  const annotator = $("annotator").value.trim();
  if (!annotator || !preference || !$("actionA").value || !$("actionB").value) {
    error("Please choose a preference and both actions, and enter your assigned pseudonym."); return;
  }
  saving = true;
  try {
    const answer = {
      pair_id: current.pair_id, scenario_id: current.scenario_id, response_a: current.response_a,
      response_b: current.response_b, annotator_id: annotator, preference,
      action_a: $("actionA").value, action_b: $("actionB").value, confidence: Number($("confidence").value),
      duration_seconds: Math.max(0, (performance.now() - startedAt) / 1000),
      population: $("population").value.trim() ? {group: $("population").value.trim()} : {},
      spans, study_id: bundle.study_id, assignment_id: bundle.assignment_id || null,
      evidence_kind: bundle.demo ? "synthetic" : "human"
    };
    const next = [...answers, answer];
    localStorage.setItem(storageKey, JSON.stringify(next)); // Persist before advancing.
    answers = next; renderTask();
  } catch (e) { error("Could not save progress: " + e.message + ". The current judgment has not been advanced."); }
  finally { saving = false; }
};
function download() {
  if (!answers.length) { error("No saved judgments to export."); return; }
  const url = URL.createObjectURL(new Blob([answers.map(x => JSON.stringify(x)).join("\n") + "\n"], {type: "application/x-ndjson"}));
  const link = node("a"); link.href = url;
  link.download = "shuorenhua-" + (bundle.assignment_id || "judgments") + ".jsonl";
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("export").onclick = download; $("exportDone").onclick = download;
for (const [id, side] of [["textA", "a"], ["textB", "b"]]) {
  $(id).onmouseup = () => {
    const selection = window.getSelection();
    if (!selection.rangeCount || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (!$(id).contains(range.startContainer) || !$(id).contains(range.endContainer)) return;
    const prefix = range.cloneRange(); prefix.selectNodeContents($(id)); prefix.setEnd(range.startContainer, range.startOffset);
    const start = Array.from(prefix.toString()).length, quote = range.toString();
    selectedSpan = {response_id: current["response_" + side], start, end: start + Array.from(quote).length, quote};
    $("selectedQuote").value = quote;
  };
}
function renderSpans() {
  $("spanList").replaceChildren(...spans.map((span, index) => {
    const li = node("li", span.type + " · characters " + span.start + "–" + span.end);
    const remove = node("button", "Remove"); remove.onclick = () => { spans.splice(index, 1); renderSpans(); };
    li.append(remove); return li;
  }));
}
$("addSpan").onclick = () => {
  if (!selectedSpan) { error("Select a passage in response A or B first."); return; }
  const {quote, ...span} = selectedSpan;
  spans.push({...span, type: $("spanType").value, severity: 2});
  selectedSpan = null; $("selectedQuote").value = ""; renderSpans(); clearError();
};
async function importFile(event, setter) {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 50 * 1024 * 1024) throw new Error("File exceeds the 50 MB browser import limit.");
    setter(JSON.parse(await file.text())); clearError();
  } catch (e) { error("Import failed: " + e.message); }
  event.target.value = "";
}
for (const id of ["packetFile", "packetFile2"]) $(id).onchange = e => importFile(e, x => { setBundle(x, true); go("annotate"); });
$("reportFile").onchange = e => importFile(e, x => { setReport(x); go("results"); });
function checkLine(label, value) { const div = node("div", undefined, "check"); div.append(node("span", label), node("strong", value)); return div; }
function setReport(x) {
  if (!x || x.schema_version !== "0.3" || !x.systems || !x.sample || !x.uncertainty || !x.pairwise_model ||
      !x.coverage || !x.agreement || !Array.isArray(x.contrasts) || !Array.isArray(x.warnings)) {
    throw new Error("Expected a v0.3 evaluation report.");
  }
  report = x;
  const synthetic = x.evidence_kind !== "human";
  const notice = synthetic ? "SOFTWARE DEMONSTRATION · All votes in this report are synthetic. These are not model performance results."
    : "HUMAN JUDGMENTS · Interpretation depends on study design, participant recruitment and the evidence checks below.";
  $("reportNotice").textContent = notice; $("evidenceNotice").textContent = notice;
  const values = [[x.sample.n_scenarios, "Scenarios in this report"], [Object.keys(x.systems).length, "Systems compared"],
    [x.sample.n_judgments, synthetic ? "Synthetic demo judgments" : "Human judgments"], [x.uncertainty.n_independent_groups, "Independent scenario groups"]];
  stats("reportStats", values); stats("overviewStats", values);
  const entries = Object.entries(x.systems).sort((a, b) => (b[1].ability ?? -Infinity) - (a[1].ability ?? -Infinity));
  const all = entries.flatMap(([, s]) => s.ability_95ci_cluster_bootstrap || [s.ability]).filter(Number.isFinite);
  const min = Math.min(-1, ...all), max = Math.max(1, ...all);
  const position = v => Math.max(0, Math.min(100, 100 * (v - min) / (max - min)));
  $("systemRows").replaceChildren(...entries.map(([name, s]) => {
    const row = node("tr"); row.append(node("td", name));
    const cell = node("td"), estimate = node("div", undefined, "estimate"), plot = node("div", undefined, "interval");
    const ci = s.ability_95ci_cluster_bootstrap;
    if (ci) { const bar = node("i", undefined, "ci"); bar.style.left = position(ci[0]) + "%"; bar.style.width = (position(ci[1]) - position(ci[0])) + "%"; plot.append(bar); }
    if (Number.isFinite(s.ability)) { const dot = node("i", undefined, "point"); dot.style.left = position(s.ability) + "%"; plot.append(dot); }
    const text = node("span", num(s.ability)); text.append(node("small", ci ? "[" + ci.map(num).join(", ") + "]" : "interval unavailable"));
    estimate.append(plot, text); cell.append(estimate); row.append(cell);
    const direct = node("td", pct(s.direct_use_rate));
    if (s.direct_use_95ci_cluster_bootstrap) direct.append(node("small", s.direct_use_95ci_cluster_bootstrap.map(pct).join(" – ")));
    row.append(direct, node("td", s.wins + " / " + s.ties + " / " + s.losses), node("td", s.n_unique_response_rater_actions));
    return row;
  }));
  $("contrasts").replaceChildren(...x.contrasts.map(c => {
    const el = node("div", undefined, "comparison"), names = node("div", undefined, "comparison-names");
    names.append(node("span", c.system_a), node("span", c.system_b));
    const bar = node("div", undefined, "comparison-track"), fill = node("i"); fill.style.width = pct(c.tie_adjusted_preference_probability_a); bar.append(fill);
    el.append(names, bar, node("small", pct(c.tie_adjusted_preference_probability_a) + " preference for left system · " +
      (c.separated_exploratory ? "exploratory intervals separated" : "separation not established")));
    return el;
  }));
  const u = x.uncertainty;
  $("checks").replaceChildren(
    checkLine("Optimizer", x.pairwise_model.converged ? "Converged" : "Not converged"),
    checkLine("Bootstrap fits", u.successful_model_samples + " / " + u.requested_samples),
    checkLine("Position adjustment", x.pairwise_model.position_adjusted ? "Included" : "Not identifiable / off"),
    checkLine("Under-annotated pairs", x.coverage.under_annotated_pairs.length),
    checkLine("Pairwise agreement", pct(x.agreement.mean_pairwise_agreement)));
  $("warnings").replaceChildren(...x.warnings.map(w => node("li", w)));
  renderSlices();
}
function renderSlices() {
  const groups = report?.slices?.[$("sliceDimension").value] || {};
  $("slices").replaceChildren(...Object.entries(groups).map(([name, slice]) => {
    const div = node("div", undefined, "slice");
    div.append(node("h3", name.replaceAll("_", " ")), node("small", slice.n_scenarios + " scenarios · " + slice.n_judgments + " judgments"));
    for (const [system, rates] of Object.entries(slice.direct_use)) div.append(checkLine(system, pct(rates.send)));
    return div;
  }));
}
$("sliceDimension").onchange = renderSlices;
async function getJson(url) { const response = await fetch(url); if (!response.ok) throw new Error(url + " unavailable"); return response.json(); }
try {
  const remembered = localStorage.getItem("shuorenhua:v03:active-packet");
  if (remembered) setBundle(JSON.parse(remembered));
  else getJson("/api/bundle").then(x => setBundle(x)).catch(e => error(e.message + ". Import a study packet to begin."));
} catch (e) { error(e.message + ". Import your packet again to recover saved progress."); }
getJson("/api/report").then(setReport).catch(() => {
  $("evidenceNotice").textContent = "No evaluation report loaded. Import a report on the Results page.";
  $("reportNotice").textContent = "Import a v0.3 report to inspect results.";
});
