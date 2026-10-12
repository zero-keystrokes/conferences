// Exercises the ACTUAL filter JavaScript shipped in docs/index.html against the
// ACTUAL markup it ships with. browser_exec is unavailable on this host, and
// markup assertions cannot prove the exclude logic works — this can.
//
//   node tests_filters.mjs
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('./docs/index.html', import.meta.url), 'utf8');

// ---- pull the real filter script out of the page -------------------------
const jsMatch = html.match(/<script>\n([\s\S]*?)<\/script>\s*<\/body>/);
if (!jsMatch) { console.error('FATAL: could not locate the filter script'); process.exit(1); }
const FILTER_JS = jsMatch[1];

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
    this.checked = false;
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

// Parse h2 / month / card in document order so nextElementSibling is faithful.
const TOKEN = /<h2>([\s\S]*?)<\/h2>|<div class="month">([\s\S]*?)<\/div>|<div class="(card[^"]*)" data-topics="([^"]*)" data-cfp="([^"]*)" data-excl="([^"]*)" data-text="([^"]*)">/g;
const ordered = [];
const cards = [], months = [];
let m;
while ((m = TOKEN.exec(html)) !== null) {
  if (m[1] !== undefined) {
    ordered.push(new El('H2', {}, m[1]));
  } else if (m[2] !== undefined) {
    const el = new El('DIV', { class: 'month' }, m[2]); ordered.push(el); months.push(el);
  } else {
    const el = new El('DIV', { class: m[3] });
    el.dataset.topics = m[4]; el.dataset.cfp = m[5]; el.dataset.excl = m[6]; el.dataset.text = m[7];
    ordered.push(el); cards.push(el);
  }
}
for (let i = 0; i < ordered.length - 1; i++) ordered[i].nextElementSibling = ordered[i + 1];

const chips = [], checkboxes = [], byId = {};
const chipRe = /<span class="chip([^"]*)"([^>]*?)>([\s\S]*?)<\/span>/g;
let cm;
while ((cm = chipRe.exec(html)) !== null) {
  const attrs = { class: 'chip' + cm[1] };
  for (const a of cm[2].matchAll(/(data-[a-z]+|id)="([^"]*)"/g)) attrs[a[1]] = a[2];
  const el = new El('SPAN', attrs, cm[3]);
  chips.push(el);
  if (attrs.id) byId[attrs.id] = el;
}
const boxRe = /<input type="checkbox" data-excl="([^"]*)">/g;
while ((cm = boxRe.exec(html)) !== null) checkboxes.push(new El('INPUT', { 'data-excl': cm[1] }));

byId.q = new El('INPUT');
byId.noshow = new El('DIV', {}, '');
byId.hiddennote = new El('SPAN', {}, '');
byId['excl-count'] = byId['excl-count'] || new El('SPAN', {}, '');
const dd = new El('DETAILS', { class: 'dd', id: 'excl-dd' });
dd.open = false;
// In the real DOM the checkboxes are descendants of the <details>, so a click
// on one must NOT count as an outside click.
dd.contains = (node) => node === dd || checkboxes.includes(node);
byId['excl-dd'] = dd;

const docListeners = {};
const document = {
  querySelectorAll: (sel) => {
    if (sel === '.card') return cards;
    if (sel === '.month') return months;
    if (sel === '.chip') return chips;
    if (sel === '.chip[data-topic]') return chips.filter((c) => c.dataset.topic !== undefined);
    if (sel === 'input[type=checkbox][data-excl]') return checkboxes;
    return [];
  },
  querySelector: (sel) => (sel === '.chip.cfp'
    ? chips.find((c) => (c.attrs.class || '').includes('cfp')) : null),
  getElementById: (id) => byId[id] || null,
  addEventListener: (t, fn) => { (docListeners[t] ||= []).push(fn); },
  dispatch: (t, ev) => { for (const fn of docListeners[t] || []) fn({ preventDefault() {}, ...ev }); },
};

// ---- run the shipped script ---------------------------------------------
new Function('document', FILTER_JS)(document);

