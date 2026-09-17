"use strict";
const $ = id => document.getElementById(id);
const node = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
let report = null, page = 0, timer = null;
let refreshSequence = 0;
let sortKey = 'rank', sortDirection = 1;
const number = value => Number(value).toLocaleString();
const money = value => typeof value === 'number' && Number.isFinite(value) ? '$' + value.toFixed(4) : '—';
const organization = row => row.model.split('/')[0] === 'meta-llama' ? 'meta' : row.model.split('/')[0];
const displayName = row => (row.name || row.model).replace(/^[^:]+:\s*/, '');
const orgNames = {qwen:'Qwen',openai:'OpenAI',google:'Google',deepseek:'DeepSeek',anthropic:'Anthropic',
  'z-ai':'Z.AI','x-ai':'xAI','bytedance-seed':'ByteDance Seed',moonshotai:'Moonshot AI',
  meta:'Meta',mistralai:'Mistral',nvidia:'NVIDIA','ibm-granite':'IBM Granite',minimax:'MiniMax',
  'arcee-ai':'Arcee AI',cognitivecomputations:'Cognitive Computations',inclusionai:'InclusionAI',
  nousresearch:'Nous Research',rekaai:'Reka AI',stepfun:'StepFun',thinkingmachines:'Thinking Machines',
  thedrummer:'TheDrummer',sao10k:'Sao10K'};
