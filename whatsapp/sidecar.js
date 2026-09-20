// WhatsApp Web sidecar: logs into web.whatsapp.com with a persistent session,
// relays incoming messages to the Python app, and sends outgoing messages it is asked to send.
const { Client, LocalAuth } = require('whatsapp-web.js');
const QRCode = require('qrcode');
const http = require('http');
const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.WHATSAPP_DATA_DIR || '/var/data/whatsapp';
const BRIDGE_URL = process.env.WHATSAPP_BRIDGE_URL || 'http://localhost:8000';
const SECRET = process.env.WHATSAPP_WEBHOOK_SECRET || '';
const SEND_PORT = parseInt(process.env.WHATSAPP_SEND_PORT || '3001', 10);

fs.mkdirSync(DATA_DIR, { recursive: true });
const QR_FILE = path.join(DATA_DIR, 'qr.txt');

let client;

function startClient() {
  client = new Client({
    authStrategy: new LocalAuth({ dataPath: path.join(DATA_DIR, 'session') }),
    puppeteer: {
      executablePath: process.env.CHROME_PATH || '/usr/bin/chromium',
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    },
  });

  client.on('qr', async (qr) => {
    try {
      const dataUrl = await QRCode.toDataURL(qr);
      fs.writeFileSync(QR_FILE, dataUrl);
      console.log('qr_written');
    } catch (e) {
      console.error('qr_render_failed', e.message);
    }
  });

  client.on('authenticated', () => {
    try { fs.unlinkSync(QR_FILE); } catch (e) {}
  });

  client.on('ready', () => console.log('whatsapp_ready'));

  client.on('message', async (msg) => {
    if (msg.fromMe) return;
    try {
      const payload = {
        secret: SECRET,
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
          if (media && media.data) payload.media = { mimetype: media.mimetype, data: media.data };
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
  });

  client.on('disconnected', () => {
    console.log('whatsapp_disconnected, restarting');
    setTimeout(startClient, 3000);
  });

  client.initialize();
}

// Small HTTP server so the Python app can ask the sidecar to send messages.
http.createServer(async (req, res) => {
  res.setHeader('content-type', 'application/json');
  if (req.method !== 'POST' || req.url !== '/send') { res.writeHead(404); res.end('{}'); return; }
  let body = '';
  req.on('data', (c) => { body += c; });
  req.on('end', async () => {
    try {
      const data = JSON.parse(body);
      const chat = await client.getChatById(String(data.chat_id));
      await chat.sendMessage(data.text || '');
      res.writeHead(200);
      res.end(JSON.stringify({ ok: true }));
    } catch (e) {
      res.writeHead(500);
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
  });
}).listen(SEND_PORT, () => console.log('send_server_on_' + SEND_PORT));

startClient();