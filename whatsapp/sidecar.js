// WhatsApp Web sidecar (multi-account): one persistent session per profile id.
// Logs into web.whatsapp.com, relays incoming messages to the Python app,
// and sends outgoing messages. Exposes a small HTTP API for the app to drive it.
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const QRCode = require('qrcode');
const http = require('http');
const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.WHATSAPP_DATA_DIR || '/var/data/whatsapp';
const BRIDGE_URL = process.env.WHATSAPP_BRIDGE_URL || 'http://localhost:8000';
const SECRET = process.env.WHATSAPP_WEBHOOK_SECRET || '';
const SEND_PORT = parseInt(process.env.WHATSAPP_SEND_PORT || '3001', 10);
const PROXY_RAW = process.env.WHATSAPP_PROXY || '';

let proxyUrl = null;
function getProxy() {
  if (proxyUrl !== null) return proxyUrl;
  proxyUrl = (async () => {
    if (!PROXY_RAW) return '';
    try {
      const proxyChain = require('proxy-chain');
      const url = await proxyChain.anonymizeProxy(PROXY_RAW);
      console.log('proxy_ready');
      return url;
    } catch (e) {
      console.error('proxy_setup_failed', e && e.message);
      return PROXY_RAW;
    }
  })();
  return proxyUrl;
}

fs.mkdirSync(DATA_DIR, { recursive: true });

const clients = {}; // profileId -> { status, qr, phone, client }

function cleanSingletonLocks(dir) {
  if (!fs.existsSync(dir)) return;
  fs.readdirSync(dir).forEach(function (name) {
    if (name === 'SingletonLock' || name === 'SingletonCookie' || name === 'SingletonSocket') {
      try { fs.unlinkSync(path.join(dir, name)); } catch (e) {}
      return;
    }
    const full = path.join(dir, name);
    try { if (fs.statSync(full).isDirectory()) cleanSingletonLocks(full); } catch (e) {}
  });
}

async function buildClient(profileId) {
  const entry = clients[profileId];
  const dataPath = path.join(DATA_DIR, 'session-' + profileId);
  fs.mkdirSync(dataPath, { recursive: true });
  cleanSingletonLocks(dataPath);
  const px = await getProxy();
  const chromeArgs = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--no-zygote',
  ];
  if (px) chromeArgs.push('--proxy-server=' + px);

  const client = new Client({
    authStrategy: new LocalAuth({ dataPath }),
    puppeteer: {
      headless: true,
      args: chromeArgs,
    },
  });

  client.on('qr', async (qr) => {
    try { entry.qr = await QRCode.toDataURL(qr); entry.status = 'pending'; } catch (e) {}
  });

  client.on('ready', async () => {
    entry.status = 'ready'; entry.qr = '';
    try { const info = client.info; if (info && info.wid) entry.phone = String(info.wid.user || ''); } catch (e) {}
  });

  client.on('message', (msg) => { if (!msg.fromMe) relay(profileId, msg); });

  client.on('disconnected', () => { entry.status = 'error'; });

  client.initialize().catch((err) => { entry.status = 'error'; console.error('client_init_failed', err && err.message); });
  entry.client = client;
}

async function relay(profileId, msg) {
  try {
    const payload = {
      secret: SECRET,
      profile_id: profileId,
      chat_id: String(msg.from),
      message_id: msg.id ? String(msg.id._serialized) : '',
      text: msg.body || '',
      type: msg.type || '',
      has_media: !!msg.hasMedia,
      timestamp: msg.timestamp || 0,
    };
    if (msg.hasMedia) {
      try {
        const media = await msg.downloadMedia();
        if (media && media.data) {
          const data = typeof media.data === 'string' ? media.data : Buffer.from(media.data).toString('base64');
          payload.media = { mimetype: media.mimetype, data };
        }
      } catch (e) {}
    }
    await fetch(BRIDGE_URL + '/webhooks/whatsapp', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    console.error('relay_failed', e.message);
  }
}

function ensure(profileId) {
  if (!clients[profileId]) {
    clients[profileId] = { status: 'starting', qr: '', phone: '', client: null };
    buildClient(profileId);
  }
  return clients[profileId];
}

async function readBody(req) {
  return new Promise((resolve) => {
    let b = '';
    req.on('data', (c) => { b += c; });
    req.on('end', () => { try { resolve(JSON.parse(b || '{}')); } catch (e) { resolve({}); } });
  });
}

function json(res, code, obj) {
  res.writeHead(code, { 'content-type': 'application/json' });
  res.end(JSON.stringify(obj));
}

http.createServer(async (req, res) => {
  const url = (req.url || '').split('?')[0];
  if (req.method === 'POST' && url === '/connect') {
    const { profile_id } = await readBody(req);
    if (!profile_id) return json(res, 400, { ok: false });
    ensure(String(profile_id));
    return json(res, 200, { ok: true });
  }
  if (req.method === 'POST' && url === '/disconnect') {
    const { profile_id } = await readBody(req);
    const pid = String(profile_id || '');
    const e = clients[pid];
    if (e && e.client) { try { await e.client.destroy(); } catch (err) {} }
    delete clients[pid];
    return json(res, 200, { ok: true });
  }
  if (req.method === 'GET' && url.startsWith('/qr/')) {
    const pid = url.slice(4);
    const e = clients[pid];
    if (!e) return json(res, 200, { status: 'none' });
    if (e.status === 'ready') return json(res, 200, { status: 'ready', phone: e.phone });
    return json(res, 200, { status: e.status, qr: e.qr || '' });
  }
  if (req.method === 'GET' && url === '/status') {
    const out = {};
    for (const [pid, e] of Object.entries(clients)) out[pid] = { status: e.status, phone: e.phone };
    return json(res, 200, { profiles: out });
  }
  if (req.method === 'POST' && url === '/send') {
    const data = await readBody(req);
    const e = clients[String(data.profile_id || '')];
    if (!e || !e.client) return json(res, 500, { ok: false, error: 'not_connected' });
    try {
      const chat = await e.client.getChatById(String(data.chat_id));
      const media = Array.isArray(data.media) ? data.media : [];
      for (let i = 0; i < media.length; i++) {
        const item = media[i];
        const m = MessageMedia.fromFilePath(item.path);
        const caption = (i === 0 && data.text) ? data.text : undefined;
        await chat.sendMessage(m, { caption });
      }
      if (media.length === 0 && data.text) await chat.sendMessage(data.text);
      return json(res, 200, { ok: true });
    } catch (err) {
      return json(res, 500, { ok: false, error: err.message });
    }
  }
  return json(res, 404, { ok: false });
}).listen(SEND_PORT, () => console.log('whatsapp_sidecar_on_' + SEND_PORT));