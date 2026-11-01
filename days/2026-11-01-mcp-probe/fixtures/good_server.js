// 의존성 없는 Node 판 정상 서버 (dev.to 글의 구조를 따른 최소 구현)
const rl = require('node:readline').createInterface({ input: process.stdin });
const send = (o) => process.stdout.write(JSON.stringify(o) + '\n');
rl.on('line', (line) => {
  let m; try { m = JSON.parse(line); } catch { return send({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'parse error' } }); }
  if (m.id === undefined) return;
  const ok = (result) => send({ jsonrpc: '2.0', id: m.id, result });
  const err = (code, message) => send({ jsonrpc: '2.0', id: m.id, error: { code, message } });
  if (m.method === 'initialize') ok({ protocolVersion: m.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: 'node-good', version: '1' } });
  else if (m.method === 'ping') ok({});
  else if (m.method === 'tools/list') ok({ tools: [{ name: 'now', description: 'time', inputSchema: { type: 'object', properties: {} } }] });
  else if (m.method === 'tools/call') (m.params && m.params.name === 'now') ? ok({ content: [{ type: 'text', text: 'now' }] }) : err(-32602, 'unknown tool');
  else err(-32601, 'method not found');
});
