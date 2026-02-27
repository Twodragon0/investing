document.addEventListener('DOMContentLoaded', function() {
  var searchInput = document.getElementById('search-input');
  var searchResults = document.getElementById('search-results');
  if (!searchInput || !searchResults) return;

  var posts = [];
  var baseurl = searchInput.dataset.baseurl || '';

  fetch(baseurl + '/search.json')
    .then(function(r) { return r.json(); })
    .then(function(data) { posts = data; })
    .catch(function() { /* search index not available */ });

  function t(key) {
    return (typeof window.__t === 'function') ? window.__t(key) : key;
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function highlightText(text, query) {
    if (!text || !query) return escapeHtml(text || '');
    var escaped = escapeHtml(text);
    var regex = new RegExp('(' + query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    return escaped.replace(regex, '<mark>$1</mark>');
  }

  function getExcerptAround(text, query, maxLen) {
    if (!text) return '';
    var lower = text.toLowerCase();
    var idx = lower.indexOf(query.toLowerCase());
    if (idx === -1) return text.substring(0, maxLen);
    var start = Math.max(0, idx - 40);
    var end = Math.min(text.length, idx + query.length + 120);
    var snippet = '';
    if (start > 0) snippet += '...';
    snippet += text.substring(start, end);
    if (end < text.length) snippet += '...';
    return snippet;
  }

  function getCategoryClass(cat) {
    if (!cat) return '';
    var lower = cat.toLowerCase();
    if (lower.indexOf('crypto') !== -1) return 'cat-crypto';
    if (lower.indexOf('stock') !== -1 || lower.indexOf('주식') !== -1) return 'cat-stock';
    if (lower.indexOf('journal') !== -1 || lower.indexOf('저널') !== -1) return 'cat-journal';
    if (lower.indexOf('security') !== -1 || lower.indexOf('보안') !== -1) return 'cat-security';
    if (lower.indexOf('analysis') !== -1 || lower.indexOf('분석') !== -1) return 'cat-analysis';
    if (lower.indexOf('regulat') !== -1 || lower.indexOf('규제') !== -1) return 'cat-regulatory';
    if (lower.indexOf('politic') !== -1 || lower.indexOf('정치') !== -1) return 'cat-political';
    return '';
  }

  function scoreResult(post, query) {
    var score = 0;
    var q = query.toLowerCase();
    var title = (post.title || '').toLowerCase();
    var tags = (post.tags || '').toLowerCase();
    var categories = (post.categories || '').toLowerCase();
    var excerpt = (post.excerpt || '').toLowerCase();
    var content = (post.content || '').toLowerCase();

    if (title === q) score += 100;
    else if (title.indexOf(q) === 0) score += 80;
    else if (title.indexOf(q) !== -1) score += 60;

    if (tags.indexOf(q) !== -1) score += 40;
    if (categories.indexOf(q) !== -1) score += 30;
    if (excerpt.indexOf(q) !== -1) score += 20;
    if (content.indexOf(q) !== -1) score += 10;

    return score;
  }

  var debounceTimer;
  searchInput.addEventListener('input', function() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function() {
      performSearch();
    }, 200);
  });

  function performSearch() {
    var query = searchInput.value.trim();
    if (query.length < 2) {
      searchResults.innerHTML = '';
      var hint = document.createElement('div');
      hint.className = 'search-empty-state';
      hint.innerHTML = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>' +
        '<p>' + escapeHtml(t('search_min_hint')) + '</p>';
      searchResults.appendChild(hint);
      return;
    }

    var q = query.toLowerCase();
    var results = [];
    for (var i = 0; i < posts.length; i++) {
      var post = posts[i];
      var s = scoreResult(post, q);
      if (s > 0) {
        results.push({ post: post, score: s });
      }
    }

    results.sort(function(a, b) { return b.score - a.score; });
    results = results.slice(0, 15);

    searchResults.innerHTML = '';

    if (results.length === 0) {
      var noDiv = document.createElement('div');
      noDiv.className = 'search-empty-state';
      noDiv.innerHTML = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>' +
        '<p class="search-empty-title">' + escapeHtml(t('no_results')) + '</p>' +
        '<p class="search-empty-query">"' + escapeHtml(query) + '" ' + escapeHtml(t('no_results_for')) + '</p>';
      searchResults.appendChild(noDiv);
      return;
    }

    var countDiv = document.createElement('div');
    countDiv.className = 'search-result-count';
    countDiv.textContent = results.length + (results.length >= 15 ? '+' : '') + ' results';
    searchResults.appendChild(countDiv);

    for (var j = 0; j < results.length; j++) {
      var post = results[j].post;
      var item = document.createElement('a');
      item.href = post.url;
      item.className = 'search-result-item';

      var titleDiv = document.createElement('div');
      titleDiv.className = 'search-result-title';
      titleDiv.innerHTML = highlightText(post.title, query);

      var metaDiv = document.createElement('div');
      metaDiv.className = 'search-result-meta';

      var dateSpan = document.createElement('span');
      dateSpan.className = 'search-result-date';
      dateSpan.textContent = post.date;
      metaDiv.appendChild(dateSpan);

      if (post.categories) {
        var catSpan = document.createElement('span');
        catSpan.className = 'search-result-cat ' + getCategoryClass(post.categories);
        catSpan.textContent = post.categories;
        metaDiv.appendChild(catSpan);
      }

      if (post.tags) {
        var tagsArr = post.tags.split(', ');
        for (var k = 0; k < Math.min(tagsArr.length, 3); k++) {
          var tagSpan = document.createElement('span');
          tagSpan.className = 'search-result-tag';
          tagSpan.textContent = '#' + tagsArr[k];
          metaDiv.appendChild(tagSpan);
        }
      }

      item.appendChild(titleDiv);
      item.appendChild(metaDiv);

      var searchText = post.excerpt || post.content || '';
      if (searchText) {
        var snippetDiv = document.createElement('div');
        snippetDiv.className = 'search-result-snippet';
        snippetDiv.innerHTML = highlightText(getExcerptAround(searchText, query, 160), query);
        item.appendChild(snippetDiv);
      }

      searchResults.appendChild(item);
    }
  }

  // Keyboard navigation
  searchInput.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      var first = searchResults.querySelector('.search-result-item');
      if (first) first.focus();
    }
  });

  searchResults.addEventListener('keydown', function(e) {
    var current = document.activeElement;
    if (!current || !current.classList.contains('search-result-item')) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      var next = current.nextElementSibling;
      while (next && !next.classList.contains('search-result-item')) {
        next = next.nextElementSibling;
      }
      if (next) next.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      var prev = current.previousElementSibling;
      while (prev && !prev.classList.contains('search-result-item')) {
        prev = prev.previousElementSibling;
      }
      if (prev) prev.focus();
      else searchInput.focus();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      window.location.href = current.href;
    }
  });
});
