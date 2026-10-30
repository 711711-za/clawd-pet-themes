// Same-length patch of src/hit-renderer.js: double-click reactions may list `files` (+ `durations`) and pick one at random.
const fs = require('fs');
const raw = fs.readFileSync('hit.orig.js', 'utf8');
const NL = raw.includes('\r\n') ? '\r\n' : '\n';
let s = raw.replace(/\r\n/g, '\n');
const origLen = Buffer.byteLength(raw);
const rep = (a, b) => { if (!s.includes(a)) throw new Error('missing: ' + a.slice(0, 60)); s = s.replace(a, b); };
const start = s.indexOf('// macOS is OUT:'), end = s.indexOf('//\n// Affordance gating lives HERE');
if (start < 0 || end < start) throw new Error('comment block not found');
s = s.slice(0, start) + 'FUNCHERE\n' + s.slice(end);
const m1 = s.indexOf("// Main released the lock because"), m2 = s.indexOf("// so gesture state, drag reaction");
if (m1 < 0 || m2 < m1) throw new Error("second comment not found");
s = s.slice(0, m1) + s.slice(s.indexOf('\n', m2) + 1);
rep('        const react = dir === "left" ? leftReact : rightReact;\n        playReaction(react.file, react.duration || 2500);\n',
    '        const react = dir === "left" ? leftReact : rightReact;\n        const pick = pickReactFile(react);\n        playReaction(pick.file, pick.duration);\n');
const fn = [
  '// Local patch: a click reaction may list `files` (+ `durations` map); pick one at random, never twice in a row.',
  'PADHERE',
  'let lastPickedFile = null;',
  'function pickReactFile(r) {',
  '  const pool = Array.isArray(r.files) && r.files.length ? r.files : [r.file];',
  '  const choices = pool.length > 1 ? pool.filter((f) => f !== lastPickedFile) : pool;',
  '  const file = choices[Math.floor(Math.random() * choices.length)];',
  '  lastPickedFile = file;',
  '  const d = r.durations ? Number(r.durations[file]) : 0;',
  '  return { file, duration: d > 0 ? d : (r.duration || 2500) };',
  '}',
].join('\n');
s = s.replace('FUNCHERE', fn);
let out = s.replace(/\n/g, NL);
const free = origLen - Buffer.byteLength(out.replace('PADHERE', ''));
if (free < 4) throw new Error('not enough room: ' + free);
out = out.replace('PADHERE', '/*' + ' '.repeat(free - 4) + '*/');
if (Buffer.byteLength(out) !== origLen) throw new Error('length mismatch');
fs.writeFileSync('hit.patched.js', out);
console.log('ok', origLen, 'padding', free - 4);
