// Prevent accidental double submissions without disabling the clicked action value.
document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', event => {
    if (form.dataset.submitting === 'yes') { event.preventDefault(); return; }
    form.dataset.submitting = 'yes';
    form.setAttribute('aria-busy', 'true');
    window.setTimeout(() => { delete form.dataset.submitting; form.removeAttribute('aria-busy'); }, 15000);
  });
});

function toast(msg) {
  var t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  window.setTimeout(function () { t.classList.add('show'); }, 10);
  window.setTimeout(function () { t.classList.remove('show'); window.setTimeout(function () { t.remove(); }, 300); }, 2200);
}

// Conversation story bubbles: 5 stage colors + "awaiting reply" blink that speeds up each minute.
(function () {
  function blinkClass(mins) {
    if (mins >= 20) return 'blink5';
    if (mins >= 12) return 'blink4';
    if (mins >= 8) return 'blink3';
    if (mins >= 6) return 'blink2';
    return 'blink1';
  }
  function updateStories() {
    var now = Date.now() / 1000;
    document.querySelectorAll('.story').forEach(function (s) {
      var ring = s.querySelector('.story-ring');
      var state = s.getAttribute('data-state');
      if (!ring || !state) return;
      var stage = state, blink = '';
      if (state === 'active') {
        var unanswered = s.getAttribute('data-unanswered') === '1';
        var last = parseFloat(s.getAttribute('data-last') || '0');
        var mins = (unanswered && last > 0) ? (now - last) / 60 : 0;
        if (unanswered && mins > 4) {
          stage = 'waiting';
          blink = blinkClass(mins);
        }
      }
      ring.className = 'story-ring stage-' + stage + (blink ? ' ' + blink : '');
    });
  }
  updateStories();
  setInterval(updateStories, 10000);
})();

// Gallery icons: clicking attaches the actual media file (photo or video) to the reply.
document.querySelectorAll('.gallery-icon').forEach(function (btn) {
  btn.addEventListener('click', async function () {
    var url = btn.getAttribute('data-copy');
    var form = document.querySelector('.chat-composer');
    var input = form && form.querySelector('input[name=file]');
    if (!input) { toast('Open a conversation first'); return; }
    try {
      var resp = await fetch(url, { credentials: 'same-origin' });
      if (!resp.ok) throw new Error('status ' + resp.status);
      var blob = await resp.blob();
      var ext = (url.split('?')[0].split('.').pop() || 'bin').toLowerCase();
      var name = 'media.' + ext;
      var dt = new DataTransfer();
      dt.items.add(new File([blob], name, { type: blob.type || 'application/octet-stream' }));
      input.files = dt.files;
      var attach = form.querySelector('.attach');
      attach.classList.add('has-file');
      attach.title = 'Attached: ' + name;
      var label = form.querySelector('.attach-name');
      if (label) label.textContent = '✓ ' + name;
      btn.classList.add('copied');
      toast('Media copied — press Send to send it');
      window.setTimeout(function () { btn.classList.remove('copied'); }, 1200);
    } catch (e) {
      toast('Could not attach media');
    }
  });
});

// Chat composer: pasting an image attaches it to the reply file input (delegated so
// it keeps working after the chat is swapped via AJAX).
document.addEventListener('paste', function (e) {
  var ta = e.target;
  if (!ta || !ta.matches || !ta.matches('.chat-composer textarea')) return;
  var form = ta.closest('.chat-composer');
  var input = form && form.querySelector('input[name=file]');
  var items = e.clipboardData && e.clipboardData.items;
  if (!items || !input) return;
  for (var i = 0; i < items.length; i++) {
    var it = items[i];
    if (it.type && it.type.indexOf('image/') === 0) {
      var blob = it.getAsFile();
      if (blob) {
        try {
          var dt = new DataTransfer();
          dt.items.add(new File([blob], 'pasted.png', { type: blob.type }));
          input.files = dt.files;
          form.querySelector('.attach').classList.add('has-file');
        } catch (err) {}
      }
      break;
    }
  }
});

