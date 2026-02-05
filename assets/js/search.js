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
    if (query.length < 2) { searchResults.innerHTML = ''; return; }
    var results = posts.filter(function(post) {
      return post.title.toLowerCase().indexOf(query) !== -1 ||
             (post.tags && post.tags.toLowerCase().indexOf(query) !== -1) ||
             (post.categories && post.categories.toLowerCase().indexOf(query) !== -1);
    }).slice(0, 10);
    searchResults.innerHTML = results.map(function(post) {
      return '<div class="search-result-item"><a href="' + post.url + '">' + post.title + '</a>' +
             '<small> ' + post.date + ' | ' + post.categories + '</small></div>';
    }).join('');
  });
});
