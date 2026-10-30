// Same-length patch of src/menu.js: right-click "做动作" submenu, listed by the active user theme's `actionMenu`.
const fs = require('fs');
const raw = fs.readFileSync('menu.orig.js', 'utf8');
const NL = raw.includes('\r\n') ? '\r\n' : '\n';
let s = raw.replace(/\r\n/g, '\n');
const origLen = Buffer.byteLength(raw);
const cut = (from, to) => {
  const a = s.indexOf(from), b = s.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('missing: ' + from.slice(0, 40));
  s = s.slice(0, a) + s.slice(b);
};
const rep = (a, b) => { if (!s.includes(a)) throw new Error('missing: ' + a.slice(0, 60)); s = s.replace(a, b); };
cut('// Login-item / autostart helpers', 'const WIN_TOPMOST_LEVEL');
cut('    // Grouped as state / work / display', '    const stateGroup = [');
cut('    // Intent is captured at build time', '    const petHiddenAtBuild');
cut('    // Quit stands alone as the final group', '    const quitGroup');
rep('const WIN_TOPMOST_LEVEL', 'FUNCHERE\n\nconst WIN_TOPMOST_LEVEL');
rep('      { ...buildMiniModeMenuItem() },\n', '      { ...buildMiniModeMenuItem() },\n      ...actionMenuItems(ctx),\n');
const fn = [
  '// Local patch: "做动作" submenu from the active user theme\'s `actionMenu` [{ label, file, duration }].',
  'PADHERE',
  'function actionMenuItems(ctx) {',
  '  try {',
  '    const id = String(ctx.getActiveThemeId());',
  '    const file = path.join(ctx.ensureUserThemesDir(), id, "theme.json");',
  '    const list = (JSON.parse(require("fs").readFileSync(file, "utf8")).actionMenu || []).filter((a) => a && a.file);',
  '    if (!list.length) return [];',
  '    return [{ label: "做动作", submenu: list.map((a) => ({',
  '      label: String(a.label || a.file),',
  '      click: () => require("electron").ipcMain.emit("play-click-reaction", {}, a.file, Number(a.duration) || 3000),',
  '    })) }];',
  '  } catch { return []; }',
  '}',
].join('\n');
s = s.replace('FUNCHERE', fn);
let out = s.replace(/\n/g, NL);
const free = origLen - Buffer.byteLength(out.replace('PADHERE', ''));
if (free < 4) throw new Error('not enough room: ' + free);
out = out.replace('PADHERE', '/*' + ' '.repeat(free - 4) + '*/');
if (Buffer.byteLength(out) !== origLen) throw new Error('length mismatch');
fs.writeFileSync('menu.patched.js', out);
console.log('ok', origLen, 'padding', free - 4);
