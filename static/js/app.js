/* ═══════════════════════════════════════════
   Cricket Analytics — Frontend Logic
═══════════════════════════════════════════ */

'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentMatchId  = null;
let currentInnings  = 1;
let manhattanChart  = null;
let jobPollInterval = null;
let tooltip         = null;

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------
const $  = id => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls)  e.className   = cls;
  if (text) e.textContent = text;
  return e;
};

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function createTooltip() {
  tooltip = el('div', 'tooltip');
  tooltip.style.display = 'none';
  document.body.appendChild(tooltip);
  document.addEventListener('mousemove', e => {
    if (tooltip.style.display === 'none') return;
    tooltip.style.left = (e.clientX + 12) + 'px';
    tooltip.style.top  = (e.clientY + 12) + 'px';
  });
}

function showTip(text) { tooltip.textContent = text; tooltip.style.display = 'block'; }
function hideTip()      { tooltip.style.display = 'none'; }

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  $(`view-${name}`).classList.add('active');
  document.querySelector(`.nav-btn[data-view="${name}"]`)?.classList.add('active');
}

// ---------------------------------------------------------------------------
// Job polling
// ---------------------------------------------------------------------------
function startJobPoll(jobId, onDone) {
  clearInterval(jobPollInterval);
  const statusEl = $('jobStatus');

  const render = job => {
    statusEl.classList.remove('hidden', 'error', 'done');
    if (job.status === 'done') {
      statusEl.classList.add('done');
      statusEl.innerHTML = `<span>&#10003; ${job.message}</span>`;
      clearInterval(jobPollInterval);
      onDone && onDone();
    } else if (job.status === 'failed') {
      statusEl.classList.add('error');
      statusEl.innerHTML = `<span>&#10005; ${job.message}</span>`;
      clearInterval(jobPollInterval);
    } else {
      const pct = job.progress || 0;
      statusEl.innerHTML = `
        <div class="spinner"></div>
        <span>${job.message || 'Working…'}</span>
        <div class="progress-bar-wrap">
          <div class="progress-bar" style="width:${pct}%"></div>
        </div>
        <span>${pct}%</span>`;
    }
  };

  jobPollInterval = setInterval(async () => {
    try {
      const job = await api(`/api/job/${jobId}`);
      render(job);
    } catch (_) { /* ignore */ }
  }, 1500);

  // Immediate first poll
  api(`/api/job/${jobId}`).then(render).catch(() => {});
}

