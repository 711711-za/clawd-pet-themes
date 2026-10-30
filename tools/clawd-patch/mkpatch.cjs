const fs = require('fs');
const raw = fs.readFileSync('orig.js', 'utf8');
const NL = raw.includes('\r\n') ? '\r\n' : '\n';
let s = raw.replace(/\r\n/g, '\n');
const origLen = Buffer.byteLength(raw);
const rep = (a, b) => { if (!s.includes(a)) throw new Error('missing: ' + a.slice(0, 60)); s = s.replace(a, b); };
const start = s.indexOf('// Deliberately NOT here:'), end = s.indexOf('function buildReadoutFoot(model)');
if (start < 0 || end < start) throw new Error('comment block not found');
s = s.slice(0, start) + s.slice(end);
rep('    win.textContent = shown.label;\n', '    win.textContent = shown.label + resetClock(shown);\n');
rep('  } else if (model.sourceMarker) {\n    text = model.sourceMarker;\n  }',
    '  } else if (model.windows[0] && model.windows[0] !== model.displayWindow && resetClock(model.windows[0])) {\n    text = model.windows[0].label + resetClock(model.windows[0]);\n  } else if (model.sourceMarker) {\n    text = model.sourceMarker;\n  }');
rep('function buildReadoutFoot(model) {',
    '// Local patch: show when a window resets as wall-clock time (" 21:30"); absolute, so it never goes stale.\nPADHERE\nfunction resetClock(w) {\n  const n = Number(w && w.resetAt);\n  if (!w || w.reset || !Number.isFinite(n) || n <= Date.now()) return "";\n  const d = new Date(n), p = (v) => String(v).padStart(2, "0");\n  return ` ${p(d.getHours())}:${p(d.getMinutes())}`;\n}\n\nfunction buildReadoutFoot(model) {');
let out = s.replace(/\n/g, NL);
const free = origLen - Buffer.byteLength(out.replace('PADHERE', ''));
if (free < 4) throw new Error('not enough room: ' + free);
out = out.replace('PADHERE', '/*' + ' '.repeat(free - 4) + '*/');
if (Buffer.byteLength(out) !== origLen) throw new Error('len ' + Buffer.byteLength(out) + ' vs ' + origLen);
fs.writeFileSync('patched.js', out);
console.log('ok', origLen, 'padding', free - 4);
