/** @type {import('@fullhuman/postcss-purgecss').UserDefinedOptions} */
module.exports = {
  // Jekyll 빌드 결과물의 모든 HTML 파일을 content 소스로 사용
  content: [
    '_site/**/*.html',
    '_site/**/*.js',
  ],

  // 처리 대상 CSS 파일
  css: ['_site/**/*.css'],

  // CSS variables, keyframes, font-face 보존
  variables: true,
  keyframes: true,
  fontFace: true,

  // 동적으로 추가되는 클래스 safelist
  // 1. 고정 문자열: JS/테마에서 직접 토글되는 클래스
  // 2. 패턴(정규식): 접두사 기반 동적 클래스
  safelist: {
    standard: [
      // 테마 관련
      'dark-mode',
      'light-mode',

      // 상태 클래스 (JS 토글)
      'active',
      'show',
      'hidden',
      'open',
      'collapsed',
      'visible',

      // 애니메이션
      'fade-in',

      // post.js 동적 추가
      'post-lead',
      'broken-image',
      'post-image-placeholder',
      'is-scrollable',
      'scrolled-start',
      'scrolled-end',
      'table-scroll-btn',
      'table-scroll-btn-left',
      'table-scroll-btn-right',

      // reports.js 동적 추가
      'bookmarked',
      'notify-active',
      'reports-list-view',

      // extras.js (mermaid)
      'mermaid',
      'language-mermaid',

      // search.js
      'search-result-item',

      // 읽기 진행바
      'reading-progress',
    ],
    deep: [
      // data-* 속성 선택자 패턴
      /^\[data-/,
      // JS/CSS 유틸리티 접두사 패턴
      /^js-/,
      /^is-/,
      /^has-/,
      // data-theme 기반 테마 선택자
      /^data-theme/,
    ],
    greedy: [
      // :root CSS variable 선언 블록 보존
      /:root/,
    ],
  },

  // 참고: output 경로는 purgecss_build.sh 스크립트에서 --output 플래그로 제어
  // 설정 파일에서 output을 지정하면 CLI --output보다 우선순위가 낮아 무시됨
};
