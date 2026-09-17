"use strict";
const $ = id => document.getElementById(id);
const node = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
let report = null, page = 0, timer = null;
function check(label, value) { const e = node('div', undefined, 'check'); e.append(node('span', label), node('strong', value)); return e; }
function render() {
  if (!report) return;
  const r = report, c = r.cost;
  $('wideNotice').textContent = 'MODEL-JUDGED SCREENING · ' + r.phase.replaceAll('_', ' ') +
    ' · No human preference or overall winner established.';
  $('wideUpdated').textContent = 'Snapshot: ' + new Date(r.updated_at).toLocaleString() + ' · Judge: ' + r.judge +
    (r.judge_provider_policy?.only ? ' · Provider: ' + r.judge_provider_policy.only.join(', ') : '');
  $('wideStats').replaceChildren(...[[r.n_models_planned, 'Model IDs selected'], [r.n_models_complete, 'Completed all scenarios'],
    [r.n_models_ranked, 'Models in ranking'], [r.n_accepted_pairs, 'Accepted comparisons']].map(([v,label]) => {
      const e = node('div', undefined, 'stat'); e.append(node('strong', v), node('span', label)); return e;
    }));
  $('wideChecks').replaceChildren(check('Scenarios per model', r.n_scenarios),
    check('Candidate responses saved', r.n_generation_successes + ' / ' + r.n_models_planned * r.n_scenarios),
    check('Judge checks saved', r.n_judge_checks_saved + ' / ' + r.n_pairs_planned * 2),
    check('Reported charges for these records', '$' + Number(c.reported_usd).toFixed(4)),
    ...(r.campaign_cost?.n_studies > 1 ? [check('Reported charges including earlier pass', '$' + Number(r.campaign_cost.reported_usd).toFixed(4))] : []),
    check('Charges plus reservations', '$' + Number(c.charged_or_reserved_usd).toFixed(4) + ' / $' + c.budget_usd),
    check('Requests with unknown cost', c.unknown_cost_requests), check('Recorded requests', c.attempts),
    ...(c.reused_requests ? [check('Reused generation records (no new calls)', c.reused_requests)] : []));
  $('wideBootstrap').textContent = 'Scenario families: ' + r.bootstrap.n_scenario_groups +
    ' · Bootstrap fits: ' + (r.bootstrap.attempts - r.bootstrap.lost_fits) + ' / ' + r.bootstrap.attempts +
    (r.bootstrap.intervals_withheld ? '. Intervals withheld because too many resamples lost connectivity or failed to fit.' :
      '. Intervals condition on successful connected fits and one fixed judge; they do not include judge error.');
  $('wideWarnings').replaceChildren(...r.warnings.map(w => node('li',w)));
  $('wideOrder').textContent = 'Comparison outcomes: ' + Object.entries(r.order_status_counts).map(([k,v]) => k.replaceAll('_',' ') + ': ' + v).join(' · ');
  const query = $('wideSearch').value.toLowerCase(), filter = $('wideFilter').value;
  const rows = r.rows.filter(x => (x.model + ' ' + x.name).toLowerCase().includes(query) &&
    (filter === 'all' || (filter === 'ranked' ? x.rank !== null : x.rank === null)));
  const pages = Math.max(1, Math.ceil(rows.length / 30)); page = Math.min(page, pages - 1);
  $('wideRows').replaceChildren(...rows.slice(page * 30, (page + 1) * 30).map(x => {
    const e = node('tr'); e.append(node('td', x.rank ?? '—'), node('td', x.model),
      node('td', x.rank_interval ? x.rank_interval.map(v => Math.round(v)).join(' – ') : 'Not established'),
      node('td', x.n_generated + ' / ' + x.n_scenarios), node('td', x.n_accepted + ' / ' + x.n_planned_comparisons),
      node('td', x.wins + ' / ' + x.ties + ' / ' + x.losses), node('td', x.status.replaceAll('_',' ') +
        (x.rank === null && x.generation_failures && Object.keys(x.generation_failures).length ? ' · ' + Object.entries(x.generation_failures).map(([k,v]) => k.replaceAll('_',' ') + ': ' + v).join(', ') : ''))); return e;
  }));
  $('widePage').textContent = rows.length + ' models · Page ' + (page + 1) + ' / ' + pages;
  $('widePrevious').disabled = page === 0; $('wideNext').disabled = page === pages - 1;
}
async function refresh() {
  clearTimeout(timer);
  try {
    const response = await fetch('/api/wide-report');
    if (!response.ok) throw new Error('No model screen is configured on this server.');
    const data = await response.json();
    if (data.report_kind !== 'wide_screen' || !Array.isArray(data.rows)) throw new Error('Invalid model screen report.');
    report = data; render();
    if (report.phase !== 'complete') timer = setTimeout(refresh, 10000);
  } catch (error) { $('wideNotice').textContent = error.message; }
}
$('wideSearch').oninput = $('wideFilter').onchange = () => { page = 0; render(); };
$('widePrevious').onclick = () => { page--; render(); };
$('wideNext').onclick = () => { page++; render(); };
$('refreshWide').onclick = refresh;
refresh();
