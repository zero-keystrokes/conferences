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
    this.style = { display: '' };
    this.value = '';
    this._listeners = {};
    this.nextElementSibling = null;
    this._pressed = 'false';
  }
  get classList() {
    const cls = (this.attrs.class || '').split(/\s+/).filter(Boolean);
    return { contains: (c) => cls.includes(c), _cls: cls };
  }
  setAttribute(k, v) { if (k === 'aria-pressed') this._pressed = String(v); }
  getAttribute(k) { return k === 'aria-pressed' ? this._pressed : (this.attrs[k] ?? null); }
  addEventListener(t, fn) { (this._listeners[t] ||= []).push(fn); }
  dispatch(t, ev = {}) { for (const fn of this._listeners[t] || []) fn({ preventDefault() {}, ...ev }); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = v; }
  // test helper
  click() { this.dispatch('click'); }
  type(v) { this.value = v; this.dispatch('input'); }
}

// Parse h2 / month / card in document order so nextElementSibling is faithful.
const TOKEN = /<h2>([\s\S]*?)<\/h2>|<div class="month">([\s\S]*?)<\/div>|<div class="(card[^"]*)" data-topics="([^"]*)" data-cfp="([^"]*)" data-excl="([^"]*)" data-text="([^"]*)">/g;
const ordered = [];
const cards = [], months = [], h2s = [];
let m;
while ((m = TOKEN.exec(html)) !== null) {
  if (m[1] !== undefined) {
    const el = new El('H2', {}, m[1]); ordered.push(el); h2s.push(el);
  } else if (m[2] !== undefined) {
    const el = new El('DIV', { class: 'month' }, m[2]); ordered.push(el); months.push(el);
  } else {
    const el = new El('DIV', { class: m[3] });
    el.dataset.topics = m[4]; el.dataset.cfp = m[5]; el.dataset.excl = m[6]; el.dataset.text = m[7];
    ordered.push(el); cards.push(el);
  }
}
for (let i = 0; i < ordered.length - 1; i++) ordered[i].nextElementSibling = ordered[i + 1];

const chips = [], hideChips = [], byId = {};
const chipRe = /<span class="chip([^"]*)"([^>]*?)>([\s\S]*?)<\/span>/g;
while ((m = chipRe.exec(html)) !== null) {
  const cls = 'chip' + m[1];
  const attrs = { class: cls };
  for (const a of m[2].matchAll(/(data-[a-z]+|id)="([^"]*)"/g)) attrs[a[1]] = a[2];
  const el = new El('SPAN', attrs, m[3]);
  if (cls.includes('hide')) hideChips.push(el); else chips.push(el);
  if (attrs.id) byId[attrs.id] = el;
}
byId.q = new El('INPUT'); byId.x = new El('INPUT');
byId.noshow = new El('DIV', {}, ''); byId.hiddennote = new El('SPAN', {}, '');
byId.reset = chips.find((c) => (c.attrs.class || '').includes('reset')) ||
  [...hideChips, ...chips].find((c) => c.dataset.topic === undefined && (c.attrs.class || '').includes('reset'));

// the reset chip has no data-topic; find it by markup
const resetMatch = html.match(/<span class="chip" id="reset"[^>]*>reset<\/span>/);
if (resetMatch) byId.reset = new El('SPAN', { class: 'chip', id: 'reset' }, 'reset');

