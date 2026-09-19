// Prevent accidental double submissions without disabling the clicked action value.
document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', event => {
    if (form.dataset.submitting === 'yes') { event.preventDefault(); return; }
    form.dataset.submitting = 'yes';
    form.setAttribute('aria-busy', 'true');
    window.setTimeout(() => { delete form.dataset.submitting; form.removeAttribute('aria-busy'); }, 15000);
  });
});

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

// Gallery icons: click to copy (photo -> image bytes, video -> link) for pasting into chat.
document.querySelectorAll('.gallery-icon').forEach(function (btn) {
  btn.addEventListener('click', async function () {
    var url = btn.getAttribute('data-copy');
    var kind = btn.getAttribute('data-kind');
    var copied = false;
    async function copyText(text) {
      try { await navigator.clipboard.writeText(text); return true; } catch (e) { return false; }
    }
    if (kind === 'photo') {
      try {
        var resp = await fetch(url);
        var blob = await resp.blob();
        await navigator.clipboard.write([new ClipboardItem({ [blob.type || 'image/png']: blob })]);
        copied = true;
      } catch (e) { copied = false; }
      if (!copied) copied = await copyText(location.origin + url);
    } else {
      copied = await copyText(location.origin + url);
    }
    if (copied) {
      btn.classList.add('copied');
      setTimeout(function () { btn.classList.remove('copied'); }, 1200);
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