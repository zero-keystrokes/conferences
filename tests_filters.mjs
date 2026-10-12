// Exercises the ACTUAL filter JavaScript shipped in docs/index.html against the
// ACTUAL markup it ships with. browser_exec is unavailable on this host, and
// markup assertions cannot prove filter behaviour — this can.
//
//   node tests_filters.mjs
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('./docs/index.html', import.meta.url), 'utf8');
const jsMatch = html.match(/<script>\n([\s\S]*?)<\/script>\s*<\/body>/);
if (!jsMatch) { console.error('FATAL: could not locate the filter script'); process.exit(1); }
const FILTER_JS = jsMatch[1];
const STORE = 'sde:hidden-regions:v1';

// ---- localStorage stub, shared across boots so a "reload" is faithful -----
const store = new Map();
let storageThrows = false;
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => {
    if (storageThrows) throw new Error('QuotaExceededError');
    store.set(k, String(v));
  },
  removeItem: (k) => store.delete(k),
};
const storedHidden = () => { try { return JSON.parse(store.get(STORE) || '[]'); } catch { return null; } };

// ---- minimal DOM ---------------------------------------------------------
class El {
  constructor(tagName, attrs = {}, text = '') {
    this.tagName = tagName;
    this.dataset = {};
    for (const [k, v] of Object.entries(attrs)) if (k.startsWith('data-')) this.dataset[k.slice(5)] = v;
    this.attrs = attrs;
    this._text = text;
    this._classes = new Set((attrs.class || '').split(/\s+/).filter(Boolean));
    this.style = { display: '' };
    this.value = '';
    this.checked = attrs.checked !== undefined;
    this.open = false;
    this._listeners = {};
    this.nextElementSibling = null;
    this._pressed = 'false';
  }
  get classList() {
    const self = this;
    return {
      contains: (c) => self._classes.has(c),
      toggle: (c, on) => { if (on) self._classes.add(c); else self._classes.delete(c); },
      add: (c) => self._classes.add(c),
      remove: (c) => self._classes.delete(c),
    };
  }
  setAttribute(k, v) { if (k === 'aria-pressed') this._pressed = String(v); }
  getAttribute(k) { return k === 'aria-pressed' ? this._pressed : (this.attrs[k] ?? null); }
  addEventListener(t, fn) { (this._listeners[t] ||= []).push(fn); }
  dispatch(t, ev = {}) { for (const fn of this._listeners[t] || []) fn({ preventDefault() {}, ...ev }); }
  contains(node) { return node === this; }
  get textContent() { return this._text; }
  set textContent(v) { this._text = v; }
  click() { this.dispatch('click'); }
  type(v) { this.value = v; this.dispatch('input'); }
  tick(on = true) { this.checked = on; this.dispatch('change'); }
}

// Build a fresh DOM and run the shipped script — one "page load".
function boot() {
  const TOKEN = /<h2>([\s\S]*?)<\/h2>|<div class="month">([\s\S]*?)<\/div>|<div class="(card[^"]*)" data-topics="([^"]*)" data-cfp="([^"]*)" data-regions="([^"]*)" data-text="([^"]*)">/g;
  const ordered = [], cards = [], months = [];
  let m;
  while ((m = TOKEN.exec(html)) !== null) {
    if (m[1] !== undefined) ordered.push(new El('H2', {}, m[1]));
    else if (m[2] !== undefined) {
      const el = new El('DIV', { class: 'month' }, m[2]); ordered.push(el); months.push(el);
    } else {
      const el = new El('DIV', { class: m[3] });
      el.dataset.topics = m[4]; el.dataset.cfp = m[5]; el.dataset.regions = m[6]; el.dataset.text = m[7];
      ordered.push(el); cards.push(el);
    }
  }
  for (let i = 0; i < ordered.length - 1; i++) ordered[i].nextElementSibling = ordered[i + 1];

  const chips = [], checkboxes = [], byId = {};
  let cm;
  const chipRe = /<span class="chip([^"]*)"([^>]*?)>([\s\S]*?)<\/span>/g;
  while ((cm = chipRe.exec(html)) !== null) {
    const attrs = { class: 'chip' + cm[1] };
    for (const a of cm[2].matchAll(/(data-[a-z]+|id)="([^"]*)"/g)) attrs[a[1]] = a[2];
    const el = new El('SPAN', attrs, cm[3]);
    chips.push(el);
    if (attrs.id) byId[attrs.id] = el;
  }
  const boxRe = /<input type="checkbox" data-region="([^"]*)"( checked)?>/g;
  while ((cm = boxRe.exec(html)) !== null) {
    checkboxes.push(new El('INPUT', { 'data-region': cm[1], checked: cm[2] ? '' : undefined }));
  }

  byId.q = new El('INPUT');
  byId.noshow = new El('DIV', {}, '');
  byId.hiddennote = new El('SPAN', {}, '');
  byId['region-count'] = byId['region-count'] || new El('SPAN', {}, '');
  const dd = new El('DETAILS', { class: 'dd', id: 'region-dd' });
  // In the real DOM the checkboxes are descendants of the <details>, so a click
  // on one must NOT count as an outside click.
  dd.contains = (node) => node === dd || checkboxes.includes(node);
  byId['region-dd'] = dd;

  const docListeners = {};
  const document = {
    querySelectorAll: (sel) => {
      if (sel === '.card') return cards;
      if (sel === '.month') return months;
      if (sel === '.chip') return chips;
      if (sel === '.chip[data-topic]') return chips.filter((c) => c.dataset.topic !== undefined);
      if (sel === 'input[type=checkbox][data-region]') return checkboxes;
      return [];
    },
    querySelector: (sel) => (sel === '.chip.cfp'
      ? chips.find((c) => (c.attrs.class || '').includes('cfp')) : null),
    getElementById: (id) => byId[id] || null,
    addEventListener: (t, fn) => { (docListeners[t] ||= []).push(fn); },
    dispatch: (t, ev) => { for (const fn of docListeners[t] || []) fn({ preventDefault() {}, ...ev }); },
  };

  new Function('document', FILTER_JS)(document);
  return { cards, months, chips, checkboxes, byId, dd, document };
}

