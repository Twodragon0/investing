document.addEventListener('DOMContentLoaded', function() {
  // Mobile nav toggle
  const navToggle = document.querySelector('.nav-toggle');
  const siteNav = document.querySelector('.site-nav');
  if (navToggle && siteNav) {
    navToggle.addEventListener('click', function() {
      siteNav.classList.toggle('active');
    });
  }

  // Simple search functionality
  const searchInput = document.getElementById('search-input');
  const searchResults = document.getElementById('search-results');
  if (!searchInput || !searchResults) return;

  let posts = [];
  fetch(searchInput.dataset.baseurl + '/search.json')
    .then(function(response) { return response.json(); })
    .then(function(data) { posts = data; })
    .catch(function() { /* search index not available */ });

  searchInput.addEventListener('input', function() {
    var query = this.value.toLowerCase().trim();
    if (query.length < 2) {
      searchResults.textContent = '';
      var hint = document.createElement('div');
      hint.style.cssText = 'text-align: center; padding: 3rem; color: #8b949e;';
      var hintP = document.createElement('p');
      hintP.textContent = (typeof window.__t === 'function') ? window.__t('search_min_hint') : '검색어를 2자 이상 입력해주세요.';
      hint.appendChild(hintP);
      searchResults.appendChild(hint);
      return;
    }

    var results = posts.filter(function(post) {
      return post.title.toLowerCase().indexOf(query) !== -1 ||
             (post.tags && post.tags.toLowerCase().indexOf(query) !== -1) ||
             (post.categories && post.categories.toLowerCase().indexOf(query) !== -1);
    }).slice(0, 10);

    if (results.length === 0) {
      searchResults.textContent = '';
      var noDiv = document.createElement('div');
      noDiv.style.cssText = 'text-align: center; padding: 3rem; color: #8b949e;';
      var noResultsText = (typeof window.__t === 'function') ? window.__t('no_results') : '검색 결과가 없습니다';
      noDiv.innerHTML = '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.5; margin-bottom: 1rem;"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg><p style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem;">' + noResultsText + '</p>';
      var noResultsFor = (typeof window.__t === 'function') ? window.__t('no_results_for') : '에 대한 포스트를 찾을 수 없습니다.';
      var queryP = document.createElement('p');
      queryP.textContent = '"' + query + '" ' + noResultsFor;
      noDiv.appendChild(queryP);
      searchResults.appendChild(noDiv);
      return;
    }

    searchResults.textContent = '';
    results.forEach(function(post) {
      var item = document.createElement('div');
      item.className = 'search-result-item';
      var link = document.createElement('a');
      link.href = post.url;
      link.textContent = post.title;
      var meta = document.createElement('small');
      meta.textContent = post.date + ' | ' + post.categories;
      item.appendChild(link);
      item.appendChild(meta);
      searchResults.appendChild(item);
    });
  });
});
