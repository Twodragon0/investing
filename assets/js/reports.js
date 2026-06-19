/**
 * Reports Dashboard - Interactive features
 * Extracted from _layouts/reports.html for maintainability
 */
(function() {
  'use strict';

  // === Constants ===
  var BADGE_COLORS = {
    'cat-crypto': ['rgba(247,147,26,0.15)', '#f7931a'],
    'cat-stock': ['rgba(88,166,255,0.15)', '#58a6ff'],
    'cat-journal': ['rgba(63,185,80,0.15)', '#3fb950'],
    'cat-security': ['rgba(248,81,73,0.15)', '#f85149'],
    'cat-analysis': ['rgba(188,140,255,0.15)', '#bc8cff'],
    'cat-regulatory': ['rgba(210,153,34,0.15)', '#d29922'],
    'cat-political': ['rgba(220,20,60,0.15)', '#dc143c'],
    'cat-social': ['rgba(29,161,242,0.15)', '#1da1f2'],
    'cat-worldmonitor': ['rgba(32,178,170,0.15)', '#20b2aa'],
    'cat-blockchain': ['rgba(139,92,246,0.15)', '#8b5cf6'],
    'cat-devops': ['rgba(79,195,247,0.15)', '#4fc3f7']
  };
  var PAGE_SIZE = 24;

  // === State ===
  var currentPage = 1;
  var activeFilter = 'all';
  var searchQuery = '';
  var dateFrom = '';
  var dateTo = '';
  var currentView = 'grid';
  var focusedCardIndex = -1;

  // === DOM refs ===
  var dataEl = document.getElementById('reports-data');
  if (!dataEl) return;
  var posts = JSON.parse(dataEl.textContent);
  var grid = document.getElementById('reports-grid');
  var loadMoreBtn = document.getElementById('load-more-btn');
  var showingEl = document.getElementById('reports-showing');
  var searchInput = document.getElementById('report-search');
  var searchClearBtn = document.getElementById('report-search-clear');
  var dateFromInput = document.getElementById('report-date-from');
  var dateToInput = document.getElementById('report-date-to');
  var clearBtn = document.getElementById('report-clear');
  var filterBtns = document.querySelectorAll('.filter-btn');

  function syncSearchClearVisibility() {
    if (searchClearBtn) searchClearBtn.hidden = searchInput.value.length === 0;
  }

  if (searchClearBtn) {
    searchClearBtn.addEventListener('click', function() {
      searchInput.value = '';
      searchInput.dispatchEvent(new Event('input'));
      searchInput.focus();
    });
  }

  // === Utilities ===
  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function highlightText(html) {
    if (!searchQuery || searchQuery.length < 2) return html;
    var escapedQuery = escapeHtml(searchQuery).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return html.replace(new RegExp('(' + escapedQuery + ')', 'gi'), function(_, m) {
      return '<mark class="search-highlight">' + m + '</mark>';
    });
  }

  function relativeTime(dateStr) {
    var now = new Date();
    var d = new Date(dateStr + 'T00:00:00');
    var diff = Math.floor((now - d) / (1000 * 60 * 60));
    if (diff < 1) return '방금 전';
    if (diff < 24) return diff + '시간 전';
    var days = Math.floor(diff / 24);
    if (days === 0) return '오늘';
    if (days === 1) return '어제';
    if (days < 7) return days + '일 전';
    if (days < 30) return Math.floor(days / 7) + '주 전';
    return Math.floor(days / 30) + '개월 전';
  }

  // === Bookmarks ===
  var bookmarks = JSON.parse(localStorage.getItem('report-bookmarks') || '{}');
  function isBookmarked(url) { return !!bookmarks[url]; }
  function getBookmarkCount() { return Object.keys(bookmarks).length; }
  function updateBookmarkBadge() {
    var badge = document.getElementById('bookmark-count');
    var count = getBookmarkCount();
    if (badge) { badge.textContent = count; badge.style.display = count > 0 ? '' : 'none'; }
  }
  function toggleBookmark(url, btn) {
    if (bookmarks[url]) { delete bookmarks[url]; btn.classList.remove('bookmarked'); }
    else { bookmarks[url] = 1; btn.classList.add('bookmarked'); }
    localStorage.setItem('report-bookmarks', JSON.stringify(bookmarks));
    updateBookmarkBadge();
  }

  // === Card Builder ===
  function buildCard(p) {
    var thumbHtml = '';
    if (p.img) {
      thumbHtml = '<div class="report-card-thumb"><img src="' + escapeHtml(p.img) + '" alt="" loading="lazy" onerror="this.closest(\'.report-card-thumb\').remove()"></div>';
    }
    var tagsHtml = '';
    if (p.tags && p.tags.length) {
      tagsHtml = '<div class="report-tags">' + p.tags.map(function(t) {
        return '<span class="report-tag">' + escapeHtml(t) + '</span>';
      }).join('') + '</div>';
    }
    var bc = BADGE_COLORS[p.cc] || ['rgba(88,166,255,0.15)', '#58a6ff'];
    var bmClass = isBookmarked(p.u) ? ' bookmarked' : '';
    return '<a href="' + escapeHtml(p.u) + '" class="report-card report-card-visible" role="article" aria-label="' + escapeHtml(p.t) + '">' +
      '<button class="report-bookmark' + bmClass + '" data-url="' + escapeHtml(p.u) + '" title="즐겨찾기"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" stroke="none"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg></button>' +
      thumbHtml +
      '<div class="report-card-body">' +
      '<div class="report-card-header">' +
      '<span class="report-category-badge" style="background:' + bc[0] + ';color:' + bc[1] + '">' + highlightText(escapeHtml(p.cn)) + '</span>' +
      '<time class="report-date-label">' + escapeHtml(p.dm) + '</time>' +
      '<span class="report-relative-time">' + relativeTime(p.d) + '</span>' +
      '</div>' +
      '<h3 class="report-title">' + highlightText(escapeHtml(p.t)) + '</h3>' +
      '<p class="report-summary">' + highlightText(escapeHtml(p.s)) + '</p>' +
      tagsHtml +
      '<div class="report-card-footer">' +
      '<span class="report-read-more">자세히 보기 <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></span>' +
      '<span class="report-share" data-url="' + escapeHtml(p.u) + '" data-title="' + escapeHtml(p.t) + '">' +
      '<button class="share-btn" data-action="copy" title="링크 복사"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>' +
      '<button class="share-btn" data-action="twitter" title="Twitter"><svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></button>' +
      '<button class="share-btn" data-action="telegram" title="Telegram"><svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0h-.056zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg></button>' +
      '</span>' +
      '</div></div></a>';
  }

  // === Filtering & Rendering ===
  function getFiltered() {
    return posts.filter(function(p) {
      if (activeFilter === '_bookmarks' && !isBookmarked(p.u)) return false;
      if (activeFilter !== 'all' && activeFilter !== '_bookmarks' && p.c !== activeFilter) return false;
      if (searchQuery) {
        var t = p.t.toLowerCase();
        var s = (p.s || '').toLowerCase();
        var cn = (p.cn || '').toLowerCase();
        if (t.indexOf(searchQuery) === -1 && s.indexOf(searchQuery) === -1 && cn.indexOf(searchQuery) === -1) return false;
      }
      if (dateFrom && p.d < dateFrom) return false;
      if (dateTo && p.d > dateTo) return false;
      return true;
    });
  }

  function render() {
    var filtered = getFiltered();
    var visible = currentPage * PAGE_SIZE;
    var showing = filtered.slice(0, visible);
    grid.innerHTML = showing.map(buildCard).join('');
    loadMoreBtn.style.display = visible >= filtered.length ? 'none' : '';
    showingEl.textContent = showing.length + ' / ' + filtered.length + '건';
  }

  // === Event Listeners ===
  filterBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      filterBtns.forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      currentPage = 1;
      render();
    });
  });

  function syncReportUrlQuery() {
    try {
      var url = new URL(window.location.href);
      if (searchInput.value) url.searchParams.set('q', searchInput.value);
      else url.searchParams.delete('q');
      window.history.replaceState(null, '', url.toString());
    } catch (_) {}
  }

  var _searchTimer;
  searchInput.addEventListener('input', function() {
    syncSearchClearVisibility();
    syncReportUrlQuery();
    var val = this.value.toLowerCase().trim();
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(function() {
      searchQuery = val;
      currentPage = 1;
      render();
    }, 300);
  });

  searchInput.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && searchInput.value) {
      e.preventDefault();
      e.stopPropagation();
      searchInput.value = '';
      searchInput.dispatchEvent(new Event('input'));
    }
  });

  dateFromInput.addEventListener('change', function() { dateFrom = this.value; currentPage = 1; render(); });
  dateToInput.addEventListener('change', function() { dateTo = this.value; currentPage = 1; render(); });

  clearBtn.addEventListener('click', function() {
    searchInput.value = '';
    dateFromInput.value = '';
    dateToInput.value = '';
    searchQuery = ''; dateFrom = ''; dateTo = '';
    filterBtns.forEach(function(b) { b.classList.remove('active'); });
    filterBtns[0].classList.add('active');
    activeFilter = 'all';
    currentPage = 1;
    syncSearchClearVisibility();
    syncReportUrlQuery();
    render();
  });

  loadMoreBtn.addEventListener('click', function() { currentPage++; render(); });

  // === Infinite Scroll ===
  if ('IntersectionObserver' in window) {
    var sentinel = document.createElement('div');
    sentinel.id = 'scroll-sentinel';
    sentinel.style.height = '1px';
    document.getElementById('reports-load-more').appendChild(sentinel);
    var observer = new IntersectionObserver(function(entries) {
      if (entries[0].isIntersecting && loadMoreBtn.style.display !== 'none') {
        currentPage++;
        render();
      }
    }, { rootMargin: '200px' });
    observer.observe(sentinel);
  }

  // === Keyboard Navigation ===
  document.addEventListener('keydown', function(e) {
    if (e.key === '/') {
      var active = document.activeElement;
      if (active) {
        var tag = active.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || active.isContentEditable) return;
      }
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
      return;
    }
    var cards = grid.querySelectorAll('.report-card');
    if (!cards.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
      e.preventDefault();
      focusedCardIndex = Math.min(focusedCardIndex + 1, cards.length - 1);
      cards[focusedCardIndex].focus();
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
      e.preventDefault();
      focusedCardIndex = Math.max(focusedCardIndex - 1, 0);
      cards[focusedCardIndex].focus();
    } else if (e.key === 'Escape') {
      document.activeElement.blur();
      focusedCardIndex = -1;
    }
  });

  // Restore from ?q= on load
  (function restoreReportFromUrl() {
    try {
      var initial = new URL(window.location.href).searchParams.get('q');
      if (initial) {
        searchInput.value = initial;
        syncSearchClearVisibility();
        setTimeout(function() { searchInput.dispatchEvent(new Event('input')); }, 0);
      }
    } catch (_) {}
  })();

  updateBookmarkBadge();

  // === View Toggle ===
  var viewBtns = document.querySelectorAll('.report-view-btn');
  viewBtns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      viewBtns.forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      currentView = btn.dataset.view;
      grid.classList.toggle('reports-list-view', currentView === 'list');
    });
  });

  // === Recently Viewed ===
  var recentHistory = JSON.parse(localStorage.getItem('report-recent') || '[]');
  function renderRecent() {
    if (!recentHistory.length) return;
    var container = document.getElementById('reports-recent');
    var list = document.getElementById('recent-list');
    if (!container || !list) return;
    var recentPosts = recentHistory.slice(0, 5).map(function(url) {
      return posts.find(function(p) { return p.u === url; });
    }).filter(Boolean);
    if (!recentPosts.length) return;
    container.style.display = '';
    list.innerHTML = recentPosts.map(function(p) {
      var bc = BADGE_COLORS[p.cc] || ['rgba(88,166,255,0.15)','#58a6ff'];
      return '<a href="' + escapeHtml(p.u) + '" class="recent-item">' +
        '<span class="report-category-badge" style="background:' + escapeHtml(bc[0]) + ';color:' + escapeHtml(bc[1]) + '">' + escapeHtml(p.cn) + '</span>' +
        '<span class="recent-item-title">' + escapeHtml(p.t) + '</span>' +
        '<span class="report-relative-time">' + relativeTime(p.d) + '</span></a>';
    }).join('');
  }
  grid.addEventListener('click', function(e) {
    var card = e.target.closest('.report-card');
    if (card && !e.target.closest('.report-bookmark') && !e.target.closest('.share-btn')) {
      var url = card.getAttribute('href');
      if (url) {
        recentHistory = recentHistory.filter(function(u) { return u !== url; });
        recentHistory.unshift(url);
        recentHistory = recentHistory.slice(0, 20);
        localStorage.setItem('report-recent', JSON.stringify(recentHistory));
      }
    }
  });
  renderRecent();

  // === Bookmark + Share Delegation ===
  grid.addEventListener('click', function(e) {
    var btn = e.target.closest('.report-bookmark');
    if (btn) {
      e.preventDefault();
      e.stopPropagation();
      toggleBookmark(btn.dataset.url, btn);
      if (activeFilter === '_bookmarks') render();
      return;
    }
    var shareBtn = e.target.closest('.share-btn');
    if (shareBtn) {
      e.preventDefault();
      e.stopPropagation();
      var wrap = shareBtn.closest('.report-share');
      var url = location.origin + wrap.dataset.url;
      var title = wrap.dataset.title;
      var action = shareBtn.dataset.action;
      if (action === 'copy') {
        navigator.clipboard.writeText(url).then(function() {
          shareBtn.title = '복사됨!';
          setTimeout(function() { shareBtn.title = '링크 복사'; }, 1500);
        });
      } else if (action === 'twitter') {
        window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(title) + '&url=' + encodeURIComponent(url), '_blank', 'width=550,height=420');
      } else if (action === 'telegram') {
        window.open('https://t.me/share/url?url=' + encodeURIComponent(url) + '&text=' + encodeURIComponent(title), '_blank', 'width=550,height=420');
      }
    }
  });

  // === Today's Highlights ===
  (function() {
    var today = new Date().toISOString().slice(0, 10);
    var todayPosts = posts.filter(function(p) { return p.d === today; });
    if (todayPosts.length === 0) return;
    var hlContainer = document.getElementById('reports-highlights');
    var hlGrid = document.getElementById('highlights-grid');
    if (!hlContainer || !hlGrid) return;
    hlContainer.style.display = '';
    var shown = todayPosts.slice(0, 6);
    hlGrid.innerHTML = shown.map(function(p) {
      var bc = BADGE_COLORS[p.cc] || ['rgba(88,166,255,0.15)', '#58a6ff'];
      var thumbHtml = p.img ? '<img class="highlight-thumb" src="' + escapeHtml(p.img) + '" alt="" loading="lazy" onerror="this.remove()">' : '';
      return '<a href="' + escapeHtml(p.u) + '" class="highlight-card">' +
        thumbHtml +
        '<div class="highlight-body">' +
        '<span class="report-category-badge" style="background:' + escapeHtml(bc[0]) + ';color:' + escapeHtml(bc[1]) + '">' + escapeHtml(p.cn) + '</span>' +
        '<h4 class="highlight-title">' + escapeHtml(p.t) + '</h4>' +
        '<p class="highlight-summary">' + escapeHtml((p.s || '').slice(0, 80)) + '</p>' +
        '</div></a>';
    }).join('');
  })();

  // === Hash-based Filter ===
  function applyHash() {
    var hash = location.hash.replace('#', '');
    if (!hash) return;
    var matched = false;
    filterBtns.forEach(function(btn) {
      if (btn.dataset.filter === hash) {
        filterBtns.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        activeFilter = hash;
        matched = true;
      }
    });
    if (matched) { currentPage = 1; render(); }
  }

  function updateHash() {
    var h = activeFilter === 'all' ? '' : '#' + activeFilter;
    history.replaceState(null, '', location.pathname + h);
  }

  filterBtns.forEach(function(btn) { btn.addEventListener('click', updateHash); });
  window.addEventListener('hashchange', function() { applyHash(); });
  applyHash();
  if (activeFilter === 'all') render();

  // === Charts ===
  function initCharts() {
    if (typeof Chart === 'undefined') return;

    var isDark = !document.documentElement.getAttribute('data-theme') ||
                  document.documentElement.getAttribute('data-theme') === 'dark';
    var textColor = isDark ? '#7d8fa8' : '#59636e';
    var gridColor = isDark ? 'rgba(36,48,68,0.6)' : 'rgba(208,215,222,0.5)';

    Chart.defaults.color = textColor;
    Chart.defaults.font.family = "'Noto Sans KR', sans-serif";

    // Category distribution doughnut
    var catCounts = {};
    posts.forEach(function(p) { catCounts[p.cn] = (catCounts[p.cn] || 0) + 1; });
    var catLabels = Object.keys(catCounts).sort(function(a, b) { return catCounts[b] - catCounts[a]; });
    var catValues = catLabels.map(function(l) { return catCounts[l]; });
    var catColors = ['#f7931a','#58a6ff','#3fb950','#f85149','#bc8cff','#d29922','#dc143c','#1da1f2','#20b2aa','#8b5cf6','#4fc3f7'];

    new Chart(document.getElementById('category-chart'), {
      type: 'doughnut',
      data: {
        labels: catLabels,
        datasets: [{ data: catValues, backgroundColor: catColors.slice(0, catLabels.length), borderWidth: 0, hoverOffset: 6 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '55%',
        plugins: { legend: { position: 'right', labels: { boxWidth: 12, padding: 8, font: { size: 11 } } } }
      }
    });

    // Daily stacked bar chart (30 days)
    var dayDates = [];
    var now = new Date();
    for (var i = 29; i >= 0; i--) {
      var d = new Date(now);
      d.setDate(d.getDate() - i);
      dayDates.push(d.toISOString().slice(0, 10));
    }
    var shortLabels = dayDates.map(function(k) { return k.slice(5); });
    var catColorMap = {
      'cat-crypto': '#f7931a', 'cat-stock': '#58a6ff', 'cat-journal': '#3fb950',
      'cat-security': '#f85149', 'cat-analysis': '#bc8cff', 'cat-regulatory': '#d29922',
      'cat-political': '#dc143c', 'cat-social': '#1da1f2', 'cat-worldmonitor': '#20b2aa',
      'cat-blockchain': '#8b5cf6', 'cat-devops': '#4fc3f7'
    };
    var catDayCounts = {};
    posts.forEach(function(p) {
      if (dayDates.indexOf(p.d) === -1) return;
      if (!catDayCounts[p.cn]) { catDayCounts[p.cn] = { cc: p.cc, counts: {} }; }
      catDayCounts[p.cn].counts[p.d] = (catDayCounts[p.cn].counts[p.d] || 0) + 1;
    });
    var stackDatasets = Object.keys(catDayCounts).map(function(cn) {
      var info = catDayCounts[cn];
      var color = catColorMap[info.cc] || '#58a6ff';
      return {
        label: cn,
        data: dayDates.map(function(d) { return info.counts[d] || 0; }),
        backgroundColor: color + 'aa', borderColor: color, borderWidth: 1, borderRadius: 2, barPercentage: 0.8
      };
    });

    new Chart(document.getElementById('daily-chart'), {
      type: 'bar',
      data: { labels: shortLabels, datasets: stackDatasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 45, font: { size: 9 }, maxTicksLimit: 15 } },
          y: { stacked: true, beginAtZero: true, grid: { color: gridColor }, ticks: { stepSize: 2, font: { size: 10 } } }
        },
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 10, padding: 6, font: { size: 9 } } },
          tooltip: { mode: 'index', intersect: false }
        }
      }
    });
  }

  // Theme sync: destroy and re-create charts
  var chartInstances = [];
  var _origInitCharts = initCharts;
  initCharts = function() {
    chartInstances.forEach(function(c) { c.destroy(); });
    chartInstances = [];
    _origInitCharts();
    if (typeof Chart !== 'undefined' && Chart.instances) {
      Object.values(Chart.instances).forEach(function(c) { chartInstances.push(c); });
    }
  };

  if (typeof Chart !== 'undefined') {
    initCharts();
  } else {
    window.addEventListener('chartjs-ready', initCharts);
  }

  var themeObserver = new MutationObserver(function(mutations) {
    mutations.forEach(function(m) {
      if (m.attributeName === 'data-theme' && typeof Chart !== 'undefined') {
        initCharts();
      }
    });
  });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  // === Notification Subscription ===
  var notifyBtn = document.getElementById('report-notify-btn');
  if (notifyBtn && 'Notification' in window) {
    var isSubscribed = localStorage.getItem('report-notify') === 'on';
    function updateNotifyBtn() {
      var label = notifyBtn.querySelector('[data-i18n]');
      if (isSubscribed) {
        notifyBtn.classList.add('notify-active');
        if (label) label.textContent = label.getAttribute('data-i18n') === 'reports_notify' ? '알림 켜짐' : label.textContent;
      } else {
        notifyBtn.classList.remove('notify-active');
      }
    }
    updateNotifyBtn();

    // Check for new posts since last visit
    if (isSubscribed) {
      var lastSeen = localStorage.getItem('report-last-seen') || '';
      var newest = posts.length ? posts[0].d : '';
      if (lastSeen && newest > lastSeen && Notification.permission === 'granted') {
        var newCount = posts.filter(function(p) { return p.d > lastSeen; }).length;
        if (newCount > 0) {
          new Notification('Investing Dragon', {
            body: newCount + '건의 새 리포트가 발행되었습니다.',
            icon: '/assets/images/favicon-192.png',
            tag: 'new-reports'
          });
        }
      }
      if (newest) localStorage.setItem('report-last-seen', newest);
    }

    notifyBtn.addEventListener('click', function() {
      if (isSubscribed) {
        isSubscribed = false;
        localStorage.setItem('report-notify', 'off');
        updateNotifyBtn();
        return;
      }
      Notification.requestPermission().then(function(perm) {
        if (perm === 'granted') {
          isSubscribed = true;
          localStorage.setItem('report-notify', 'on');
          var newest = posts.length ? posts[0].d : '';
          if (newest) localStorage.setItem('report-last-seen', newest);
          updateNotifyBtn();
          new Notification('Investing Dragon', {
            body: '리포트 알림이 활성화되었습니다.',
            icon: '/assets/images/favicon-192.png'
          });
        }
      });
    });
  } else if (notifyBtn) {
    notifyBtn.style.display = 'none';
  }
})();
