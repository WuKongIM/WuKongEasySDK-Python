// Actual pinned JS SDK; stdin commands and stdout receipts are harness boundaries.
const readline = require('node:readline');
const { WKIM, WKIMDeviceFlag, WKIMEvent } = require(process.env.WKIM_JS_ENTRY);
const emit = (kind, value) => console.log(JSON.stringify({kind, ...value}));
const im = WKIM.init(process.env.WKIM_URL, {
  uid: 'cluster-bob', token: process.env.WKIM_BOB_TOKEN,
  deviceFlag: WKIMDeviceFlag.Desktop,
}, { singleton: false });
im.on(WKIMEvent.Error, () => emit('error', {}));
im.on(WKIMEvent.Connect, result => emit('connect', {result}));
im.on(WKIMEvent.Message, message => emit('message', {message}));
readline.createInterface({input: process.stdin}).on('line', async line => {
  const command = JSON.parse(line);
  try {
    if (command.kind === 'send') {
      const ack = await im.send(command.uid, 1, command.payload);
      emit('ack', {id: command.id, ack});
    } else if (command.kind === 'stop') {
      im.destroy();
      process.exit(0);
    }
  } catch (_) { emit('failed', {id: command.id}); }
});
im.connect().then(() => emit('ready', {})).catch(() => {
  emit('fatal', {}); im.destroy(); process.exit(1);
});
process.on('SIGTERM', () => { im.destroy(); process.exit(0); });
