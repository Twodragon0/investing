// QRCode footer initialization
document.addEventListener('DOMContentLoaded', function() {
  var el = document.getElementById('footer-qrcode');
  if (!el) return;
  function tryInit() {
    if (typeof QRCode !== 'undefined') {
      new QRCode(el, {
        text: window.__siteUrl || el.getAttribute('data-url') || window.location.origin,
        width: 120,
        height: 120,
        colorDark: '#0a0e14',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.M
      });
    } else {
      setTimeout(tryInit, 100);
    }
  }
  tryInit();
});

// Mermaid.js diagram setup
(function() {
  var mermaids = document.querySelectorAll('.language-mermaid, pre code.language-mermaid');
  if (!mermaids.length) return;
  mermaids.forEach(function(el) {
    var pre = el.closest('pre');
    var container = document.createElement('div');
    container.className = 'mermaid';
    container.textContent = el.textContent;
    if (pre) { pre.parentNode.replaceChild(container, pre); }
    else { el.parentNode.replaceChild(container, el); }
  });
  var script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js';
  script.integrity = 'sha384-rbtjAdnIQE/aQJGEgXrVUlMibdfTSa4PQju4HDhN3sR2PmaKFzhEafuePsl9H/9I';
  script.crossOrigin = 'anonymous';
  script.onload = function() {
    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    mermaid.initialize({ startOnLoad: true, theme: isDark ? 'dark' : 'default', securityLevel: 'strict' });
  };
  document.head.appendChild(script);
})();