// ---- assertions ----------------------------------------------------------
let fail = 0;
const vis = () => cards.filter((c) => c.style.display !== 'none').length;
const check = (label, ok, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : '  ' + detail}`);
  if (!ok) fail++;
};
const keysOf = (c) => (c.dataset.excl || '').split('|').filter(Boolean);
const noteN = () => parseInt((byId.hiddennote.textContent || '0').match(/^\d+/)?.[0] || '0', 10);
const box = (k) => checkboxes.find((b) => b.dataset.excl === k);

console.log('Markup contract');
check('no exclusion text box (inclusion only)', !/id="x"/.test(html), 'still present');
check('inclusion search box present', /id="q"/.test(html));
check('dropdown rendered as details/summary', /<details class="dd" id="excl-dd">/.test(html));
check('dropdown options are checkboxes', checkboxes.length > 0, 'no checkboxes found');
check('no leftover hide chips', !/class="chip hide"/.test(html), 'old chips still in markup');
check('cards parsed from the real markup', cards.length > 0, 'no cards found');
check('every card is visible on load', vis() === cards.length, `${vis()}/${cards.length}`);

console.log('\nDropdown exclusion (multi-select)');
const onlineCards = cards.filter((c) => keysOf(c).includes('Online'));
const onlineBox = box('Online');
check('an Online option exists', !!onlineBox, 'not rendered');
check('Online is listed first', checkboxes[0]?.dataset.excl === 'Online',
  `first=${checkboxes[0]?.dataset.excl}`);
if (onlineBox) {
  onlineBox.tick(true);
  check('ticking Online hides exactly the online cards',
    vis() === cards.length - onlineCards.length,
    `visible ${vis()}, expected ${cards.length - onlineCards.length}`);
  check('hidden count reported', noteN() === onlineCards.length,
    `note="${byId.hiddennote.textContent}"`);

  const sgBox = box('Singapore');
  const sgCards = cards.filter((c) => keysOf(c).includes('Singapore'));
  if (sgBox) {
    sgBox.tick(true);
    const union = cards.filter((c) =>
      keysOf(c).includes('Online') || keysOf(c).includes('Singapore')).length;
    check('two ticked options hide their union', vis() === cards.length - union,
      `visible ${vis()}, expected ${cards.length - union}`);
    check('summary reports 2 selected', /2/.test(byId['excl-count'].textContent),
      `summary="${byId['excl-count'].textContent}"`);
    check('dropdown marked active', dd.classList.contains('active'));
  }
  sgBox?.tick(false);
  check('unticking one restores only its cards',
    vis() === cards.length - onlineCards.length, `visible ${vis()}`);

  onlineBox.tick(false);
  check('unticking everything restores the full list', vis() === cards.length, `visible ${vis()}`);
  check('summary count clears', byId['excl-count'].textContent === '',
    `summary="${byId['excl-count'].textContent}"`);
  check('active flag removed', !dd.classList.contains('active'));
}

console.log('\nOutside-click closes the dropdown');
dd.open = true;
document.dispatch('click', { target: byId.q });
check('click outside closes it', dd.open === false);
dd.open = true;
document.dispatch('click', { target: checkboxes[0] });
check('click on an option keeps it open', dd.open === true);
dd.open = false;

console.log('\nInclusion search still works');
byId.q.type('kafka');
const kafka = cards.filter((c) => (c.dataset.text || '').includes('kafka'));
check('search narrows to matches', vis() === kafka.length, `visible ${vis()}, expected ${kafka.length}`);
check('search is case-insensitive', (() => { byId.q.type('KAFKA'); return vis() === kafka.length; })());
check('search composes with exclusion', (() => {
  const ob = box('Online');
  if (!ob) return false;
  ob.tick(true);
  const both = kafka.filter((c) => !keysOf(c).includes('Online')).length;
  const ok = vis() === both;
  ob.tick(false);
  return ok;
})(), 'search+exclusion did not intersect');
byId.q.type('');

console.log('\nReset');
const topicChip = chips.find((c) => c.dataset.topic !== undefined);
topicChip?.click();
box('Online')?.tick(true);
byId.q.type('kafka');
byId.reset.click();
check('reset restores every card', vis() === cards.length, `visible ${vis()}`);
check('reset clears the search box', byId.q.value === '', `"${byId.q.value}"`);
check('reset unticks the dropdown', checkboxes.every((b) => !b.checked), 'a box stayed ticked');
check('reset clears the selected count', byId['excl-count'].textContent === '');
check('reset unpresses the topic chip', topicChip?.getAttribute('aria-pressed') === 'false');

console.log('\nMonth headers');
check('all month headers visible when unfiltered',
  months.every((mm) => mm.style.display !== 'none'), 'a header was hidden');
checkboxes.forEach((b) => b.tick(true));
check('empty month headers hide under heavy exclusion',
  vis() === 0 || months.some((mm) => mm.style.display === 'none'), 'no header hidden');
checkboxes.forEach((b) => b.tick(false));

console.log('\nStyling');
check('no border-radius in served CSS', !/border-radius/.test(html), 'still rounded');

console.log(fail ? `\n${fail} FAILURE(S)` : '\nAll browser-logic checks passed.');
process.exit(fail ? 1 : 0);
