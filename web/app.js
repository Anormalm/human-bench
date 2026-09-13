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
  const modelJudged = x.evidence_kind === "model_judged";
  const synthetic = !modelJudged && x.evidence_kind !== "human";
  const notice = modelJudged ? "MODEL-JUDGED SCREENING · Predictions from one model judge. These are not human preference measurements." : synthetic ? "SOFTWARE DEMONSTRATION · All votes in this report are synthetic. These are not model performance results."
    : "HUMAN JUDGMENTS · Interpretation depends on study design, participant recruitment and the evidence checks below.";
  $("directUseHeading").textContent = modelJudged ? "Judge-predicted direct use" : "Direct use";
  $("uncertaintyCaption").textContent = "Ability is a relative log-strength estimate. " + x.uncertainty.scope;
  const statusNotice = x.ranking_status === "no_separation" ? " ALL OBSERVED PREFERENCES ARE TIES · No winner established." : "";
  $("reportNotice").textContent = notice + statusNotice; $("evidenceNotice").textContent = notice + statusNotice;
  const values = [[modelJudged ? (x.automatic_judge?.n_scenarios_judged ?? x.sample.n_scenarios) : x.sample.n_scenarios,
    modelJudged ? "Scenarios judged" : "Scenarios in this report"], [Object.keys(x.systems).length, "Systems compared"],
    [x.sample.n_judgments, modelJudged ? "Accepted model judgments" : synthetic ? "Synthetic demo judgments" : "Human judgments"],
    [x.uncertainty.n_independent_groups, modelJudged ? "Independent groups with judgments" : "Independent scenario groups"]];
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
    row.append(direct, node("td", s.wins + " / " + s.ties + " / " + s.losses), node("td", s.n_unique_response_rater_actions ?? "—"));
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
    checkLine("Optimizer", x.ranking_status === "withheld" ? "Not fitted" : x.pairwise_model.converged ? "Converged" : "Not converged"),
    checkLine("Bootstrap fits", u.successful_model_samples + " / " + u.requested_samples),
    checkLine("Position adjustment", x.pairwise_model.position_adjusted ? "Included" : "Not identifiable / off"),
    checkLine(modelJudged ? "Unresolved pairs" : "Under-annotated pairs", x.coverage.under_annotated_pairs.length),
    checkLine(modelJudged ? "Two-order agreement" : "Pairwise agreement",
      pct(modelJudged ? x.automatic_judge?.accepted_fraction : x.agreement.mean_pairwise_agreement)));
  if (x.automatic_judge) {
    $("checks").append(checkLine("Judge", x.automatic_judge.requested_model),
      checkLine("Accepted comparisons", x.automatic_judge.n_accepted_pairs + " / " + x.automatic_judge.n_pairs),
      checkLine("Excluded comparisons", x.automatic_judge.n_excluded_pairs),
      checkLine("Ranking", x.ranking_status === "withheld" ? "Withheld" : x.ranking_status === "no_separation" ? "All ties · no winner" : "Screening estimate"));
  }
  $("warnings").replaceChildren(...x.warnings.map(w => node("li", w)));
  const sensitivity = x.sensitivity;
  $("sensitivityPanel").classList.toggle("hidden", !sensitivity);
  $("sensitivityChecks").replaceChildren();
  $("sensitivityRows").replaceChildren();
  if (sensitivity) {
    const primary = sensitivity.primary_full_consistency;
    const diagnostic = sensitivity.diagnostic_stable_preference_only;
    const order = result => result.point_order?.join(" → ") || "No ordering established";
    $("sensitivityNotice").textContent = "Primary acceptance rule unchanged. " +
      (sensitivity.point_order_changed === true ? "The fitted ordering changes under the diagnostic rule." :
       sensitivity.point_order_changed === false ? "The fitted ordering is unchanged under the diagnostic rule." :
       "An ordering cannot be compared under both rules.");
    $("sensitivityChecks").append(
      checkLine("Primary · " + primary.n_pairs + " pairs", order(primary)),
      checkLine("Stable preference only · " + diagnostic.n_pairs + " pairs", order(diagnostic)));
    $("sensitivityRows").replaceChildren(...sensitivity.head_to_head_exclusion_bounds.map(c => {
      const row = node("tr");
      row.append(node("td", c.system_a + " / " + c.system_b),
        node("td", c.a_wins + " / " + c.ties + " / " + c.b_wins),
        node("td", c.n_excluded + " / " + c.n_planned),
        node("td", c.a_score_range_over_all_planned?.map(pct).join(" – ") || "Unavailable"));
      return row;
    }));
  }
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