// ---------------------------------------------------------------------------
// Match Library
// ---------------------------------------------------------------------------
async function loadLibrary() {
  const grid = $('matchGrid');
  try {
    const matches = await api('/api/matches');
    if (!matches.length) {
      grid.innerHTML = '<div class="empty-state">No matches yet. Paste a CricInfo URL above.</div>';
      return;
    }
    grid.innerHTML = '';
    matches.forEach(m => {
      const card = el('div', `match-card mc-status-${m.status}`);
      card.innerHTML = `
        <div class="mc-type">${m.match_type || 'Match'}</div>
        <div class="mc-title">${m.title || `${m.team1} vs ${m.team2}`}</div>
        <div class="mc-venue">${[m.venue, m.match_date].filter(Boolean).join(' &bull; ')}</div>
        <div class="mc-result">${m.result || ''}</div>
        <span class="mc-status ${m.status}">${m.status}</span>`;
      if (m.status === 'done') {
        card.addEventListener('click', () => openMatch(m.match_id));
      }
      grid.appendChild(card);
    });
  } catch (e) {
    grid.innerHTML = `<div class="empty-state" style="color:var(--danger)">Error loading matches: ${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Match Detail
// ---------------------------------------------------------------------------
async function openMatch(matchId) {
  currentMatchId = matchId;
  currentInnings = 1;
  showView('match');

  try {
    const match = await api(`/api/match/${matchId}`);
    renderMatchHeader(match);
    renderInningsTabs(match.innings, matchId);
    await loadInningsData(matchId, 1, match.innings);
  } catch (e) {
    $('matchHeader').innerHTML = `<span style="color:var(--danger)">Error: ${e.message}</span>`;
  }
}

function renderMatchHeader(match) {
  const h = $('matchHeader');
  h.innerHTML = `
    <div>
      <button class="back-btn" id="backBtn">&#8592; Library</button>
    </div>
    <div style="flex:1; min-width:0;">
      <div class="mh-title">${match.title || `${match.team1} vs ${match.team2}`}</div>
      <div class="mh-meta">${[match.venue, match.match_date, match.match_type].filter(Boolean).join(' &bull; ')}</div>
      <div class="mh-result">${match.result || ''}</div>
    </div>`;
  $('backBtn').addEventListener('click', () => { showView('library'); loadLibrary(); });
}

function renderInningsTabs(innings, matchId) {
  const tabs = $('inningsTabs');
  tabs.innerHTML = '';
  innings.forEach(inn => {
    const tab = el('button', `inn-tab${inn.innings_number === 1 ? ' active' : ''}`,
      `${inn.batting_team || `Innings ${inn.innings_number}`}` +
      (inn.total_runs != null ? ` — ${inn.total_runs}/${inn.total_wickets}` : ''));
    tab.dataset.innings = inn.innings_number;
    tab.addEventListener('click', async () => {
      document.querySelectorAll('.inn-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      currentInnings = inn.innings_number;
      await loadInningsData(matchId, inn.innings_number, innings);
    });
    tabs.appendChild(tab);
  });
}

async function loadInningsData(matchId, inningsNumber, allInnings) {
  // Reset filters
  ['filterBowler','filterBatsman','filterLength','filterLine','filterPhase'].forEach(id => {
    $(id).value = '';
  });

  await Promise.all([
    renderDeliveries(matchId, inningsNumber),
    renderManhattan(matchId, inningsNumber),
    renderStats(matchId, inningsNumber, allInnings),
  ]);
  populateFilterDropdowns(matchId, inningsNumber);
}

// ---------------------------------------------------------------------------
// Deliveries table + pitch map
// ---------------------------------------------------------------------------
async function renderDeliveries(matchId, inningsNumber) {
  const bowler  = $('filterBowler').value;
  const batsman = $('filterBatsman').value;
  const length  = $('filterLength').value;
  const line    = $('filterLine').value;
  const phase   = $('filterPhase').value;

  const params = new URLSearchParams({ innings: inningsNumber });
  if (bowler)  params.set('bowler',  bowler);
  if (batsman) params.set('batsman', batsman);
  if (length)  params.set('length',  length);
  if (line)    params.set('line',    line);
  if (phase)   params.set('phase',   phase);

  let rows;
  try {
    rows = await api(`/api/match/${matchId}/deliveries?${params}`);
  } catch (e) {
    $('deliveryBody').innerHTML = `<tr><td colspan="13" style="color:var(--danger)">Error: ${e.message}</td></tr>`;
    return;
  }

  renderTable(rows);
  renderPitchMap(rows);
}

function renderTable(rows) {
  const tbody = $('deliveryBody');
  tbody.innerHTML = '';
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="13" class="empty-state">No deliveries match the filters.</td></tr>';
    return;
  }

  rows.forEach(r => {
    const tr = document.createElement('tr');

    const totalRuns = (r.runs_off_bat || 0) + (r.extras || 0);
    let runClass = '';
    if (r.wicket_type)      runClass = 'wicket';
    else if (totalRuns === 0) runClass = 'run-0';
    else if (totalRuns >= 6)  runClass = 'run-6';
    else if (totalRuns >= 4)  runClass = 'run-4';

    tr.innerHTML = `
      <td style="font-family:var(--font-mono)">${r.over_ball || `${r.over_number}.${r.ball_number}`}</td>
      <td>${r.bowler || ''}</td>
      <td>${r.batsman || ''}</td>
      <td class="${runClass}">${r.runs_off_bat ?? ''}</td>
      <td class="${r.extras ? 'extra' : ''}">${r.extra_type ? `${r.extras} (${r.extra_type})` : (r.extras || '')}</td>
      <td class="wicket">${r.wicket_type || ''}</td>
      <td>${r.length_label ? `<span class="badge badge-length">${r.length_label}</span>` : ''}</td>
      <td>${r.line_label   ? `<span class="badge badge-line">${r.line_label}</span>` : ''}</td>
      <td>${r.movement_label ? `<span class="badge badge-movement">${r.movement_label}</span>` : ''}</td>
      <td>${r.shot_label   ? `<span class="badge badge-shot">${r.shot_label}</span>` : ''}</td>
      <td>${r.edge_type || r.control_type || ''}</td>
      <td>${r.is_slower_ball ? '&#9679;' : ''}</td>
      <td class="commentary-cell" title="${(r.commentary||'').replace(/"/g,'&quot;')}">${r.commentary || ''}</td>`;
    tbody.appendChild(tr);
  });
}

