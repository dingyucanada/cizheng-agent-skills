/* A small, dependency-free ZIP writer. Entries are stored without compression. */
const encoder = new TextEncoder();
const crcTable = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

export function crc32(bytes) {
  let c = 0xffffffff;
  for (const byte of bytes) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function concat(parts) {
  const result = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of parts) { result.set(part, offset); offset += part.length; }
  return result;
}

function safePath(path) {
  if (typeof path !== 'string' || !path || path.includes('\\') || path.startsWith('/') || /(^|\/)\.\.(\/|$)/.test(path) || path.includes('\0')) {
    throw new Error('ZIP entry path must be a safe relative path');
  }
  return path;
}

export function makeZip(entries) {
  if (!Array.isArray(entries) || entries.length > 65535) throw new Error('Unsupported ZIP entry count');
  const locals = [], central = [], names = new Set();
  let offset = 0;
  // A fixed date makes identical teaching exports reproducible.
  const dosDate = ((2026 - 1980) << 9) | (1 << 5) | 1;
  for (const entry of entries) {
    const path = safePath(entry.path);
    if (names.has(path)) throw new Error(`Duplicate ZIP entry: ${path}`);
    names.add(path);
    const name = encoder.encode(path);
    const data = typeof entry.data === 'string' ? encoder.encode(entry.data) : new Uint8Array(entry.data);
    if (name.length > 65535 || data.length > 0xffffffff) throw new Error('ZIP entry is too large');
    const crc = crc32(data);
    const local = new Uint8Array(30 + name.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true); lv.setUint16(4, 20, true); lv.setUint16(6, 0x0800, true);
    lv.setUint16(10, 0, true); lv.setUint16(12, dosDate, true); lv.setUint32(14, crc, true);
    lv.setUint32(18, data.length, true); lv.setUint32(22, data.length, true); lv.setUint16(26, name.length, true);
    local.set(name, 30);
    const record = new Uint8Array(46 + name.length);
    const cv = new DataView(record.buffer);
    cv.setUint32(0, 0x02014b50, true); cv.setUint16(4, 20, true); cv.setUint16(6, 20, true);
    cv.setUint16(8, 0x0800, true); cv.setUint16(12, 0, true); cv.setUint16(14, dosDate, true);
    cv.setUint32(16, crc, true); cv.setUint32(20, data.length, true); cv.setUint32(24, data.length, true);
    cv.setUint16(28, name.length, true); cv.setUint32(42, offset, true); record.set(name, 46);
    locals.push(local, data); central.push(record);
    offset += local.length + data.length;
  }
  const directory = concat(central);
  if (offset + directory.length > 0xffffffff) throw new Error('ZIP64 is not supported');
  const end = new Uint8Array(22);
  const ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true); ev.setUint16(8, entries.length, true); ev.setUint16(10, entries.length, true);
  ev.setUint32(12, directory.length, true); ev.setUint32(16, offset, true);
  return concat([...locals, directory, end]);
}