function runSetup() {
  const count = Number($("runCount").value);
  const reasoning = $("runReasoning").value === "reasoning";
  const judgeReasoning = $("runJudgeReasoning").value === "reasoning";
  const endpoint = $("runEndpoint").value.trim(), keyEnv = $("runKeyEnv").value.trim();
  const url = new URL(endpoint);
  if (!(url.protocol === "https:" || (url.protocol === "http:" &&
        ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)))) {
    throw new Error("Use HTTPS or a local inference endpoint.");
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(keyEnv)) throw new Error("Enter an environment variable name.");
  const models = [$("runModelA").value.trim(), $("runModelB").value.trim(), $("runJudge").value.trim()];
  if (models.some(x => !x)) throw new Error("Enter both candidate models and a judge.");
  const common = {base_url: endpoint, api_key_env: keyEnv, retries: 2,
    temperature: reasoning ? null : 0.2, top_p: reasoning ? null : 1,
    max_tokens: reasoning ? 4096 : 512, token_parameter: reasoning ? "max_completion_tokens" : "max_tokens"};
  if (reasoning) common.reasoning_effort = "low";
  const judgeProfile = {...common, temperature: judgeReasoning ? null : 0,
    top_p: judgeReasoning ? null : 1, max_tokens: judgeReasoning ? 4096 : 768,
    token_parameter: judgeReasoning ? "max_completion_tokens" : "max_tokens"};
  if (judgeReasoning) judgeProfile.reasoning_effort = "low";
  else delete judgeProfile.reasoning_effort;
  return {count, config: {
    system_prompt: "你正在替用户撰写一条真实沟通消息。严格依据场景、关系、渠道和事实作答；不新增事实或承诺，只输出正文。",
    systems: models.slice(0, 2).map((model, i) => ({...common, system_id: "model-" + (i ? "b" : "a"), model})),
    judge: {...judgeProfile, model: models[2], response_format: $("runFormat").value}
  }};
}
function updateRunPlan() {
  const count = Number($("runCount").value);
  const command = ".\\.venv\\Scripts\\python.exe -m shuorenhua_bench.cli run --scenarios data/prompts/suite_zh_v0.3.jsonl --config bench-config.json --output studies/model-run --limit " + count;
  $("runPreview").textContent = command;
  $("runExecute").textContent = command + " --execute --max-requests " + count * 8;
  $("runPlan").textContent = count * 2 + " generated responses + " + count * 2 +
    " judge completions → up to " + count + " accepted comparisons. Cap: " + count * 8 +
    " HTTP attempts, allowing two attempts per completion.";
}
$("runCount").onchange = updateRunPlan;
$("downloadRunConfig").onclick = () => {
  try {
    const {config} = runSetup();
    const url = URL.createObjectURL(new Blob([JSON.stringify(config, null, 2) + "\n"], {type: "application/json"}));
    const link = node("a"); link.href = url; link.download = "bench-config.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); clearError();
  } catch (e) { error(e.message); }
};
updateRunPlan();