// ---------------------------------------------------------------------------
// Pitch Map
// ---------------------------------------------------------------------------

// Pitch SVG coordinate space: viewBox="0 0 200 360"
// x axis: line  — outside_leg(40) → outside_off(160)
// y axis: length — bouncer(80)     → yorker(290)

const PITCH_X = {
  outside_leg:  50,
  leg_stump:    72,
  middle_stump: 100,
  off_stump:    128,
  outside_off:  150,
};
const PITCH_Y = {
  bouncer:       85,
  short:        120,
  short_of_good:160,
  good_length:  195,
  full:         230,
  yorker:       265,
  full_toss:    285,
};
const DOT_COLORS = {
  wicket:   '#ef4444',
  six:      '#8b5cf6',
  four:     '#3b82f6',
  runs:     '#f59e0b',
  dot:      '#6b7280',
  extra:    '#d29922',
};

function renderPitchMap(rows) {
  const g = $('pitchDots');
  g.innerHTML = '';

  // Group identical coords and stack
  const groups = {};

  rows.forEach(r => {
    if (r.pitch_x == null && r.pitch_y == null) return;
    // Map [0,1] coords to SVG space
    const svgX = r.pitch_x != null
      ? 40 + r.pitch_x * 120          // 40..160
      : PITCH_X[r.line_type]   || 100;
    const svgY = r.pitch_y != null
      ? 70 + r.pitch_y * 225          // 70..295
      : PITCH_Y[r.length_type] || 195;

    // Jitter by ±4px to avoid perfect stacking
    const jx = svgX + (Math.random() - .5) * 8;
    const jy = svgY + (Math.random() - .5) * 8;

    const totalRuns = (r.runs_off_bat || 0);
    let color;
    if (r.wicket_type)    color = DOT_COLORS.wicket;
    else if (r.extra_type && r.extra_type !== '') color = DOT_COLORS.extra;
    else if (totalRuns >= 6) color = DOT_COLORS.six;
    else if (totalRuns >= 4) color = DOT_COLORS.four;
    else if (totalRuns > 0)  color = DOT_COLORS.runs;
    else                     color = DOT_COLORS.dot;

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', jx.toFixed(1));
    circle.setAttribute('cy', jy.toFixed(1));
    circle.setAttribute('r',  '4');
    circle.setAttribute('fill', color);
    circle.setAttribute('opacity', '0.8');

    const tip = [
      `${r.over_ball}: ${r.bowler || ''} to ${r.batsman || ''}`,
      r.length_label && `Length: ${r.length_label}`,
      r.line_label   && `Line: ${r.line_label}`,
      r.wicket_type  ? `OUT: ${r.wicket_type}` : `Runs: ${totalRuns}`,
    ].filter(Boolean).join('\n');

    circle.addEventListener('mouseenter', () => showTip(tip));
    circle.addEventListener('mouseleave', hideTip);
    g.appendChild(circle);
  });
}

