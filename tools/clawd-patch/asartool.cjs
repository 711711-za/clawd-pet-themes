// usage: node asartool.cjs extract <asar> <path> <out> | patch <asar> <path> <newfile>
const fs = require('fs');
const [cmd, A, P, F] = process.argv.slice(2);
const fd = fs.openSync(A, cmd === 'patch' ? 'r+' : 'r');
const b8 = Buffer.alloc(8); fs.readSync(fd, b8, 0, 8, 0);
const headerSize = b8.readUInt32LE(4);
const hb = Buffer.alloc(headerSize); fs.readSync(fd, hb, 0, headerSize, 8);
const json = JSON.parse(hb.toString('utf8', 8, 8 + hb.readUInt32LE(4)));
let node = json; for (const part of P.split('/')) node = node.files[part];
if (node.unpacked) throw new Error('file is unpacked');
const off = 8 + headerSize + Number(node.offset), size = node.size;
if (cmd === 'extract') { const buf = Buffer.alloc(size); fs.readSync(fd, buf, 0, size, off); fs.writeFileSync(F, buf); console.log('extracted', size, 'bytes at', off); }
else { const nb = fs.readFileSync(F); if (nb.length !== size) throw new Error(`size mismatch ${nb.length} != ${size}`); fs.writeSync(fd, nb, 0, size, off); console.log('patched', size, 'bytes'); }
fs.closeSync(fd);
