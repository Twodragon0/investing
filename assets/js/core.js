// Vercel Analytics stub
window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };

// Vercel Speed Insights stub
window.si = window.si || function () { (window.siq = window.siq || []).push(arguments); };

// Theme toggle
(function() {
  var toggle = document.getElementById('theme-toggle');
  if (!toggle) return;
  var metaColor = document.getElementById('meta-theme-color');

  function getTheme() {
    var saved = localStorage.getItem('theme');
    if (saved) return saved;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  function applyTheme(theme) {
    if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
      if (metaColor) metaColor.setAttribute('content', '#ffffff');
    } else {
      document.documentElement.removeAttribute('data-theme');
      if (metaColor) metaColor.setAttribute('content', '#0a0e14');
    }
  }

  toggle.addEventListener('click', function() {
    var current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    var next = current === 'light' ? 'dark' : 'light';
    localStorage.setItem('theme', next);
    applyTheme(next);
  });

  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function(e) {
    if (!localStorage.getItem('theme')) {
      applyTheme(e.matches ? 'light' : 'dark');
    }
  });
})();

// Reading progress bar
(function() {
  var bar = document.getElementById('reading-progress');
  if (!bar || !document.querySelector('.post-detail')) {
    if (bar) bar.style.display = 'none';
    return;
  }
  window.addEventListener('scroll', function() {
    var h = document.documentElement.scrollHeight - window.innerHeight;
    if (h > 0) bar.style.width = (window.scrollY / h * 100) + '%';
  }, { passive: true });
})();

// External links → new tab
(function() {
  var host = location.hostname;
  document.querySelectorAll('main a[href^="http"]').forEach(function(a) {
    if (a.hostname !== host) {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    }
  });
})();

// Lazy load post content images
document.querySelectorAll('main img:not([loading])').forEach(function(img) {
  img.loading = 'lazy';
});