// ---------------------------------------------------------------------------
// Manhattan chart
// ---------------------------------------------------------------------------
async function renderManhattan(matchId, inningsNumber) {
  let overs;
  try {
    overs = await api(`/api/match/${matchId}/overs?innings=${inningsNumber}`);
  } catch (_) { return; }

  const ctx = $('manhattanChart');

  if (manhattanChart) {
    manhattanChart.destroy();
    manhattanChart = null;
  }

  const labels = overs.map(o => `Over ${o.over_number + 1}`);
  const runs   = overs.map(o => o.runs);
  const wkts   = overs.map(o => o.wickets);

  manhattanChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Runs',
        data: runs,
        backgroundColor: overs.map(o =>
          o.wickets > 0 ? 'rgba(248,81,73,.7)' : 'rgba(56,139,253,.7)'
        ),
        borderRadius: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const i   = ctx.dataIndex;
              const wkt = wkts[i];
              return `${ctx.raw} runs${wkt ? `, ${wkt} wicket${wkt > 1 ? 's' : ''}` : ''}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#8b949e', maxRotation: 45, font: { size: 9 } },
          grid:  { color: '#21262d' },
        },
        y: {
          ticks: { color: '#8b949e', font: { size: 10 } },
          grid:  { color: '#21262d' },
          beginAtZero: true,
        },
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Stats cards
// ---------------------------------------------------------------------------
function renderStats(matchId, inningsNumber, allInnings) {
  const inn = allInnings.find(i => i.innings_number === inningsNumber) || {};
  const grid = $('statsGrid');
  const overs = inn.total_overs ? parseFloat(inn.total_overs).toFixed(1) : '—';
  const rr = inn.total_runs && inn.total_overs
    ? (inn.total_runs / inn.total_overs * 6).toFixed(2) : '—';

  grid.innerHTML = `
    <div class="stat-item"><div class="s-val">${inn.total_runs ?? '—'}/${inn.total_wickets ?? '—'}</div><div class="s-lbl">Score</div></div>
    <div class="stat-item"><div class="s-val">${overs}</div><div class="s-lbl">Overs</div></div>
    <div class="stat-item"><div class="s-val">${rr}</div><div class="s-lbl">Run Rate</div></div>
    <div class="stat-item"><div class="s-val">${inn.batting_team || '—'}</div><div class="s-lbl">Batting</div></div>`;
}

// ---------------------------------------------------------------------------
// Filter dropdowns
// ---------------------------------------------------------------------------
async function populateFilterDropdowns(matchId, inningsNumber) {
  try {
    const rows = await api(`/api/match/${matchId}/deliveries?innings=${inningsNumber}`);

    const bowlers  = [...new Set(rows.map(r => r.bowler).filter(Boolean))].sort();
    const batsmen  = [...new Set(rows.map(r => r.batsman).filter(Boolean))].sort();

    const bowlerSel  = $('filterBowler');
    const batsmanSel = $('filterBatsman');

    bowlerSel.innerHTML  = '<option value="">All Bowlers</option>';
    batsmanSel.innerHTML = '<option value="">All Batsmen</option>';

    bowlers.forEach(b  => bowlerSel.insertAdjacentHTML('beforeend',  `<option>${b}</option>`));
    batsmen.forEach(b  => batsmanSel.insertAdjacentHTML('beforeend', `<option>${b}</option>`));
  } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Analytics View
// ---------------------------------------------------------------------------
function renderAnalyticsParams() {
  const type   = $('analyticsType').value;
  const params = $('analyticsParams');
  params.innerHTML = '';

  const input = (id, label, placeholder) => `
    <label class="form-label" for="${id}">${label}</label>
    <input id="${id}" class="form-input" type="text" placeholder="${placeholder}" list="${id}-list"/>
    <datalist id="${id}-list"></datalist>`;

  if (type === 'batsman_vulnerability') {
    params.innerHTML = input('paramBatsman', 'Batsman name', 'e.g. Babar Azam');
    loadPlayerDatalist('paramBatsman', '/api/players');
  } else if (type === 'bowler_profile') {
    params.innerHTML = input('paramBowler', 'Bowler name', 'e.g. James Anderson');
    loadPlayerDatalist('paramBowler', '/api/bowlers');
  } else if (type === 'head_to_head') {
    params.innerHTML =
      input('paramBowler2',  'Bowler name',  'e.g. Jasprit Bumrah') +
      input('paramBatsman2', 'Batsman name', 'e.g. Steve Smith');
    loadPlayerDatalist('paramBowler2',  '/api/bowlers');
    loadPlayerDatalist('paramBatsman2', '/api/players');
  } else if (type === 'phase_analysis') {
    params.innerHTML = `
      <label class="form-label">Filter by team (optional)</label>
      <input id="paramTeam" class="form-input" type="text" placeholder="e.g. India" />`;
  }
}

async function loadPlayerDatalist(inputId, endpoint) {
  try {
    const names = await api(endpoint);
    const dl = document.getElementById(`${inputId}-list`);
    if (!dl) return;
    names.forEach(n => {
      const opt = document.createElement('option');
      opt.value = n;
      dl.appendChild(opt);
    });
  } catch (_) {}
}

async function runAnalytics() {
  const type   = $('analyticsType').value;
  const status = $('analyticsStatus');
  const result = $('analyticsResult');
  status.textContent = 'Running…';
  status.classList.remove('hidden', 'error', 'done');

  const params = new URLSearchParams({ type });

  if (type === 'batsman_vulnerability') {
    const v = ($('paramBatsman') || {}).value || '';
    if (!v) { status.textContent = 'Please enter a batsman name.'; status.classList.add('error'); return; }
    params.set('batsman', v);
  } else if (type === 'bowler_profile') {
    const v = ($('paramBowler') || {}).value || '';
    if (!v) { status.textContent = 'Please enter a bowler name.'; status.classList.add('error'); return; }
    params.set('bowler', v);
  } else if (type === 'head_to_head') {
    const bow = ($('paramBowler2') || {}).value || '';
    const bat = ($('paramBatsman2') || {}).value || '';
    if (!bow || !bat) { status.textContent = 'Both bowler and batsman required.'; status.classList.add('error'); return; }
    params.set('bowler', bow);
    params.set('batsman', bat);
  } else if (type === 'phase_analysis') {
    const team = ($('paramTeam') || {}).value || '';
    if (team) params.set('team', team);
  }

  try {
    const data = await api(`/api/analytics?${params}`);
    status.classList.add('done');
    status.textContent = `${data.rows.length} rows returned.`;
    renderAnalyticsResult(data);
  } catch (e) {
    status.classList.add('error');
    status.textContent = `Error: ${e.message}`;
  }
}

function renderAnalyticsResult(data) {
  const result = $('analyticsResult');
  result.innerHTML = '';

  if (!data.rows || !data.rows.length) {
    result.innerHTML = '<div class="empty-state">No results. Make sure you have matches scraped for this player.</div>';
    return;
  }

  if (data.type === 'batsman_vulnerability') {
    renderVulnerabilityResult(data);
  } else if (data.type === 'bowler_profile') {
    renderBowlerProfileResult(data);
  } else if (data.type === 'head_to_head') {
    renderHeadToHeadResult(data);
  } else if (data.type === 'phase_analysis') {
    renderPhaseResult(data);
  }
}

function renderVulnerabilityResult(data) {
  const result = $('analyticsResult');

  const card = el('div', 'card');
  card.innerHTML = `<div class="card-title">Batsman Vulnerability — ${data.batsman}</div>`;

  const sub = el('p', null, 'Delivery types ranked by wickets taken and dot ball percentage. Higher = more effective against this batsman.');
  sub.style.cssText = 'font-size:12px;color:var(--text-dim);margin-bottom:12px;';
  card.appendChild(sub);

  const wrap = el('div');
  wrap.style.overflowX = 'auto';
  const maxWkts = Math.max(...data.rows.map(r => r.wickets), 1);

  wrap.innerHTML = `
    <table class="analytics-table">
      <thead>
        <tr>
          <th>Length</th><th>Line</th>
          <th class="num">Balls</th>
          <th class="num">Runs</th>
          <th class="num">Wkts</th>
          <th class="num">Run/Ball</th>
          <th class="num">Dot %</th>
          <th class="num">Bdry %</th>
        </tr>
      </thead>
      <tbody>
        ${data.rows.map(r => {
          const heatLevel = Math.round((r.wickets / maxWkts) * 4);
          return `<tr class="heat-${heatLevel}">
            <td>${label(r.length_type)}</td>
            <td>${label(r.line_type)}</td>
            <td class="num">${r.balls}</td>
            <td class="num">${r.runs}</td>
            <td class="num" style="font-weight:700;color:var(--danger)">${r.wickets}</td>
            <td class="num">${r.run_rate}</td>
            <td class="num">${r.dot_pct}%</td>
            <td class="num">${r.boundary_pct}%</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
  card.appendChild(wrap);

  // Pitch heatmap visualisation
  const pitchCard = el('div', 'card');
  pitchCard.innerHTML = `<div class="card-title">Wicket Heatmap</div>
    <div style="text-align:center">
      <svg viewBox="0 0 200 360" style="max-width:220px;width:100%;border-radius:6px">
        <rect x="40" y="10" width="120" height="340" rx="4" fill="#3a7d1e"/>
        <rect x="60" y="10" width="80"  height="340" fill="#4a9a28"/>
        <line x1="40" y1="60"  x2="160" y2="60"  stroke="#fff" stroke-width="1.5" opacity=".6"/>
        <line x1="40" y1="300" x2="160" y2="300" stroke="#fff" stroke-width="1.5" opacity=".6"/>
        ${data.rows.map(r => {
          const lx = { outside_leg:50, leg_stump:72, middle_stump:100, off_stump:128, outside_off:150 };
          const ly = { bouncer:85, short:120, short_of_good:160, good_length:195, full:230, yorker:265, full_toss:285 };
          const x = lx[r.line_type] || 100;
          const y = ly[r.length_type] || 195;
          const r_ = Math.max(4, r.wickets * 5);
          const alpha = 0.3 + (r.wickets / maxWkts) * 0.7;
          return `<circle cx="${x}" cy="${y}" r="${r_}" fill="rgba(239,68,68,${alpha.toFixed(2)})">
            <title>${label(r.length_type)} / ${label(r.line_type)}: ${r.wickets} wkts from ${r.balls} balls</title>
          </circle>`;
        }).join('')}
      </svg>
      <p style="font-size:11px;color:var(--text-dim);margin-top:6px">Circle size = wickets taken</p>
    </div>`;

  result.appendChild(card);
  result.appendChild(pitchCard);
}

function renderBowlerProfileResult(data) {
  const result = $('analyticsResult');
  const card = el('div', 'card');
  card.innerHTML = `<div class="card-title">Bowler Profile — ${data.bowler}</div>`;

  const wrap = el('div');
  wrap.style.overflowX = 'auto';
  wrap.innerHTML = `
    <table class="analytics-table">
      <thead>
        <tr>
          <th>Length</th><th>Line</th><th>Movement</th>
          <th class="num">Balls</th>
          <th class="num">Runs</th>
          <th class="num">Wkts</th>
          <th class="num">Economy</th>
          <th class="num">Dot %</th>
        </tr>
      </thead>
      <tbody>
        ${data.rows.map(r => `<tr>
          <td>${label(r.length_type)}</td>
          <td>${label(r.line_type)}</td>
          <td>${label(r.movement_type)}</td>
          <td class="num">${r.balls}</td>
          <td class="num">${r.runs}</td>
          <td class="num" style="color:var(--danger)">${r.wickets}</td>
          <td class="num">${r.economy}</td>
          <td class="num">${r.dot_pct}%</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
  card.appendChild(wrap);
  result.appendChild(card);
}

function renderHeadToHeadResult(data) {
  const result = $('analyticsResult');

  // Summary stats card
  const total  = data.rows.length;
  const runs   = data.rows.reduce((s, r) => s + (r.runs_off_bat || 0), 0);
  const wickets = data.rows.filter(r => r.wicket_type).length;
  const dots   = data.rows.filter(r => (r.runs_off_bat || 0) === 0 && !r.wicket_type).length;

  const sumCard = el('div', 'card');
  sumCard.innerHTML = `
    <div class="card-title">Head to Head — ${data.bowler} vs ${data.batsman}</div>
    <div class="stats-grid" style="grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px">
      <div class="stat-item"><div class="s-val">${total}</div><div class="s-lbl">Balls</div></div>
      <div class="stat-item"><div class="s-val">${runs}</div><div class="s-lbl">Runs</div></div>
      <div class="stat-item"><div class="s-val" style="color:var(--danger)">${wickets}</div><div class="s-lbl">Wickets</div></div>
      <div class="stat-item"><div class="s-val">${total ? ((dots/total)*100).toFixed(0) : 0}%</div><div class="s-lbl">Dot %</div></div>
    </div>`;

  // Delivery table
  const wrap = el('div');
  wrap.style.overflowX = 'auto';
  wrap.innerHTML = `
    <table class="analytics-table">
      <thead>
        <tr>
          <th>Match</th><th>Over</th>
          <th class="num">Runs</th>
          <th>Wicket</th>
          <th>Length</th><th>Line</th><th>Shot</th>
          <th>Commentary</th>
        </tr>
      </thead>
      <tbody>
        ${data.rows.map(r => `<tr>
          <td style="font-size:11px;color:var(--text-dim)">${r.title || ''}<br>${r.match_date || ''}</td>
          <td style="font-family:var(--font-mono)">${r.over_ball || `${r.over_number}.${r.ball_number}`}</td>
          <td class="num ${r.runs_off_bat >= 4 ? 'run-4' : ''}">${r.runs_off_bat ?? ''}</td>
          <td class="wicket">${r.wicket_type || ''}</td>
          <td>${label(r.length_type)}</td>
          <td>${label(r.line_type)}</td>
          <td>${label(r.shot_type)}</td>
          <td style="font-size:11px;color:var(--text-dim);max-width:250px">${r.commentary || ''}</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
  sumCard.appendChild(wrap);
  result.appendChild(sumCard);
}

function renderPhaseResult(data) {
  const result = $('analyticsResult');
  const card = el('div', 'card');
  card.innerHTML = `<div class="card-title">Phase Analysis</div>`;

  const wrap = el('div');
  wrap.style.overflowX = 'auto';
  wrap.innerHTML = `
    <table class="analytics-table">
      <thead>
        <tr>
          <th>Phase</th>
          <th class="num">Balls</th>
          <th class="num">Runs</th>
          <th class="num">Wickets</th>
          <th class="num">Run Rate</th>
          <th class="num">Boundary %</th>
          <th class="num">Dot %</th>
        </tr>
      </thead>
      <tbody>
        ${data.rows.map(r => `<tr>
          <td style="font-weight:600">${r.phase}</td>
          <td class="num">${r.balls}</td>
          <td class="num">${r.runs}</td>
          <td class="num" style="color:var(--danger)">${r.wickets}</td>
          <td class="num">${r.run_rate}</td>
          <td class="num">${r.boundary_pct}%</td>
          <td class="num">${r.dot_pct}%</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
  card.appendChild(wrap);
  result.appendChild(card);
}

// ---------------------------------------------------------------------------
// Label helper (mirrors Python parser)
// ---------------------------------------------------------------------------
const LABELS = {
  full_toss:'Full toss', yorker:'Yorker', bouncer:'Bouncer', short:'Short',
  short_of_good:'Short of good length', good_length:'Good length', full:'Full',
  outside_off:'Outside off', off_stump:'Off stump', middle_stump:'Middle stump',
  leg_stump:'Leg stump', outside_leg:'Outside leg',
  inswing:'Inswing', outswing:'Outswing', off_cutter:'Off cutter',
  leg_cutter:'Leg cutter', seam:'Seam', googly:'Googly', doosra:'Doosra',
  flipper:'Flipper', slider:'Slider', arm_ball:'Arm ball', carrom:'Carrom ball',
  top_spinner:'Top spinner', off_break:'Off break', leg_break:'Leg break',
  drive:'Drive', cut:'Cut', pull:'Pull', hook:'Hook', sweep:'Sweep',
  reverse_sweep:'Reverse sweep', glance:'Glance', flick:'Flick', nudge:'Nudge',
  punch:'Punch', dab:'Dab', scoop:'Scoop', ramp:'Ramp', paddle:'Paddle',
  slog:'Slog', loft:'Loft', block:'Block/Defend', leave:'Leave',
  beaten:'Beaten', mistimed:'Mistimed', edged:'Edged',
  inside_edge:'Inside edge', outside_edge:'Outside edge',
  top_edge:'Top edge', bottom_edge:'Bottom edge',
};
const label = k => (k && (LABELS[k] || k.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase()))) || '';

// ---------------------------------------------------------------------------
// Wire up events
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  createTooltip();

  // Nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.view;
      showView(view);
      if (view === 'library') loadLibrary();
      if (view === 'analytics') renderAnalyticsParams();
    });
  });

  // Add match button
  $('addMatchBtn').addEventListener('click', async () => {
    const url = $('urlInput').value.trim();
    if (!url) return;
    try {
      $('addMatchBtn').disabled = true;
      const { job_id } = await post('/api/add-match', { url });
      startJobPoll(job_id, () => {
        loadLibrary();
        $('addMatchBtn').disabled = false;
      });
    } catch (e) {
      const s = $('jobStatus');
      s.classList.remove('hidden');
      s.classList.add('error');
      s.textContent = `Error: ${e.message}`;
      $('addMatchBtn').disabled = false;
    }
  });

  // Add series button
  $('addSeriesBtn').addEventListener('click', async () => {
    const url = $('urlInput').value.trim();
    if (!url) return;
    try {
      $('addSeriesBtn').disabled = true;
      const { job_id } = await post('/api/add-series', { url });
      startJobPoll(job_id, () => {
        loadLibrary();
        $('addSeriesBtn').disabled = false;
      });
    } catch (e) {
      const s = $('jobStatus');
      s.classList.remove('hidden');
      s.classList.add('error');
      s.textContent = `Error: ${e.message}`;
      $('addSeriesBtn').disabled = false;
    }
  });

  // Filter bar
  ['filterBowler','filterBatsman','filterLength','filterLine','filterPhase'].forEach(id => {
    $(id).addEventListener('change', () => {
      if (currentMatchId) renderDeliveries(currentMatchId, currentInnings);
    });
  });
  $('clearFilters').addEventListener('click', () => {
    ['filterBowler','filterBatsman','filterLength','filterLine','filterPhase'].forEach(id => $(id).value = '');
    if (currentMatchId) renderDeliveries(currentMatchId, currentInnings);
  });

  // Analytics
  $('analyticsType').addEventListener('change', renderAnalyticsParams);
  $('runAnalyticsBtn').addEventListener('click', runAnalytics);

  // Initial state
  showView('library');
  loadLibrary();
  renderAnalyticsParams();
});
