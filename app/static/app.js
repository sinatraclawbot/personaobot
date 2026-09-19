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

// Chat composer: pasting an image attaches it to the reply file input.
document.querySelectorAll('.chat-composer').forEach(function (form) {
  var ta = form.querySelector('textarea');
  var input = form.querySelector('input[name=file]');
  if (!ta || !input) return;
  ta.addEventListener('paste', function (e) {
    var items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
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