const orgLabel = value => orgNames[value] || value.replaceAll('-', ' ').replace(/\b\w/g, c => c.toUpperCase());
function rankInterval(row) {
  return Array.isArray(row.rank_interval) && row.rank_interval.length === 2 && row.rank_interval.every(Number.isFinite)
    ? [Math.floor(row.rank_interval[0]), Math.ceil(row.rank_interval[1])] : null;
}
function setView(chart) {
  $('tableView').hidden = chart; $('chartView').hidden = !chart;
  for (const [id, selected] of [['tableTab', !chart], ['chartTab', chart]]) {
    $(id).setAttribute('aria-selected', String(selected)); $(id).tabIndex = selected ? 0 : -1;
  }
}
function updateOrganizations() {
  const selected = $('wideOrganization').value;
  const values = [...new Set(report.rows.map(organization))].sort((a,b) => orgLabel(a).localeCompare(orgLabel(b)));
  $('wideOrganization').replaceChildren(...['all', ...values].map(value => {
    const option = node('option', value === 'all' ? 'All organizations' : orgLabel(value)); option.value = value; return option;
  }));
  $('wideOrganization').value = values.includes(selected) ? selected : 'all';
}
function filteredRows() {
  const query = $('wideSearch').value.trim().toLowerCase(), filter = $('wideFilter').value;
  return report.rows.filter(x => (x.model + ' ' + x.name + ' ' + orgLabel(organization(x))).toLowerCase().includes(query) &&
    ($('wideOrganization').value === 'all' || organization(x) === $('wideOrganization').value) &&
    (filter === 'all' || (filter === 'complete' && x.n_generated === x.n_scenarios) ||
      (filter === 'partial' && x.n_generated < x.n_scenarios) ||
      (filter === 'ranked' && x.rank != null) || (filter === 'unranked' && x.rank == null)));
}
function sortedRows(rows) {
  return [...rows].sort((a,b) => {
    const av = sortKey === 'name' ? displayName(a) : a[sortKey], bv = sortKey === 'name' ? displayName(b) : b[sortKey];
    if (av == null || bv == null) return av == null && bv == null ? a.model.localeCompare(b.model) : av == null ? 1 : -1;
    const diff = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return diff * sortDirection || (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.model.localeCompare(b.model);
  });
}
function coverageCell(count, total, cls) {
  const cell = node('td', undefined, cls), track = node('div', undefined, 'mini-track'), bar = node('i');
  cell.append(node('span', number(count) + ' '), node('small', '/ ' + number(total)));
  bar.style.width = Math.max(0, Math.min(100, total ? count / total * 100 : 0)) + '%';
  track.setAttribute('aria-hidden', 'true'); track.append(bar); cell.append(track); return cell;
}
function modelRow(x) {
  const row = node('tr'), model = node('td', undefined, 'model-cell'), identity = node('div', undefined, 'model-identity');
  const org = organization(x), label = orgLabel(org), mark = node('span', label.replace(/[^A-Za-z]/g, '').slice(0,2).toUpperCase(), 'model-mark');
  const hue = [...org].reduce((n,c) => n + c.charCodeAt(0), 0) % 360;
  mark.style.setProperty('--org-bg', `hsl(${hue} 35% 94%)`); mark.style.setProperty('--org-color', `hsl(${hue} 35% 35%)`);
  mark.setAttribute('aria-hidden', 'true');
  const name = node('div'); name.append(node('strong', displayName(x)), node('small', x.model));
  identity.append(mark, name); model.append(identity);
  const change = node('td', undefined, 'rank-change ' + (x.rank_change > 0 ? 'up' : x.rank_change < 0 ? 'down' : 'neutral'));
  change.textContent = x.rank_change == null ? '—' : (x.rank_change > 0 ? '+' : '') + x.rank_change;
  change.title = x.previous_rank == null ? 'No earlier estimate' : 'Earlier point rank: ' + x.previous_rank;
  const ci = node('td'), bounds = rankInterval(x);
  ci.append(node('span', bounds ? bounds.join(' – ') : 'Unavailable', bounds ? 'rank-range' : 'unavailable'));
  const status = node('td', undefined, 'status-cell'), partial = x.n_generated < x.n_scenarios;
  status.append(node('span', x.rank != null ? (partial ? 'Partial responses' : 'Ranked') : x.status.replaceAll('_',' '),
    'status-label' + (partial ? ' partial' : x.rank == null ? ' pending' : '')));
  if (Object.keys(x.generation_failures || {}).length) status.append(node('small', Object.entries(x.generation_failures)
    .map(([k,v]) => k.replaceAll('_',' ') + ': ' + v).join(' · ')));
  row.append(node('td', x.rank ?? '—'), model, change, ci,
    coverageCell(x.n_generated, x.n_scenarios, 'coverage-cell'), coverageCell(x.n_accepted, x.n_planned_comparisons, 'pair-cell'),
    node('td', x.wins + ' / ' + x.ties + ' / ' + x.losses, 'outcomes'), node('td', money(x.generation_reported_usd), 'cost-cell'), status);
  return row;
}
function renderChart(rows) {
  const best = rows.filter(x => x.rank != null).sort((a,b) => a.rank-b.rank || a.model.localeCompare(b.model)).slice(0,10);
  $('wideChart').replaceChildren();
  $('chartDescription').textContent = best.length ? 'Top ' + best.length + ' matching models by point rank. Lower ranks are better.' +
    (best.some(x => rankInterval(x)) ? '' : ' Intervals are unavailable in this snapshot; only point estimates are shown.') : 'No matching point estimates to display.';
  if (!best.length) { $('wideChart').append(node('p', 'No ranked models match these filters.', 'small-note')); return; }
  const maximum = Math.max(2, Math.ceil(Math.max(...best.map(x => rankInterval(x)?.[1] ?? x.rank)) / 10) * 10);
  const position = value => Math.max(0, Math.min(100, (value - 1) / (maximum - 1) * 100));
  const axis = node('div', undefined, 'rank-chart-axis'), ticks = node('div', undefined, 'axis-ticks');
  for (let i=0;i<5;i++) ticks.append(node('span', Math.round(1 + (maximum-1) * i / 4)));
  axis.append(node('span', 'Model / point rank'), ticks, node('span', '95% interval')); $('wideChart').append(axis);
  for (const x of best) {
    const bounds = rankInterval(x), button = node('button', undefined, 'rank-chart-row'), label = node('span', undefined, 'chart-model');
    label.append(node('b', x.rank), node('span', displayName(x))); button.title = x.model;
    button.setAttribute('aria-label', displayName(x) + ', point rank ' + x.rank + ', ' +
      (bounds ? '95% rank interval ' + bounds.join(' to ') : 'interval unavailable') + '. Find in table.');
    const track = node('span', undefined, 'chart-track'); track.setAttribute('aria-hidden', 'true');
    track.style.setProperty('--point', position(x.rank) + '%');
    if (bounds) {
      track.style.setProperty('--low', position(bounds[0]) + '%');
      track.style.setProperty('--range', (position(bounds[1]) - position(bounds[0])) + '%');
      track.append(node('i', undefined, 'chart-band'));
    }
    track.append(node('i', undefined, 'chart-point'));
    button.append(label, track, node('span', bounds ? bounds.join('–') : 'Unavailable', 'chart-value'));
    button.onclick = () => { $('wideSearch').value = x.model; page = 0; setView(false); render(); $('wideSearch').focus(); };
    $('wideChart').append(button);
  }
}
function check(label, value) { const e = node('div', undefined, 'check'); e.append(node('span', label), node('strong', value)); return e; }
function render() {
  if (!report) return;
  const r = report, c = r.cost;
  $('wideNotice').textContent = 'Study ' + r.phase.replaceAll('_', ' ') + ' · Exploratory estimates';
  $('wideUpdated').textContent = 'Updated ' + new Date(r.updated_at).toLocaleDateString() + ' · Judge: ' + r.judge;
  $('wideStats').replaceChildren(...[[number(r.n_models_ranked), 'Models ranked', number(r.n_models_planned) + ' selected · ' + r.n_models_complete + ' complete'],
    [number(r.n_scenarios), 'Scenario families', number(r.n_generation_successes) + ' usable responses'],
    [number(r.n_accepted_pairs), 'Accepted comparisons', number(r.n_judge_checks_saved) + ' judge checks saved'],
    ['$' + Number(c.reported_usd).toFixed(2), 'Reported study cost', c.reused_requests ? 'Includes reused records · USD' : 'Generation + judging · USD']].map(([v,label,note]) => {
      const e = node('article', undefined, 'summary-card'); e.append(node('span', label, 'card-label'), node('strong', v), node('small', note)); return e;
    }));
  $('wideChecks').replaceChildren(check('Snapshot', new Date(r.updated_at).toLocaleString()), check('Judge', r.judge),
    check('Judge provider policy', r.judge_provider_policy?.only?.join(', ') || 'Default routing'), check('Scenarios per model', r.n_scenarios),
    check('Candidate responses saved', r.n_generation_successes + ' / ' + r.n_models_planned * r.n_scenarios),
    check('Judge checks processed', r.n_judge_checks_saved + ' / ' + r.n_pairs_planned * 2),
    check('Reported charges for these records', '$' + Number(c.reported_usd).toFixed(4)),
    ...(r.campaign_cost?.n_studies > 1 ? [check('Reported charges including earlier pass', '$' + Number(r.campaign_cost.reported_usd).toFixed(4))] : []),
    check('Charges plus reservations', '$' + Number(c.charged_or_reserved_usd).toFixed(4) + ' / $' + c.budget_usd),
    check('Requests with unknown cost', c.unknown_cost_requests), check('Recorded requests', c.attempts),
    ...(c.reused_requests ? [check('Reused request records (no new calls)', c.reused_requests)] : []),
    ...(c.reused_judge_requests ? [check('Reused generations / judge checks', c.reused_generation_requests + ' / ' + c.reused_judge_requests)] : []),
    ...(r.n_judge_checks_skipped ? [check('Checks skipped for missing candidate text', r.n_judge_checks_skipped)] : []));
  $('wideBaseline').textContent = r.baseline_n_scenarios ? 'Change vs. ' + r.baseline_n_scenarios +
    ' scenarios · Descriptive movement, not significant improvement.' : 'Point estimates from this snapshot · No earlier rank comparison.';
  $('wideBootstrap').textContent = 'Scenario families: ' + r.bootstrap.n_scenario_groups +
    ' · Bootstrap fits: ' + (r.bootstrap.attempts - r.bootstrap.lost_fits) + ' / ' + r.bootstrap.attempts +
    (r.bootstrap.intervals_withheld ? '. Intervals withheld because too many resamples lost connectivity or failed to fit.' :
      '. Intervals condition on successful connected fits and one fixed judge; they do not include judge error.');
  $('wideWarnings').replaceChildren(...r.warnings.map(w => node('li',w)));
  $('wideOrder').textContent = 'Comparison outcomes: ' + Object.entries(r.order_status_counts).map(([k,v]) => k.replaceAll('_',' ') + ': ' + v).join(' · ');
  const matches = filteredRows(), rows = sortedRows(matches);
  const pages = Math.max(1, Math.ceil(rows.length / 30)); page = Math.min(page, pages - 1);
  $('wideRows').replaceChildren(...rows.slice(page * 30, (page + 1) * 30).map(modelRow));
  if (!rows.length) { const empty = node('tr'), cell = node('td', 'No models match. Try another search or reset the filters.', 'empty-cell'); cell.colSpan = 9; empty.append(cell); $('wideRows').append(empty); }
  $('wideCount').textContent = number(rows.length) + ' of ' + number(r.rows.length) + ' model IDs';
  for (const button of document.querySelectorAll('[data-sort]')) {
    const active = button.dataset.sort === sortKey;
    if (active) button.parentElement.setAttribute('aria-sort', sortDirection === 1 ? 'ascending' : 'descending');
    else button.parentElement.removeAttribute('aria-sort');
    button.querySelector('.sort-arrow').textContent = active ? (sortDirection === 1 ? '↑' : '↓') : '↕';
  }
  renderChart(matches);
  $('widePage').textContent = rows.length + ' models · Page ' + (page + 1) + ' / ' + pages;
  $('widePrevious').disabled = page === 0; $('wideNext').disabled = page === pages - 1;
}
async function refresh() {
  clearTimeout(timer);
  const sequence = ++refreshSequence;
  const selected = $('wideStudy').value;
  const endpoint = selected === 'baseline' ? '/api/wide-baseline' : '/api/wide-report';
  try {
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error(selected === 'baseline' ? 'No earlier snapshot is configured on this server.' : 'No model screen is configured on this server.');
    const data = await response.json();
    if (sequence !== refreshSequence) return;
    if (data.report_kind !== 'wide_screen' || !Array.isArray(data.rows)) throw new Error('Invalid model screen report.');
    report = data; updateOrganizations(); $('wideDownload').href = endpoint; $('wideDownload').hidden = false; render();
    if (report.phase !== 'complete') timer = setTimeout(refresh, 10000);
  } catch (error) {
    if (sequence !== refreshSequence) return;
    report = null; $('wideRows').replaceChildren(); $('wideStats').replaceChildren(); $('wideChecks').replaceChildren(); $('wideChart').replaceChildren();
    for (const id of ['wideUpdated', 'wideBaseline', 'wideBootstrap', 'wideOrder']) $(id).textContent = '';
    $('wideWarnings').replaceChildren(); $('wideDownload').hidden = true;
    $('widePrevious').disabled = $('wideNext').disabled = true;
    $('wideNotice').textContent = error.message; $('widePage').textContent = 'No report loaded'; $('wideCount').textContent = 'No report loaded';
  }
}
$('wideStudy').onchange = () => { page = 0; refresh(); };
$('wideSearch').oninput = $('wideFilter').onchange = $('wideOrganization').onchange = () => { page = 0; render(); };
$('wideReset').onclick = () => {
  $('wideSearch').value = ''; $('wideFilter').value = $('wideOrganization').value = 'all';
  sortKey = 'rank'; sortDirection = 1; page = 0; render();
};
for (const button of document.querySelectorAll('[data-sort]')) button.onclick = () => {
  const key = button.dataset.sort;
  sortDirection = sortKey === key ? -sortDirection : ['rank','name','generation_reported_usd'].includes(key) ? 1 : -1;
  sortKey = key; page = 0; render();
};
$('tableTab').onclick = () => setView(false); $('chartTab').onclick = () => setView(true);
for (const id of ['tableTab','chartTab']) $(id).onkeydown = event => {
  if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
    event.preventDefault(); const chart = event.key === 'End' || (event.key !== 'Home' && id === 'tableTab');
    setView(chart); $(chart ? 'chartTab' : 'tableTab').focus();
  }
};
$('widePrevious').onclick = () => { page--; render(); };
$('wideNext').onclick = () => { page++; render(); };
$('refreshWide').onclick = refresh;
refresh();