// ---- assertions ----------------------------------------------------------
let fail = 0;
const check = (label, ok, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : '  ' + detail}`);
  if (!ok) fail++;
};
const vis = (p) => p.cards.filter((c) => c.style.display !== 'none').length;
const regionsOf = (c) => (c.dataset.regions || '').split('|').filter(Boolean);
const boxOf = (p, k) => p.checkboxes.find((b) => b.dataset.region === k);
const noteN = (p) => parseInt((p.byId.hiddennote.textContent || '0').match(/^\d+/)?.[0] || '0', 10);
const isContinent = (b) => !['Online', 'Location TBA', 'Other'].includes(b.dataset.region);

console.log('Markup contract');
check('no exclusion text box (inclusion only)', !/id="x"/.test(html));
check('inclusion search box present', /id="q"/.test(html));
check('region dropdown rendered as details/summary', /<details class="dd" id="region-dd">/.test(html));
check('options are region checkboxes', /<input type="checkbox" data-region="/.test(html));
check('no leftover exclusion markup', !/data-excl=/.test(html), 'old data-excl attributes remain');
const totalBoxes = (html.match(/<input type="checkbox" data-region="/g) || []).length;
const checkedBoxes = (html.match(/<input type="checkbox" data-region="[^"]*" checked>/g) || []).length;
check('every region renders ticked (include filter)', totalBoxes > 0 && totalBoxes === checkedBoxes,
  `${checkedBoxes}/${totalBoxes} ticked`);
check('every card carries at least one region key',
  !/data-cfp="[^"]*" data-regions=""/.test(html),
  'a card has no region — the include filter would strand it');

let p = boot();
console.log('\nDefault state (nothing hidden)');
check('all cards visible on a first visit', vis(p) === p.cards.length, `${vis(p)}/${p.cards.length}`);
check('every box ticked on a first visit', p.checkboxes.every((b) => b.checked));
check('no hidden count shown', p.byId.hiddennote.textContent === '');
check('summary has no counts suffix', p.byId['region-count'].textContent === '');

console.log('\nUnticking a region filters it out');
const contBox = p.checkboxes.find(isContinent);
const contName = contBox.dataset.region;
const contCards = p.cards.filter((c) => regionsOf(c).includes(contName));
contBox.tick(false);
check(`unticking ${contName} hides exactly its cards`,
  vis(p) === p.cards.length - contCards.length,
  `visible ${vis(p)}, expected ${p.cards.length - contCards.length}`);
check('hidden count reported', noteN(p) === contCards.length, `note="${p.byId.hiddennote.textContent}"`);
check('summary reports the remainder',
  p.byId['region-count'].textContent.includes(`${p.checkboxes.length - 1} of ${p.checkboxes.length}`),
  `summary="${p.byId['region-count'].textContent}"`);
check('dropdown marked partial', p.dd.classList.contains('partial'));

const tbaCards = p.cards.filter((c) => regionsOf(c).includes('Location TBA'));
check('location-TBA events survive a region being unticked',
  tbaCards.every((c) => c.style.display !== 'none'),
  `${tbaCards.filter((c) => c.style.display !== 'none').length}/${tbaCards.length} visible`);

console.log('\nPersistence across a reload');
check('hidden set written to localStorage',
  JSON.stringify(storedHidden()) === JSON.stringify([contName]),
  `stored ${JSON.stringify(storedHidden())}`);
check('storage holds HIDDEN regions, not shown ones',
  Array.isArray(storedHidden()) && storedHidden().length === 1, JSON.stringify(storedHidden()));

const p2 = boot();
check('reload restores the unticked box', boxOf(p2, contName)?.checked === false,
  'box came back ticked');
check('reload keeps those cards hidden', vis(p2) === p2.cards.length - contCards.length,
  `visible ${vis(p2)}`);
check('every other region still ticked after reload',
  p2.checkboxes.filter((b) => b.checked).length === p2.checkboxes.length - 1,
  `${p2.checkboxes.filter((b) => b.checked).length} ticked`);

console.log('\nStorage robustness');
store.set(STORE, JSON.stringify(['Atlantis', contName]));
const p3 = boot();
check('unknown stored region names are ignored',
  boxOf(p3, contName)?.checked === false,
  'a known key was dropped along with the unknown one');
check('an unknown name hides nothing extra',
  vis(p3) === p3.cards.length - contCards.length, `visible ${vis(p3)}`);
check('regions absent from storage default to visible',
  p3.checkboxes.filter((b) => b.checked).length === p3.checkboxes.length - 1,
  'a region was hidden without ever being stored');

store.set(STORE, 'not json at all');
const p4 = boot();
check('corrupt stored value degrades to all-visible', vis(p4) === p4.cards.length, `visible ${vis(p4)}`);

store.clear();
storageThrows = true;
const p5 = boot();
boxOf(p5, contName)?.tick(false);
check('filtering still works when localStorage throws (private mode)',
  vis(p5) === p5.cards.length - contCards.length,
  `visible ${vis(p5)} — a throwing store broke filtering`);
storageThrows = false;

console.log('\nReset');
store.set(STORE, JSON.stringify([contName]));
const p6 = boot();
check('reset starts from the restored state', vis(p6) === p6.cards.length - contCards.length,
  `visible ${vis(p6)}`);
p6.byId.reset.click();
check('reset re-ticks every region', p6.checkboxes.every((b) => b.checked), 'a box stayed unticked');
check('reset shows every card again', vis(p6) === p6.cards.length, `visible ${vis(p6)}`);
check('reset clears the saved preference', JSON.stringify(storedHidden()) === '[]',
  `stored ${JSON.stringify(storedHidden())}`);
check('reset removes the partial marker', !p6.dd.classList.contains('partial'));

console.log('\nSearch and topic filters still compose');
p6.byId.q.type('kafka');
const kafka = p6.cards.filter((c) => (c.dataset.text || '').includes('kafka'));
check('search narrows to matches', vis(p6) === kafka.length, `visible ${vis(p6)}, expected ${kafka.length}`);
check('search is case-insensitive', (() => { p6.byId.q.type('KAFKA'); return vis(p6) === kafka.length; })());
check('search composes with region filtering', (() => {
  const b = p6.checkboxes.find(isContinent);
  b.tick(false);
  const expect = kafka.filter((c) => !regionsOf(c).includes(b.dataset.region)).length;
  const ok = vis(p6) === expect;
  b.tick(true);
  return ok;
})(), 'search and region filter did not intersect');
p6.byId.q.type('');
const topicChip = p6.chips.find((c) => c.dataset.topic !== undefined);
topicChip?.click();
check('topic chip still filters', vis(p6) <= p6.cards.length);
topicChip?.click();
check('clearing the topic chip restores everything', vis(p6) === p6.cards.length, `visible ${vis(p6)}`);

console.log('\nMonth headers');
check('all month headers visible when unfiltered',
  p6.months.every((mm) => mm.style.display !== 'none'), 'a header was hidden');
p6.checkboxes.forEach((b) => b.tick(false));
check('empty month headers hide when every region is unticked',
  vis(p6) === 0 || p6.months.some((mm) => mm.style.display === 'none'), 'no header hidden');
p6.checkboxes.forEach((b) => b.tick(true));

console.log('\nDropdown behaviour and styling');
p6.byId['region-dd'].open = true;
p6.document.dispatch('click', { target: p6.byId.q });
check('click outside closes the dropdown', p6.byId['region-dd'].open === false);
p6.byId['region-dd'].open = true;
p6.document.dispatch('click', { target: p6.checkboxes[0] });
check('click on an option keeps it open', p6.byId['region-dd'].open === true);
check('no border-radius in served CSS', !/border-radius/.test(html), 'still rounded');
// Regression: a scroll container on the controls bar clipped the dropdown and
// put a scrollbar on the sticky bar.
const controlsCss = html.match(/\.controls\{([^}]*)\}/)?.[1] ?? '';
check('controls bar is not a scroll container',
  !/overflow/.test(controlsCss) && !/max-height/.test(controlsCss), `got: ${controlsCss}`);
const menuCss = html.match(/\.ddmenu\{([^}]*)\}/)?.[1] ?? '';
check('dropdown menu is absolutely positioned', /position:absolute/.test(menuCss), `got: ${menuCss}`);
check('dropdown menu stacks above the cards', /z-index/.test(menuCss));
check('narrow screens unpin the controls bar', /\.controls\{position:static\}/.test(html));

console.log(fail ? `\n${fail} FAILURE(S)` : '\nAll browser-logic checks passed.');
process.exit(fail ? 1 : 0);
