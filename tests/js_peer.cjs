// Execute the actual built WuKongEasySDK-JS, not a synthetic wire client.
const { WKIM, WKIMChannelType, WKIMDeviceFlag, WKIMEvent } = require(process.env.WKIM_JS_ENTRY);
const im = WKIM.init(process.env.WKIM_URL, {
  uid: 'python-bob', token: process.env.WKIM_BOB_TOKEN,
  deviceFlag: WKIMDeviceFlag.Desktop,
}, { singleton: false });
im.on(WKIMEvent.Error, () => { console.error('JS peer operation failed'); });
im.on(WKIMEvent.Message, async (message) => {
  try {
    const ack = await im.send('python-alice', WKIMChannelType.Person, message.payload);
    if (ack.reasonCode !== 1) throw new Error('Rejected');
  } catch (_) {
    console.error('JS peer reply failed');
    process.exitCode = 1;
  }
});
im.connect().then(() => console.log('READY')).catch(() => {
  console.error('JS peer CONNECT failed');
  im.destroy();
  process.exitCode = 1;
});
process.on('SIGTERM', () => { im.destroy(); process.exit(0); });
process.on('SIGINT', () => { im.destroy(); process.exit(0); });
