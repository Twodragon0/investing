---
layout: default
title: "검색"
permalink: /search/
description: "Investing Dragon 사이트 내 검색 — 암호화폐, 주식, 시장 분석 게시물을 빠르게 찾아보세요."
sitemap: false
---

<style>
  .search-page-form { display: flex; gap: 8px; margin: 1rem 0 1.5rem; }
  .search-page-input-wrap { position: relative; flex: 1; display: flex; }
  .search-page-form input { flex: 1; width: 100%; padding: 0.6rem 2.6rem 0.6rem 0.8rem; font-size: 16px; border-radius: 6px; border: 1px solid var(--border, #444); background: var(--bg, transparent); color: inherit; }
  .search-page-form input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
  .search-page-form button[type="submit"] { padding: 0.6rem 1rem; border-radius: 6px; border: 1px solid var(--border, #444); background: var(--accent, #2c5282); color: #fff; cursor: pointer; }
  .search-page-clear { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; padding: 0; border: 1px solid transparent; border-radius: 6px; background: transparent; color: inherit; opacity: 0.6; cursor: pointer; transition: background-color .15s, opacity .15s, border-color .15s; }
  .search-page-clear:hover { opacity: 1; background: rgba(255,255,255,.08); }
  .search-page-clear:focus-visible { outline: none; opacity: 1; border-color: var(--accent, #2c5282); box-shadow: 0 0 0 3px rgba(44, 82, 130, 0.25); }
  .search-page-clear[hidden] { display: none; }
  .search-page-clear svg { width: 14px; height: 14px; pointer-events: none; }
  #search-page-results { margin-top: 1rem; }
  #search-page-results .item { display: block; padding: 0.75rem 0.5rem; border-bottom: 1px solid var(--border, rgba(255,255,255,.08)); color: inherit; text-decoration: none; }
  #search-page-results .item:hover { background: rgba(255,255,255,.04); }
  #search-page-results .title { font-weight: 600; margin-bottom: 0.25rem; }
  #search-page-results .meta { font-size: 0.85rem; opacity: 0.7; }
  #search-page-results mark { background: rgba(255, 215, 0, 0.3); color: inherit; padding: 0 2px; }
  #search-page-status { margin-top: 0.5rem; opacity: 0.75; font-size: 0.9rem; }
</style>

# 검색

<form class="search-page-form" id="search-page-form" role="search">
  <label for="search-page-input" class="visually-hidden">검색어</label>
  <div class="search-page-input-wrap">
    <input
      type="search"
      id="search-page-input"
      name="q"
      placeholder="검색어를 입력하세요…"
      autocomplete="off"
      spellcheck="false"
      enterkeyhint="search"
      autofocus
    >
    <button type="button" class="search-page-clear" id="search-page-clear" aria-label="검색어 지우기" data-i18n-aria="category_search_clear" hidden>
      <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>
  </div>
  <button type="submit">검색</button>
</form>

<div id="search-page-status" aria-live="polite"></div>
<div id="search-page-results" role="list"></div>

<script>
(function() {
  var input = document.getElementById('search-page-input');
  var form = document.getElementById('search-page-form');
  var results = document.getElementById('search-page-results');
  var status = document.getElementById('search-page-status');
  var clearBtn = document.getElementById('search-page-clear');
  var posts = null;

  function syncClearVisibility() {
    if (clearBtn) clearBtn.hidden = input.value.length === 0;
  }

  function clearSearch() {
    input.value = '';
    syncClearVisibility();
    results.innerHTML = '';
    status.textContent = '';
    var url = new URL(window.location.href);
    url.searchParams.delete('q');
    window.history.replaceState(null, '', url.toString());
    input.focus();
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', clearSearch);
  }

  input.addEventListener('input', syncClearVisibility);

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && input.value) {
      e.preventDefault();
      clearSearch();
    }
  });

  document.addEventListener('keydown', function(e) {
    if (e.key !== '/') return;
    var active = document.activeElement;
    if (active) {
      var tag = active.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || active.isContentEditable) return;
    }
    e.preventDefault();
    input.focus();
    input.select();
  });

  function getQueryParam() {
    var m = window.location.search.match(/[?&]q=([^&]*)/);
    return m ? decodeURIComponent(m[1].replace(/\+/g, ' ')) : '';
  }

  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }

  function highlight(text, q) {
    if (!text || !q) return escapeHtml(text || '');
    var safe = escapeHtml(text);
    var re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    return safe.replace(re, '<mark>$1</mark>');
  }

  function score(post, q) {
    var s = 0;
    var title = (post.title || '').toLowerCase();
    var tags = (post.tags || '').toLowerCase();
    var cats = (post.categories || '').toLowerCase();
    var ex = (post.excerpt || '').toLowerCase();
    var co = (post.content || '').toLowerCase();
    if (title === q) s += 100;
    else if (title.indexOf(q) === 0) s += 80;
    else if (title.indexOf(q) !== -1) s += 60;
    if (tags.indexOf(q) !== -1) s += 40;
    if (cats.indexOf(q) !== -1) s += 30;
    if (ex.indexOf(q) !== -1) s += 20;
    if (co.indexOf(q) !== -1) s += 10;
    return s;
  }

  function render(query, scored) {
    results.innerHTML = '';
    if (!scored.length) {
      status.textContent = '"' + query + '"에 대한 결과가 없습니다.';
      return;
    }
    status.textContent = scored.length + (scored.length >= 30 ? '+' : '') + '개의 결과';
    var max = Math.min(scored.length, 30);
    for (var i = 0; i < max; i++) {
      var p = scored[i].post;
      var a = document.createElement('a');
      a.className = 'item';
      a.setAttribute('role', 'listitem');
      a.href = p.url;
      a.innerHTML =
        '<div class="title">' + highlight(p.title || '(제목 없음)', query) + '</div>' +
        '<div class="meta">' + escapeHtml(p.date || '') +
          (p.categories ? ' · ' + escapeHtml(p.categories) : '') +
        '</div>';
      results.appendChild(a);
    }
  }

  function search(query) {
    if (!query || query.length < 2) {
      results.innerHTML = '';
      status.textContent = '검색어는 2글자 이상 입력해주세요.';
      return;
    }
    if (!posts) {
      status.textContent = '검색 인덱스를 불러오는 중…';
      return;
    }
    var q = query.toLowerCase();
    var scored = [];
    for (var i = 0; i < posts.length; i++) {
      var s = score(posts[i], q);
      if (s > 0) scored.push({ post: posts[i], score: s });
    }
    scored.sort(function(a, b) { return b.score - a.score; });
    render(query, scored);
  }

  function loadIndexThen(cb) {
    fetch('{{ site.baseurl }}/search.json')
      .then(function(r) { return r.json(); })
      .then(function(data) { posts = data; if (cb) cb(); })
      .catch(function() { status.textContent = '검색 인덱스를 불러오지 못했습니다.'; });
  }

  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var q = input.value.trim();
    var url = new URL(window.location.href);
    if (q) { url.searchParams.set('q', q); } else { url.searchParams.delete('q'); }
    window.history.replaceState(null, '', url.toString());
    search(q);
  });

  var initial = getQueryParam();
  if (initial) input.value = initial;
  syncClearVisibility();

  loadIndexThen(function() {
    if (initial) search(initial);
  });
})();
</script>
