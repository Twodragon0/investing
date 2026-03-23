// Post page interactions: TOC, reading progress, image handling, lightbox, tables, share
(function() {
  // TOC generation
  var headings = document.querySelectorAll('.post-content h2');
  var toc = document.getElementById('post-toc');
  var tocList = document.getElementById('toc-list');
  if (!toc || !tocList || headings.length < 2) {
    if (toc) toc.style.display = 'none';
  } else {
    headings.forEach(function(h, i) {
      var id = 'section-' + i;
      h.setAttribute('id', id);
      var li = document.createElement('li');
      var a = document.createElement('a');
      a.href = '#' + id;
      a.textContent = h.textContent;
      a.setAttribute('data-index', i);
      li.appendChild(a);
      tocList.appendChild(li);
    });
    if ('IntersectionObserver' in window) {
      var observer = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
          if (entry.isIntersecting) {
            var id = entry.target.getAttribute('id');
            tocList.querySelectorAll('a').forEach(function(a) { a.classList.remove('active'); });
            var active = tocList.querySelector('a[href="#' + id + '"]');
            if (active) active.classList.add('active');
          }
        });
      }, { rootMargin: '-80px 0px -60% 0px', threshold: 0 });
      headings.forEach(function(h) { observer.observe(h); });
    }
  }

  // Reading progress
  var progressBar = document.getElementById('reading-progress');
  var article = document.querySelector('.post-detail');
  if (progressBar && article) {
    function updateProgress() {
      var articleTop = article.offsetTop;
      var articleHeight = article.offsetHeight - window.innerHeight;
      if (articleHeight <= 0) {
        progressBar.style.width = '0%';
        return;
      }
      var scrolled = window.scrollY - articleTop;
      var progress = Math.min(100, Math.max(0, (scrolled / articleHeight) * 100));
      progressBar.style.width = progress + '%';
    }

    var firstParagraph = document.querySelector('.post-content.prose-content > p');
    if (firstParagraph && firstParagraph.textContent.trim().length > 80) {
      firstParagraph.classList.add('post-lead');
    }

    window.addEventListener('scroll', updateProgress, { passive: true });
    window.addEventListener('resize', updateProgress);
    updateProgress();
  }

  // Image handling
  var images = document.querySelectorAll('.post-content.prose-content img');
  if (images.length) {
    function toCaption(text) {
      text = String(text || '').trim();
      if (!text) return '';
      if (/^(top-coins|market-heatmap|fear-greed|news-briefing|source-dist|defi-tvl)/i.test(text)) return '';
      return text.replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim();
    }

    function wrapImage(img) {
      if (img.closest('figure')) return;
      var figure = document.createElement('figure');
      figure.className = 'post-figure';
      var target = img.closest('picture') || img;
      target.parentNode.insertBefore(figure, target);
      figure.appendChild(target);
      var alt = toCaption(img.getAttribute('alt'));
      if (alt) {
        var caption = document.createElement('figcaption');
        caption.textContent = alt;
        figure.appendChild(caption);
      }
    }

    function fallbackSrc(src) {
      var ext = src.indexOf('.webp') !== -1 ? '.webp' : '.png';
      var normSrc = src.replace('.webp', '.png');
      var dailyPattern = /news-briefing-daily-(\d{4}-\d{2}-\d{2})\.png/;
      var matched = normSrc.match(dailyPattern);
      if (matched) {
        return normSrc.replace('news-briefing-daily-' + matched[1] + '.png', 'news-briefing-' + matched[1] + '.png');
      }
      var datePattern = /(top-coins|market-heatmap|fear-greed|market-snapshot|news-summary|source-distribution|defi-tvl-dashboard|news-briefing)(?:-(?:cmc|coingecko))?-\d{4}-\d{2}-\d{2}\.png/;
      if (datePattern.test(normSrc)) {
        var catMatch = document.querySelector('meta[property="article:section"]');
        if (catMatch) {
          var cat = catMatch.getAttribute('content');
          var baseUrl = document.querySelector('.post-detail') ? document.querySelector('.post-detail').dataset.baseUrl || '/' : '/';
          return baseUrl + 'assets/images/og-' + (cat || 'default') + '.png';
        }
      }
      return '';
    }

    function attachFallback(img) {
      img.loading = 'lazy';
      img.decoding = 'async';
      img.addEventListener('error', function() {
        if (img.dataset.fallbackTried !== '1') {
          var nextSrc = fallbackSrc(img.currentSrc || img.src || '');
          if (nextSrc) {
            img.dataset.fallbackTried = '1';
            img.src = nextSrc;
            return;
          }
        }
        img.classList.add('broken-image');
        if (!img.nextElementSibling || !img.nextElementSibling.classList.contains('post-image-placeholder')) {
          var holder = document.createElement('div');
          holder.className = 'post-image-placeholder';
          holder.textContent = (typeof window.__t === 'function') ? window.__t('image_error') : '이미지를 불러오지 못했습니다.';
          img.insertAdjacentElement('afterend', holder);
        }
      }, { once: true });
    }

    images.forEach(function(img) {
      wrapImage(img);
      attachFallback(img);
    });
  }

  // Image lightbox
  var overlay = document.createElement('div');
  overlay.className = 'lightbox-overlay';
  var lbImg = document.createElement('img');
  lbImg.className = 'lightbox-img';
  var lbClose = document.createElement('button');
  lbClose.className = 'lightbox-close';
  lbClose.setAttribute('aria-label', (typeof window.__t === 'function') ? window.__t('close_label') : '닫기');
  lbClose.textContent = '\u00D7';
  overlay.appendChild(lbImg);
  overlay.appendChild(lbClose);
  document.body.appendChild(overlay);

  document.querySelectorAll('.post-content.prose-content img').forEach(function(img) {
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', function(e) {
      e.preventDefault();
      lbImg.src = img.src;
      lbImg.alt = img.alt || '';
      overlay.classList.add('active');
      document.body.style.overflow = 'hidden';
    });
  });

  function closeLightbox() {
    overlay.classList.remove('active');
    document.body.style.overflow = '';
  }

  lbClose.addEventListener('click', closeLightbox);
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) closeLightbox();
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeLightbox();
  });

  // Table scroll wrappers
  var tables = document.querySelectorAll('.post-content.prose-content table');
  tables.forEach(function(table) {
    var parent = table.parentElement;
    if (parent && parent.classList.contains('table-wrap')) return;
    var wrap = document.createElement('div');
    wrap.className = 'table-wrap';
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);

    var btnLeft = document.createElement('button');
    btnLeft.className = 'table-scroll-btn table-scroll-btn-left';
    btnLeft.setAttribute('aria-label', '왼쪽으로 스크롤');
    btnLeft.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>';
    wrap.appendChild(btnLeft);

    var btnRight = document.createElement('button');
    btnRight.className = 'table-scroll-btn table-scroll-btn-right';
    btnRight.setAttribute('aria-label', '오른쪽으로 스크롤');
    btnRight.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';
    wrap.appendChild(btnRight);

    btnLeft.addEventListener('click', function() {
      wrap.scrollBy({ left: -200, behavior: 'smooth' });
    });
    btnRight.addEventListener('click', function() {
      wrap.scrollBy({ left: 200, behavior: 'smooth' });
    });

    function update() {
      var scrollable = table.scrollWidth > wrap.clientWidth + 4;
      wrap.classList.toggle('is-scrollable', scrollable);
      if (scrollable) {
        var atStart = wrap.scrollLeft <= 2;
        var atEnd = wrap.scrollLeft + wrap.clientWidth >= wrap.scrollWidth - 2;
        wrap.classList.toggle('scrolled-start', atStart);
        wrap.classList.toggle('scrolled-end', atEnd);
        if (!wrap.querySelector('.scroll-hint')) {
          var hint = document.createElement('span');
          hint.className = 'scroll-hint';
          hint.textContent = (typeof window.__t === 'function') ? window.__t('scroll_hint') : '\u2190 \uC2A4\uD06C\uB864 \u2192';
          wrap.appendChild(hint);
        }
      } else {
        wrap.classList.remove('scrolled-end', 'scrolled-start');
        var existingHint = wrap.querySelector('.scroll-hint');
        if (existingHint) existingHint.remove();
      }
    }

    wrap.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    update();
  });

  // TOC toggle
  var tocHeader = document.getElementById('toc-header');
  if (tocHeader) {
    tocHeader.addEventListener('click', function() {
      var toc = document.getElementById('post-toc');
      if (toc) toc.classList.toggle('collapsed');
    });
  }

  // Share buttons
  var shareTwitterBtn = document.getElementById('share-twitter');
  if (shareTwitterBtn) {
    shareTwitterBtn.addEventListener('click', function() {
      var postDetail = document.querySelector('.post-detail');
      var text = postDetail ? postDetail.dataset.postTitle : document.title;
      var url = window.location.href;
      window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(text) + '&url=' + encodeURIComponent(url), '_blank', 'width=550,height=450');
    });
  }

  var shareCopyBtn = document.getElementById('share-copy');
  if (shareCopyBtn) {
    shareCopyBtn.addEventListener('click', function() {
      var url = window.location.href;
      navigator.clipboard.writeText(url).then(function() {
        var btn = document.querySelector('.share-copy');
        if (!btn) return;
        var originalHTML = btn.innerHTML;
        btn.textContent = '';
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '16'); svg.setAttribute('height', '16');
        svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2');
        var poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        poly.setAttribute('points', '20 6 9 17 4 12');
        svg.appendChild(poly); btn.appendChild(svg);
        var copiedText = (typeof window.__t === 'function') ? window.__t('copied') : '복사됨!';
        btn.appendChild(document.createTextNode(' ' + copiedText));
        setTimeout(function() { btn.innerHTML = originalHTML; }, 2000);
      }).catch(function() {
        var promptText = (typeof window.__t === 'function') ? window.__t('copy_prompt') : '링크를 복사하세요:';
        window.prompt(promptText, url);
      });
    });
  }
})();