let judgeAudit = null, judgeAuditPage = 0;
function setJudgeAudit(x) {
  if (!x || x.schema_version !== "0.5" || x.report_kind !== "judge_audit" ||
      !x.judges || !Array.isArray(x.pairs) || !Array.isArray(x.cross_judge) ||
      !Array.isArray(x.warnings) || x.pairs.length > 100000) {
    throw new Error("Expected a v0.5 judge audit.");
  }
  for (const j of Object.values(x.judges)) {
    if (!j.order_diagnostics || !j.human_comparison) throw new Error("Audit is missing judge diagnostics.");
  }
  for (const p of x.pairs) {
    if (!p.candidate_a || !p.candidate_b || !p.judges) throw new Error("Audit is missing comparison data.");
    for (const [key, result] of Object.entries(p.judges)) {
      if (!x.judges[key] || !Array.isArray(result.observations)) throw new Error("Invalid judge observations.");
    }
  }
  judgeAudit = x; judgeAuditPage = 0;
  $("judgeAuditNotice").textContent = x.evidence_status === "human_reference_available"
    ? "HUMAN REFERENCE AVAILABLE · Agreement is conditional on the recruited raters and comparisons with a clear majority."
    : "HUMAN CALIBRATION PENDING · This audit measures model repeatability and agreement. It does not establish judge accuracy.";
  stats("judgeAuditStats", [[x.n_scenarios, "Fixed scenarios"], [Object.keys(x.judges).length, "Judge configurations"],
    [x.n_pairs, "Identical comparisons"], [x.n_human_judgments, "Human judgments"]]);
  $("judgeAuditRows").replaceChildren(...Object.values(x.judges).map(j => {
    const d = j.order_diagnostics, h = j.human_comparison;
    const row = node("tr"), name = node("td", j.requested_model);
    name.append(node("small", j.run_label));
    const agreement = node("td", pct(h.agreement));
    agreement.append(node("small", h.n_comparable_pairs + " comparable / " + h.n_reference_pairs + " reference pairs"));
    row.append(name, node("td", d.n_preference_consistent + " / " + d.n_comparable_pairs),
      node("td", d.n_actions_consistent + " / " + d.n_comparable_pairs),
      node("td", j.n_accepted_pairs + " / " + j.n_pairs), agreement);
    return row;
  }));
  $("crossJudgeChecks").replaceChildren(...x.cross_judge.map(c => checkLine(
    x.judges[c.judge_a].requested_model + " ↔ " + x.judges[c.judge_b].requested_model,
    pct(c.agreement) + " preference agreement · " + c.n_comparable_pairs + " / " + c.n_expected_pairs + " pairs comparable")));
  $("judgeAuditWarnings").replaceChildren(...x.warnings.map(w => node("li", w)));
  renderJudgeAuditPairs();
}
function renderJudgeAuditPairs() {
  if (!judgeAudit) return;
  const filter = $("auditFilter").value;
  const pairs = judgeAudit.pairs.filter(p => filter === "all" ||
    (filter === "human" ? Boolean(p.human_reference) : Object.values(p.judges).some(j => !j.accepted)));
  const pageCount = Math.max(1, Math.ceil(pairs.length / 20));
  judgeAuditPage = Math.min(judgeAuditPage, pageCount - 1);
  $("auditPrevious").disabled = judgeAuditPage === 0;
  $("auditNext").disabled = judgeAuditPage >= pageCount - 1;
  $("auditPageStatus").textContent = pairs.length ? "Page " + (judgeAuditPage + 1) + " / " + pageCount + " · " + pairs.length + " comparisons" : "0 comparisons";
  $("judgeAuditPairs").replaceChildren(...pairs.slice(judgeAuditPage * 20, (judgeAuditPage + 1) * 20).map(p => {
    const card = node("details", undefined, "panel audit-pair");
    card.append(node("summary", p.scenario_id + " · " + p.candidate_a.system + " vs " + p.candidate_b.system));
    card.append(node("p", p.context), node("p", p.instruction, "muted"));
    card.append(node("p", "Required facts: " + p.required_facts.join("; ") +
      " · Constraints: " + p.prohibited_changes.join("; "), "caption"));
    const candidates = node("div", undefined, "responses");
    for (const [side, candidate] of [["A", p.candidate_a], ["B", p.candidate_b]]) {
      const el = node("article", undefined, "response");
      el.append(node("strong", side + " · " + candidate.system), node("p", candidate.text)); candidates.append(el);
    }
    card.append(candidates);
    for (const [key, result] of Object.entries(p.judges)) {
      const block = node("div", undefined, "judge-observations");
      block.append(node("h3", judgeAudit.judges[key].requested_model + " · " + result.status.replaceAll("_", " ")));
      for (const o of result.observations) {
        const display = o.displayed_first === "A" ? "A → B" : "B → A";
        const detail = node("div", undefined, "judge-check");
        detail.append(node("strong", "Display " + display + " · Choice " + (o.preference || o.status) +
          " · Actions A / B: " + (o.action_a || "—") + " / " + (o.action_b || "—")));
        detail.append(node("p", o.rationale || o.raw_output || "Observation missing."));
        block.append(detail);
      }
      block.append(node("small", "Choices and actions above use the candidate labels on this page. A/B inside explanations refer to that check's displayed positions.", "muted"));
      card.append(block);
    }
    if (p.human_reference) {
      const h = p.human_reference;
      card.append(node("p", "Human reference: " + (h.majority || h.status.replaceAll("_", " ")) +
        " · " + h.n_raters + " raters · " + JSON.stringify(h.votes), "caption"));
    }
    return card;
  }));
  if (!pairs.length) $("judgeAuditPairs").append(node("p", "No pairs match this filter.", "muted"));
}
$("auditFilter").onchange = () => { judgeAuditPage = 0; renderJudgeAuditPairs(); };
$("auditPrevious").onclick = () => { if (judgeAuditPage > 0) judgeAuditPage--; renderJudgeAuditPairs(); };
$("auditNext").onclick = () => { judgeAuditPage++; renderJudgeAuditPairs(); };
$("judgeAuditFile").onchange = e => importFile(e, x => { setJudgeAudit(x); go("judgeAudit"); });
getJson("/api/judge-audit").then(setJudgeAudit).catch(() => {
  $("judgeAuditNotice").textContent = "No judge audit loaded. Run compare-judges on saved runs, then import its JSON report.";
});