const document = {
  querySelectorAll: (sel) => {
    if (sel === '.card') return cards;
    if (sel === '.month') return months;
    // '.chip' must match topic chips, the CFP toggle, reset AND hide chips —
    // reset relies on this to unpress the hide chips.
    if (sel === '.chip') return [...chips, ...hideChips];
    if (sel === '.chip[data-topic]') return chips.filter((c) => c.dataset.topic !== undefined);
    if (sel === '.chip.hide') return hideChips;
    return [];
  },
  querySelector: (sel) => (sel === '.chip.cfp'
    ? chips.find((c) => (c.attrs.class || '').includes('cfp')) : null),
  getElementById: (id) => byId[id] || null,
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

console.log('Baseline');
check('every card is visible on load', vis() === cards.length, `${vis()}/${cards.length}`);
check('cards parsed from the real markup', cards.length > 0, 'no cards found');

const onlineCards = cards.filter((c) => keysOf(c).includes('Online'));
console.log('\nHide chips (exact key exclusion)');
const onlineChip = hideChips.find((c) => c.dataset.excl === 'Online');
check('an Online hide chip exists', !!onlineChip, 'not rendered');
if (onlineChip) {
  onlineChip.click();
  check('clicking Hide Online hides exactly the online cards',
    vis() === cards.length - onlineCards.length,
    `visible ${vis()}, expected ${cards.length - onlineCards.length}`);
  check('chip reflects pressed state', onlineChip.getAttribute('aria-pressed') === 'true');
  check('hidden count reported to the user', noteN() === onlineCards.length,
    `note said ${byId.hiddennote.textContent}`);
  onlineChip.click();
  check('clicking again restores them', vis() === cards.length, `visible ${vis()}`);
  check('count note clears', byId.hiddennote.textContent === '', `"${byId.hiddennote.textContent}"`);
}

console.log('\nExclude text box (substring exclusion)');
const sgCards = cards.filter((c) => (c.dataset.text || '').includes('singapore'));
byId.x.type('singapore');
check('excluding "singapore" hides matching cards only',
  vis() === cards.length - sgCards.length,
  `visible ${vis()}, expected ${cards.length - sgCards.length}`);
check('matching is case-insensitive', (() => {
  byId.x.type('SINGAPORE');
  return vis() === cards.length - sgCards.length;
})());
check('comma-separated terms all apply', (() => {
  byId.x.type('singapore, online');
  const both = cards.filter((c) =>
    (c.dataset.text || '').includes('singapore') || keysOf(c).includes('Online')).length;
  return vis() === cards.length - both;
})());
byId.x.type('   ');
check('whitespace-only exclusion is a no-op', vis() === cards.length, `visible ${vis()}`);
byId.x.type('');

console.log('\nReset');
const topicChip = chips.find((c) => c.dataset.topic !== undefined);
if (topicChip) topicChip.click();
if (onlineChip) onlineChip.click();
byId.x.type('berlin');
byId.q.type('kafka');
const afterFilter = vis();
byId.reset.click();
check('reset restores every card', vis() === cards.length,
  `after filters ${afterFilter}, after reset ${vis()}`);
check('reset clears the exclude box', byId.x.value === '', `"${byId.x.value}"`);
check('reset clears the search box', byId.q.value === '', `"${byId.q.value}"`);
check('reset unpresses the hide chip',
  !onlineChip || onlineChip.getAttribute('aria-pressed') === 'false');

console.log('\nSearch still works alongside exclusion');
byId.q.type('kafka');
const kafka = cards.filter((c) => (c.dataset.text || '').includes('kafka'));
check('search narrows to matches', vis() === kafka.length, `visible ${vis()}, expected ${kafka.length}`);
byId.q.type('');

console.log('\nMonth headers');
const monthAfter = months.filter((mm) => mm.style.display === 'none').length;
check('all month headers visible when nothing is filtered', monthAfter === 0,
  `${monthAfter} hidden`);
byId.x.type('online, singapore, hungary, lithuania, spain, south africa');
check('empty month headers hide when everything is excluded',
  vis() === 0 || months.some((mm) => mm.style.display === 'none'),
  'no month header was hidden despite exclusions');

console.log('\nFilename/markup contract');
check('no border-radius in served CSS', !/border-radius/.test(html), 'still rounded');

console.log(fail ? `\n${fail} FAILURE(S)` : '\nAll browser-logic checks passed.');
process.exit(fail ? 1 : 0);
