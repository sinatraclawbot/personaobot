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