// About / "Suggest reply" tabs: two AI-generated suggested messages for the current conversation.
var suggestions = [];
document.querySelectorAll('.about-tabs').forEach(function (tabs) {
  tabs.querySelectorAll('.tab-button').forEach(function (btn) {
    btn.addEventListener('click', function () {
      tabs.querySelectorAll('.tab-button').forEach(function (b) { b.classList.remove('on'); });
      btn.classList.add('on');
      var panel = btn.closest('.panel');
      var which = btn.getAttribute('data-tab');
      panel.querySelectorAll('.about-pane').forEach(function (p) {
        p.hidden = (p.getAttribute('data-pane') !== which);
      });
      if (which === 'suggest') {
        var pid = btn.getAttribute('data-pid');
        var cid = btn.getAttribute('data-cid');
        var status = panel.querySelector('.suggest-status');
        if (!cid) { status.textContent = 'Select a conversation first.'; return; }
        if (btn.dataset.loaded === '1') return;
        btn.dataset.loaded = '1';
        status.textContent = 'Generating…';
        fetch('/p/' + pid + '/suggest?cid=' + encodeURIComponent(cid), { credentials: 'same-origin' })
          .then(function (r) { if (!r.ok) throw 0; return r.json(); })
          .then(function (d) {
            suggestions = d.suggestions || [];
            panel.querySelector('.s1').textContent = suggestions[0] || '';
            panel.querySelector('.s2').textContent = suggestions[1] || '';
            status.textContent = suggestions.length ? '' : 'No suggestions.';
          })
          .catch(function () { status.textContent = 'Could not generate suggestions.'; });
      }
    });
  });
});

// "Use" buttons copy the corresponding suggestion into the chat composer.
document.querySelectorAll('.suggest-use').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var idx = parseInt(btn.getAttribute('data-idx'), 10);
    var ta = document.querySelector('.chat-composer textarea');
    if (ta && suggestions[idx]) { ta.value = suggestions[idx]; ta.focus(); }
  });
});

// Auto-scroll the conversation transcript to the latest message on load.
function scrollTranscriptToBottom() {
  document.querySelectorAll('.transcript').forEach(function (el) {
    el.scrollTop = el.scrollHeight;
    var last = el.querySelector('article:last-child');
    if (last) last.scrollIntoView({ block: 'end' });
  });
}
scrollTranscriptToBottom();
window.addEventListener('load', scrollTranscriptToBottom);
setTimeout(scrollTranscriptToBottom, 400);

// Smooth conversation switching: load the chat via AJAX instead of reloading the page.
function resetSuggest() {
  var btn = document.querySelector('.about-tabs [data-tab=suggest]');
  if (btn) delete btn.dataset.loaded;
  var pane = document.querySelector('.about-pane[data-pane=suggest]');
  if (pane) {
    var s1 = pane.querySelector('.s1'); if (s1) s1.textContent = '';
    var s2 = pane.querySelector('.s2'); if (s2) s2.textContent = '';
    var st = pane.querySelector('.suggest-status'); if (st) st.textContent = '';
  }
}
function loadChat(url, item) {
  fetch(url, { credentials: 'same-origin' })
    .then(function (r) { if (!r.ok) throw 0; return r.json(); })
    .then(function (d) {
      var wrap = document.getElementById('chat-wrap');
      if (wrap) wrap.innerHTML = d.html;
      document.querySelectorAll('.conv-item').forEach(function (i) { i.classList.remove('selected'); });
      if (item) item.classList.add('selected');
      var sug = document.querySelector('.about-tabs [data-tab=suggest]');
      if (sug && d.cid) sug.setAttribute('data-cid', d.cid);
      resetSuggest();
      scrollTranscriptToBottom();
      setTimeout(scrollTranscriptToBottom, 200);
    })
    .catch(function () { window.location.reload(); });
}
document.querySelectorAll('.conv-item').forEach(function (item) {
  item.addEventListener('click', function (e) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    loadChat(item.getAttribute('data-chat'), item);
    history.pushState({}, '', item.getAttribute('href'));
  });
});
window.addEventListener('popstate', function () {
  var pid = (document.querySelector('.conv-list') || {}).getAttribute('data-pid');
  var cid = new URLSearchParams(window.location.search).get('cid');
  if (pid && cid) loadChat('/p/' + pid + '/chat/' + cid, null);
  else if (pid) window.location.reload();
});

