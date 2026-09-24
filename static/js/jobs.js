(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const post = (url) => fetch(url, { method: 'POST', headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' });

  const LABELS = { adzuna: 'Adzuna' };            // add a label here when you add a provider
  const MODES = { remote: 'Remote', hybrid: 'Hybrid', onsite: 'On-site' };

  function ago(iso) {
    if (!iso) return 'Date not listed';
    const d = Math.floor((Date.now() - new Date(iso)) / 86400000);
    return d <= 0 ? 'Today' : d === 1 ? '1 day ago' : d < 30 ? d + ' days ago' : Math.floor(d / 30) + ' mo ago';
  }
  const exp = j => j.exp_min == null ? 'Not specified' : (j.exp_max ? `${j.exp_min}–${j.exp_max} years` : `${j.exp_min}+ years`);
  function salary(j) {
    if (!j.salary_min && !j.salary_max) return null;
    const f = n => n >= 100000 ? (n / 100000).toFixed(1).replace('.0', '') + ' LPA' : n.toLocaleString('en-IN');
    return '₹ ' + (j.salary_min && j.salary_max ? `${f(j.salary_min)} – ${f(j.salary_max)}` : f(j.salary_min || j.salary_max));
  }

  function card(j, opts = {}) {
    const c = el('article', 'job-card');
    c.appendChild(el('h3', '', j.title));
    c.appendChild(el('div', 'job-company', j.company));
    c.appendChild(el('div', 'job-meta', [j.location, MODES[j.work_mode]].filter(Boolean).join(' | ') || 'Location not listed'));
    c.appendChild(el('div', 'job-meta', 'Experience: ' + exp(j)));
    const sal = salary(j); if (sal) c.appendChild(el('div', 'job-meta', 'Salary: ' + sal));

    const matched = new Set((j.match && j.match.matched) || []);
    if ((j.skills || []).length) {
      const sk = el('div', 'job-skills');
      j.skills.forEach(s => sk.appendChild(el('span', 'chip' + (matched.has(s) ? ' matched' : ''), s)));
      c.appendChild(sk);
    }
    if (j.description && !opts.compact) c.appendChild(el('p', 'job-meta', j.description + '…'));

    if (j.match) {
      const m = el('div', 'match-detail');
      m.appendChild(el('span', 'match-pill', `Match: ${j.match.score}%`));
      m.appendChild(el('div', '', j.match.reasons.join('. ') + '.'));
      if (j.match.missing.length) m.appendChild(el('div', '', 'Not in your profile: ' + j.match.missing.join(', ')));
      c.appendChild(m);
    }

    const foot = el('div', 'job-foot');
    const srcs = j.sources || j.job_postings || [];
    srcs.forEach(s => foot.appendChild(el('span', 'source-badge', 'Source: ' + (LABELS[s.source] || s.source))));
    foot.appendChild(el('span', 'job-meta', 'Posted: ' + ago(j.posted_at)));
    foot.appendChild(el('span', 'grow'));

    if (srcs[0]) {
      const a = el('a', 'job-btn primary', 'View Original Job');
      a.href = `/jobs/go/${j.id}/${srcs[0].id}`; a.target = '_blank'; a.rel = 'noopener noreferrer';
      foot.appendChild(a);
    }
    const toggle = (label, onLabel, url, key) => {
      const b = el('button', 'job-btn' + (j[key] ? ' on' : ''), j[key] ? onLabel : label);
      b.type = 'button';
      b.onclick = async () => {
        const r = await post(url);
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { alert(d.message || 'Could not update. Please try again.'); return; }
        j[key] = d[key];
        b.className = 'job-btn' + (j[key] ? ' on' : ''); b.textContent = j[key] ? onLabel : label;
      };
      return b;
    };
    foot.appendChild(toggle('Save Job', '★ Saved', `/api/jobs/${j.id}/save`, 'saved'));
    foot.appendChild(toggle('Mark Applied', '✓ Applied', `/api/jobs/${j.id}/applied`, 'applied'));
    c.appendChild(foot);
    return c;
  }

  // "Search the same thing on other platforms": plain outbound links, nothing is scraped
  function elsewhere(q, loc) {
    const box = $('#elsewhere'); if (!box) return;
    box.replaceChildren();
    if (!q) return;
    const slug = s => s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const e = encodeURIComponent;
    const links = [
      ['LinkedIn', `https://www.linkedin.com/jobs/search/?keywords=${e(q)}&location=${e(loc)}`],
      ['Naukri', `https://www.naukri.com/${slug(q)}-jobs${loc ? '-in-' + slug(loc) : ''}`],
      ['Indeed', `https://in.indeed.com/jobs?q=${e(q)}&l=${e(loc)}`],
      ['Internshala', `https://internshala.com/internships/keywords-${e(q)}`],
    ];
    box.appendChild(document.createTextNode('Also search on:'));
    links.forEach(([n, u]) => { const a = el('a', '', n); a.href = u; a.target = '_blank'; a.rel = 'noopener noreferrer'; box.appendChild(a); });
  }

  // ───── Search page ─────
  const form = $('#job-form');
  if (form) {
    let page = 1;
    const list = $('#job-list'), count = $('#job-count'), more = $('#load-more');

    const params = () => {
      const p = new URLSearchParams();
      const q = form.q.value.trim(), loc = form.location.value.trim();
      if (q) p.set('q', q); if (loc) p.set('location', loc);
      document.querySelectorAll('.jobs-filters [name]').forEach(i => {
        if ((i.type === 'checkbox' && i.checked) || (i.type !== 'checkbox' && i.value)) p.append(i.name, i.value);
      });
      return p;
    };

    async function load(reset) {
      if (reset) { page = 1; list.replaceChildren(); }
      count.textContent = 'Searching…';
      elsewhere(form.q.value.trim(), form.location.value.trim());
      const p = params(); p.set('page', page);
      history.replaceState(null, '', '?' + params().toString());
      try {
        const r = await fetch('/api/jobs?' + p.toString(), { credentials: 'same-origin' });
        if (r.status === 401) { location.href = '/login'; return; }
        if (!r.ok) throw new Error();
        const d = await r.json();
        d.items.forEach(j => list.appendChild(card(j)));
        count.textContent = d.total ? `${d.total} jobs found` : '';
        if (!d.total) list.replaceChildren(el('p', '', 'No jobs match yet. Try broader keywords or remove a filter.'));
        more.hidden = page * d.per_page >= d.total;
      } catch (e) { count.textContent = 'Could not load jobs. Please try again.'; }
    }

    // pre-fill from the URL so the homepage search bar lands here with results
    const u = new URLSearchParams(location.search);
    form.q.value = u.get('q') || ''; form.location.value = u.get('location') || '';
    document.querySelectorAll('.jobs-filters [name]').forEach(i => {
      const vals = u.getAll(i.name);
      if (i.type === 'checkbox') i.checked = vals.includes(i.value); else if (vals[0]) i.value = vals[0];
    });

    form.addEventListener('submit', e => { e.preventDefault(); load(true); });
    document.querySelectorAll('.jobs-filters [name]').forEach(i => i.addEventListener('change', () => load(true)));
    more.addEventListener('click', () => { page++; load(false); });
    load(true);
  }

  // ───── Dashboard ─────
  if (window.JOBS_DASHBOARD) {
    const list = $('#dash-list'); let data = null, tab = 'saved';
    const render = () => {
      list.replaceChildren();
      const rows = data[tab] || [];
      if (!rows.length) list.appendChild(el('p', 'job-meta', 'Nothing here yet.'));
      rows.forEach(j => { j.saved = tab === 'saved'; j.applied = tab === 'applied'; list.appendChild(card(j, { compact: true })); });
    };
    fetch('/api/jobs/dashboard', { credentials: 'same-origin' }).then(r => r.json()).then(d => {
      data = d; $('#n-saved').textContent = `(${d.saved.length})`; $('#n-applied').textContent = `(${d.applied.length})`; render();
    });
    document.querySelectorAll('.dash-tab').forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('.dash-tab').forEach(x => x.classList.remove('active'));
      b.classList.add('active'); tab = b.dataset.tab; render();
    }));
  }
})();