// Same-length patches: sleep after N min without touching the pet (and no agent activity),
// instead of N min without moving the mouse; only a touch (or agent activity) wakes her.
// global.__petTouchedAt is set on pointer-down on the pet; global.__petSleptAt when the yawn fires.
const fs = require('fs');

function patch(name, edits) {
  const raw = fs.readFileSync(name + '.orig.js', 'utf8');
  const NL = raw.includes('\r\n') ? '\r\n' : '\n';
  let s = raw.replace(/\r\n/g, '\n');
  const origLen = Buffer.byteLength(raw);
  for (const [a, b] of edits) {
    if (s.split(a).length !== 2) throw new Error(name + ': anchor not unique/missing: ' + a.slice(0, 60));
    s = s.replace(a, b);
  }
  // Free bytes by dropping whole-line // comments, top-down, until the edits fit.
  const deficit = () => Buffer.byteLength(s.replace(/\n/g, NL)) - origLen; // '/*PAD*/' is 7 bytes, pad must be >= 4
  const need = () => deficit() - 3;
  const lines = s.split('\n');
  for (let i = 3; i < lines.length && need() > 0; i++) {
    if (/^\s*\/\/(?!.*Local patch)/.test(lines[i])) { lines.splice(i, 1); i--; s = lines.join('\n'); }
  }
  const pad = 7 - deficit();
  if (pad < 4) throw new Error(name + ': not enough room');
  s = s.replace('/*PAD*/', '/*' + ' '.repeat(pad - 4) + '*/');
  const out = s.replace(/\n/g, NL);
  if (Buffer.byteLength(out) !== origLen) throw new Error(name + ': length mismatch');
  fs.writeFileSync(name + '.patched.js', out);
  console.log(name, 'ok', origLen);
}

patch('pet-interaction-ipc', [
  ['    if (locked) {\n      setMouseOverPet(true);',
   '    if (locked) {\n      global.__petTouchedAt = Date.now(); // Local patch: touch clock for sleep/wake\n      /*PAD*/\n      setMouseOverPet(true);'],
]);

patch('tick', [
  ['let mouseStillSince = Date.now();',
   'let mouseStillSince = Date.now();\nlet petTouchedAt = Date.now(), lastIdleAnimAt = Date.now(); // Local patch: sleep clock = last touch / idle entry, not mouse movement\n/*PAD*/'],
  ['      if (moved) {\n        resetIdlePeriodForMouseMove();\n      }\n\n      const elapsed',
   '      if (moved) mouseStillSince = Date.now(); // Local patch: mouse movement no longer cancels her actions\n\n      const elapsed'],
  ['        && !idleLookPlayed\n        && elapsed >= MOUSE_IDLE_TIMEOUT\n',
   '        && Date.now() - lastIdleAnimAt >= MOUSE_IDLE_TIMEOUT // Local patch: a random action every N s while idle\n'],
  ['        isMouseIdle = true;\n        idleLookPlayed = true;',
   '        isMouseIdle = true;\n        idleLookPlayed = true;\n        lastIdleAnimAt = Date.now();'],
  ['      const elapsed = Date.now() - mouseStillSince;\n',
   '      const elapsed = Date.now() - mouseStillSince;\n      const touchedElapsed = Date.now() - Math.max(petTouchedAt, global.__petTouchedAt || 0);\n'],
  ['      if (ctx.startupRecoveryActive) {\n        mouseStillSince = Date.now();',
   '      if (ctx.startupRecoveryActive) {\n        mouseStillSince = petTouchedAt = Date.now();'],
  ['      if (!hasTriggeredYawn && elapsed >= MOUSE_SLEEP_TIMEOUT) {\n        hasTriggeredYawn = true;',
   '      if (!hasTriggeredYawn && touchedElapsed >= MOUSE_SLEEP_TIMEOUT) {\n        hasTriggeredYawn = true;\n        global.__petSleptAt = Date.now();'],
  ['        lastCursorY = null;\n        mouseStillSince = Date.now();',
   '        lastCursorY = null;\n        mouseStillSince = petTouchedAt = lastIdleAnimAt = Date.now();'],
  ['function resetIdleTimer() {\n  mouseStillSince = Date.now();',
   'function resetIdleTimer() {\n  mouseStillSince = petTouchedAt = Date.now();'],
]);

patch('state', [
  ['  const moved = cursor.x !== lastWakeCursorX || cursor.y !== lastWakeCursorY;',
   '  const moved = (global.__petTouchedAt || 0) > (global.__petSleptAt || 0); // Local patch: only a touch wakes\n  /*PAD*/'],
  ['  if (currentState === "dozing" && Date.now() - ctx.mouseStillSince >= DEEP_SLEEP_TIMEOUT) {',
   '  if (currentState === "dozing" && Date.now() - (global.__petSleptAt || 0) >= DEEP_SLEEP_TIMEOUT) {'],
]);
