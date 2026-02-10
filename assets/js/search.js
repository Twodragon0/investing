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
      searchResults.innerHTML = '<div style="text-align: center; padding: 3rem; color: #8b949e;"><p>검색어를 2자 이상 입력해주세요.</p></div>';
      return;
    }

    var results = posts.filter(function(post) {
      return post.title.toLowerCase().indexOf(query) !== -1 ||
             (post.tags && post.tags.toLowerCase().indexOf(query) !== -1) ||
             (post.categories && post.categories.toLowerCase().indexOf(query) !== -1);
    }).slice(0, 10);

    if (results.length === 0) {
      searchResults.innerHTML = '<div style="text-align: center; padding: 3rem; color: #8b949e;"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.5; margin-bottom: 1rem;"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg><p style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem;">검색 결과가 없습니다</p><p>"' + query + '"에 대한 포스트를 찾을 수 없습니다.</p></div>';
      return;
    }

    searchResults.innerHTML = results.map(function(post) {
      return '<div class="search-result-item"><a href="' + post.url + '">' + post.title + '</a>' +
             '<small>' + post.date + ' | ' + post.categories + '</small></div>';
    }).join('');
  });
});