// Fast send: submit the reply via AJAX (no page reload) and update the chat in place.
function appendOutgoing(text, media) {
  var transcript = document.querySelector('.chat .transcript');
  if (!transcript) return;
  var art = document.createElement('article');
  art.className = 'message outgoing';
  var meta = document.createElement('div');
  meta.className = 'message-meta';
  meta.textContent = 'Assistant · now';
  art.appendChild(meta);
  if (text) {
    var b = document.createElement('div');
    b.className = 'bubble';
    b.setAttribute('dir', 'auto');
    b.textContent = text;
    art.appendChild(b);
  }
  if (media && media.length) {
    var box = document.createElement('div');
    box.className = 'msg-media';
    var pid = (document.querySelector('.conv-list') || {}).getAttribute('data-pid');
    media.forEach(function (item) {
      var url = '/media/' + pid + '/chat/' + item.name;
      if (item.kind === 'video') {
        var v = document.createElement('video'); v.src = url; v.controls = true; v.preload = 'metadata';
        box.appendChild(v);
      } else {
        var im = document.createElement('img'); im.src = url;
        box.appendChild(im);
      }
    });
    art.appendChild(box);
  }
  transcript.appendChild(art);
}
function updateSelectedListItem(text, hasFile) {
  var item = document.querySelector('.conv-item.selected');
  if (!item) return;
  var preview = item.querySelector('.conv-preview');
  var time = item.querySelector('.conv-time');
  var dot = item.querySelector('.wait-dot');
  if (preview) preview.textContent = hasFile ? '📎 Media' : (text || '');
  if (time) time.textContent = 'now';
  if (dot) dot.remove();
}
document.addEventListener('submit', function (e) {
  var form = e.target;
  if (!form || !form.matches || !form.matches('.chat-composer')) return;
  e.preventDefault();
  if (form.dataset.sending === 'yes') return;
  var ta = form.querySelector('textarea');
  var fileInput = form.querySelector('input[name=file]');
  var text = ta ? ta.value.trim() : '';
  var file = fileInput && fileInput.files && fileInput.files.length ? fileInput.files[0] : null;
  if (!text && !file) { toast('Type a message or attach something'); return; }
  form.dataset.sending = 'yes';
  form.setAttribute('aria-busy', 'true');
  var fd = new FormData(form);
  fd.set('ajax', '1');
  fetch(form.action, { method: 'POST', body: fd, credentials: 'same-origin' })
    .then(function (r) { if (!r.ok) throw 0; return r.json(); })
    .then(function (d) {
      if (d.ok) {
        var media = d.media || [];
        appendOutgoing(text, media);
        updateSelectedListItem(text, media.length > 0);
        if (ta) ta.value = '';
        if (fileInput) fileInput.value = '';
        var attach = form.querySelector('.attach');
        if (attach) { attach.classList.remove('has-file'); attach.title = 'Attach photo or video'; }
        var an = form.querySelector('.attach-name'); if (an) an.textContent = '';
        scrollTranscriptToBottom();
      } else {
        toast(d.error || 'Could not send');
      }
    })
    .catch(function () { toast('Could not send'); })
    .then(function () { delete form.dataset.sending; form.removeAttribute('aria-busy'); });
});

// WhatsApp connect (profile settings): QR login flow.
function waPid(btn) { return btn.closest('.wa-connect').getAttribute('data-pid'); }
function waPollQr(box, pid) {
  fetch('/whatsapp/qr/' + pid, { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.status === 'ready') {
        box.innerHTML = '<p class="muted fine">Connected! Reloading…</p>';
        setTimeout(function () { window.location.reload(); }, 800);
        return;
      }
      if (d.qr) {
        box.innerHTML = '<p class="fine">Scan with WhatsApp on your phone:</p><img src="' + d.qr + '" alt="QR code">';
      } else if (d.status === 'error' || d.status === 'none') {
        box.innerHTML = '<p class="muted fine">Could not reach the WhatsApp bridge. Try again.</p>';
        return;
      }
      setTimeout(function () { waPollQr(box, pid); }, 3000);
    })
    .catch(function () { box.innerHTML = '<p class="muted fine">Could not reach the WhatsApp bridge.</p>'; });
}
document.querySelectorAll('.wa-btn[data-action="connect"]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var pid = waPid(btn);
    var box = btn.closest('.wa-connect').querySelector('.wa-qr-box');
    box.hidden = false;
    box.innerHTML = '<p class="muted fine">Opening WhatsApp login…</p>';
    fetch('/whatsapp/connect/' + pid, { method: 'POST', credentials: 'same-origin' })
      .then(function () { waPollQr(box, pid); })
      .catch(function () { box.innerHTML = '<p class="muted fine">Could not start the connection.</p>'; });
  });
});
document.querySelectorAll('.wa-btn[data-action="disconnect"]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var pid = waPid(btn);
    fetch('/whatsapp/disconnect/' + pid, { method: 'POST', credentials: 'same-origin' })
      .then(function () { window.location.reload(); });
  });
});