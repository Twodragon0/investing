/**
 * Google Translate Integration - 시스템 언어 설정 자동 적용
 *
 * This script provides Google Translate functionality with automatic system language detection.
 * It handles language toggle UI, cookie management, and translation initialization.
 */

// Google Translate 초기화 (지연 로딩)
var googleTranslateLoaded = false;

function googleTranslateElementInit() {
  try {
    if (typeof google === 'undefined' || !google.translate) {
      console.warn('Google Translate API가 아직 로드되지 않았습니다.');
      // 재시도
      setTimeout(function() {
        if (typeof google !== 'undefined' && google.translate) {
          googleTranslateElementInit();
        }
      }, 500);
      return;
    }

    var element = document.getElementById('google_translate_element');
    if (!element) {
      console.warn('Google Translate 요소를 찾을 수 없습니다.');
      return;
    }

    new google.translate.TranslateElement({
      pageLanguage: 'ko',
      includedLanguages: 'en,ja,zh-CN,es',
      layout: google.translate.TranslateElement.InlineLayout.SIMPLE,
      autoDisplay: false
    }, 'google_translate_element');

    googleTranslateLoaded = true;
  } catch (e) {
    console.error('Google Translate 초기화 실패:', e);
    // 초기화 실패해도 계속 진행 (쿠키 기반 번역은 작동할 수 있음)
  }
}

// 언어 토글 초기화
(function() {
  'use strict';

  var LANG_MAP = {
    'ko': 'KO',
    'en': 'EN',
    'ja': 'JA',
    'zh-CN': 'CN',
    'es': 'ES',
    'zh': 'CN'
  };

  /* data-lang 기반 복구용 (Google Translate DOM 변경 후 UI 복원) */
  var LANG_LABELS = {
    'ko': { flag: '\uD83C\uDDF0\uD83C\uDDF7', name: '한국어' },
    'en': { flag: '\uD83C\uDDFA\uD83C\uDDF8', name: 'English' },
    'ja': { flag: '\uD83C\uDDEF\uD83C\uDDF5', name: '日本語' },
    'zh-CN': { flag: '\uD83C\uDDE8\uD83C\uDDF3', name: '简体中文' },
    'es': { flag: '\uD83C\uDDEA\uD83C\uDDF8', name: 'Espa\u00f1ol' }
  };

  var translateScriptLoaded = false;
  var scriptLoadRetries = 0;
  var maxRetries = 3;

  // 안전한 localStorage 접근 (시크릿 모드 대응)
  function safeLocalStorageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch (e) {
      // 시크릿 모드나 쿠키 차단 시 null 반환
      return null;
    }
  }

  function safeLocalStorageSet(key, value) {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (e) {
      // 시크릿 모드나 쿠키 차단 시 실패
      return false;
    }
  }

  // 안전한 sessionStorage 접근 (시크릿 모드 대응)
  function safeSessionStorageGet(key) {
    try {
      return sessionStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function safeSessionStorageSet(key, value) {
    try {
      sessionStorage.setItem(key, value);
      return true;
    } catch (e) {
      return false;
    }
  }

  function safeSessionStorageRemove(key) {
    try {
      sessionStorage.removeItem(key);
      return true;
    } catch (e) {
      return false;
    }
  }

  // 안전한 쿠키 설정 (시크릿 모드 대응)
  function setCookie(name, value, days) {
    try {
      var expires = '';
      if (days) {
        var date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        expires = '; expires=' + date.toUTCString();
      }

      // SameSite 속성 추가 (시크릿 모드 호환성)
      var cookieString = name + '=' + value + expires + '; path=/; SameSite=Lax';

      // HTTPS인 경우 Secure 속성 추가
      if (location.protocol === 'https:') {
        cookieString += '; Secure';
      }

      document.cookie = cookieString;

      // 도메인 쿠키도 시도 (실패해도 무시)
      try {
        var domainCookie = name + '=' + value + expires + '; path=/; domain=.' + location.hostname + '; SameSite=Lax';
        if (location.protocol === 'https:') {
          domainCookie += '; Secure';
        }
        document.cookie = domainCookie;
      } catch (e) {
        // 도메인 쿠키 설정 실패는 무시
      }

      return true;
    } catch (e) {
      return false;
    }
  }

  // 안전한 쿠키 읽기
  function getCookie(name) {
    try {
      var nameEQ = name + '=';
      var ca = document.cookie.split(';');
      for (var i = 0; i < ca.length; i++) {
        var c = ca[i];
        while (c.charAt(0) === ' ') c = c.substring(1, c.length);
        if (c.indexOf(nameEQ) === 0) return c.substring(nameEQ.length, c.length);
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  // 쿠키 삭제 (Google Translate가 다양한 방식으로 설정하므로 모든 조합 시도)
  function deleteCookie(name) {
    try {
      var hostname = location.hostname;
      var isSecure = location.protocol === 'https:';
      var expiry = '; expires=Thu, 01 Jan 1970 00:00:00 UTC';

      // Google Translate가 설정할 수 있는 모든 도메인 조합
      var domains = ['', hostname, '.' + hostname];
      var parts = hostname.split('.');
      if (parts.length > 2) {
        var parent = parts.slice(1).join('.');
        domains.push(parent);
        domains.push('.' + parent);
      }

      domains.forEach(function(domain) {
        var base = name + '=' + expiry + '; path=/';
        if (domain) base += '; domain=' + domain;

        // SameSite 없이, Lax, None 모두 시도
        document.cookie = base;
        document.cookie = base + '; SameSite=Lax';
        if (isSecure) {
          document.cookie = base + '; Secure';
          document.cookie = base + '; SameSite=Lax; Secure';
          document.cookie = base + '; SameSite=None; Secure';
        }
      });
      return true;
    } catch (e) {
      return false;
    }
  }

  // 시스템 언어 감지
  function getSystemLanguage() {
    var lang = navigator.language || navigator.userLanguage || 'ko';
    lang = lang.toLowerCase();

    if (lang.startsWith('ko')) return 'ko';
    if (lang.startsWith('ja')) return 'ja';
    if (lang.startsWith('zh')) return 'zh-CN';
    if (lang.startsWith('en')) return 'en';
    if (lang.startsWith('es')) return 'es';

    return 'ko';
  }

  // 저장된 언어 또는 시스템 언어 가져오기
  function getPreferredLanguage() {
    var saved = safeLocalStorageGet('preferredLang');
    if (!saved || saved === 'system') {
      return getSystemLanguage();
    }
    return saved;
  }

  // Google Translate 스크립트 지연 로딩 (재시도 로직 포함)
  function loadTranslateScript(callback, retryCount) {
    retryCount = retryCount || 0;

    if (translateScriptLoaded) {
      if (callback) callback();
      return;
    }

    // 이미 로딩 중인 스크립트가 있는지 확인
    var existingScript = document.querySelector('script[src*="translate_a/element.js"]');
    if (existingScript) {
      // 스크립트가 이미 있으면 로드 완료 대기
      var checkInterval = setInterval(function() {
        if (typeof google !== 'undefined' && google.translate) {
          clearInterval(checkInterval);
          translateScriptLoaded = true;
          if (callback) {
            setTimeout(callback, 500);
          }
        }
      }, 100);

      // 최대 10초 대기
      setTimeout(function() {
        clearInterval(checkInterval);
      }, 10000);
      return;
    }

    var script = document.createElement('script');
    script.type = 'text/javascript';
    script.src = '//translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';

    script.onload = function() {
      // Google Translate가 로드되었는지 확인
      var initCheck = setInterval(function() {
        if (typeof google !== 'undefined' && google.translate && googleTranslateLoaded) {
          clearInterval(initCheck);
          translateScriptLoaded = true;
          scriptLoadRetries = 0;
          if (callback) {
            setTimeout(callback, 500);
          }
        }
      }, 100);

      // 최대 5초 대기
      setTimeout(function() {
        clearInterval(initCheck);
        if (!translateScriptLoaded && retryCount < maxRetries) {
          // 재시도
          scriptLoadRetries++;
          setTimeout(function() {
            loadTranslateScript(callback, retryCount + 1);
          }, 1000 * (retryCount + 1));
        }
      }, 5000);
    };

    script.onerror = function() {
      // 스크립트 로딩 실패 시 재시도
      if (retryCount < maxRetries) {
        scriptLoadRetries++;
        setTimeout(function() {
          loadTranslateScript(callback, retryCount + 1);
        }, 1000 * (retryCount + 1));
      } else {
        console.warn('Google Translate 스크립트 로딩 실패');
      }
    };

    document.head.appendChild(script);
  }

  function initLangToggle() {
    var langToggle = document.getElementById('lang-toggle');
    var langDropdown = document.getElementById('lang-dropdown');
    var langDropdownOverlay = document.getElementById('lang-dropdown-overlay');
    var currentLangSpan = document.getElementById('current-lang');

    if (!langToggle || !langDropdown) {
      return;
    }

    // 토글 버튼 클릭 - addEventListener 사용
    langToggle.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();

      var isActive = langDropdown.classList.contains('active');

      if (isActive) {
        langDropdown.classList.remove('active');
        langToggle.setAttribute('aria-expanded', 'false');
        if (langDropdownOverlay) {
          langDropdownOverlay.classList.remove('active');
          langDropdownOverlay.setAttribute('aria-hidden', 'true');
        }
      } else {
        langDropdown.classList.add('active');
        langToggle.setAttribute('aria-expanded', 'true');
        if (langDropdownOverlay) {
          langDropdownOverlay.classList.add('active');
          langDropdownOverlay.setAttribute('aria-hidden', 'false');
        }
      }
    }, true);

    // 더블클릭으로 시스템 설정으로 복귀
    langToggle.addEventListener('dblclick', function(e) {
      e.preventDefault();
      e.stopPropagation();
      safeLocalStorageSet('preferredLang', 'system');
      var sysLang = getSystemLanguage();
      if (LANG_MAP[sysLang] && currentLangSpan) {
        currentLangSpan.textContent = LANG_MAP[sysLang];
      }
      // 시스템 언어로 복귀 시 플래그 초기화
      safeSessionStorageRemove('langApplied');
      safeSessionStorageRemove('langChanging');
      changeLang(sysLang);
    }, true);

    // 외부 클릭 시 닫기 (overlay 클릭 시에도 닫힘)
    document.addEventListener('click', function(e) {
      var target = e.target;
      while (target && target.tagName === 'FONT') {
        target = target.parentNode;
      }
      if (!langToggle.contains(target) && !langDropdown.contains(target)) {
        langDropdown.classList.remove('active');
        langToggle.setAttribute('aria-expanded', 'false');
        if (langDropdownOverlay) {
          langDropdownOverlay.classList.remove('active');
          langDropdownOverlay.setAttribute('aria-hidden', 'true');
        }
      }
    });

    // 언어 옵션 클릭 - 이벤트 위임 사용
    langDropdown.addEventListener('click', function(e) {
      var target = e.target;

      // font 태그나 텍스트 노드를 통과하여 lang-option 찾기
      while (target && !target.classList.contains('lang-option')) {
        if (target === langDropdown || target === document.body) {
          return;
        }
        target = target.parentNode;
      }

      if (target && target.classList.contains('lang-option')) {
        e.preventDefault();
        e.stopPropagation();

        var lang = target.getAttribute('data-lang');

        // lang 속성이 없으면 텍스트에서 추출 시도
        if (!lang) {
          var text = target.textContent.trim();
          if (text.includes('한국어') || text.includes('🇰🇷')) lang = 'ko';
          else if (text.includes('English') || text.includes('🇺🇸')) lang = 'en';
          else if (text.includes('日本語') || text.includes('🇯🇵')) lang = 'ja';
          else if (text.includes('简体中文') || text.includes('🇨🇳')) lang = 'zh-CN';
          else if (text.includes('Español') || text.includes('🇪🇸')) lang = 'es';
        }

        if (lang) {
          langDropdown.classList.remove('active');
          langToggle.setAttribute('aria-expanded', 'false');
          if (langDropdownOverlay) {
            langDropdownOverlay.classList.remove('active');
            langDropdownOverlay.setAttribute('aria-hidden', 'true');
          }

          if (LANG_MAP[lang] && currentLangSpan) {
            currentLangSpan.textContent = LANG_MAP[lang];
          }

          safeLocalStorageSet('preferredLang', lang);
          // 수동 언어 변경 시 플래그 초기화
          safeSessionStorageRemove('langApplied');
          safeSessionStorageRemove('langChanging');
          changeLang(lang);
        }
      }
    }, true);

    // 현재 언어 감지 및 표시 (localStorage 우선, 쿠키 보조)
    var currentLang = getCurrentLang();
    var savedPref = safeLocalStorageGet('preferredLang');
    var displayLang = currentLang;

    // localStorage에 사용자가 명시적으로 선택한 언어가 있으면 우선 적용
    if (savedPref && savedPref !== 'system' && LANG_MAP[savedPref]) {
      displayLang = savedPref;
    }

    if (LANG_MAP[displayLang] && currentLangSpan) {
      currentLangSpan.textContent = LANG_MAP[displayLang];
    }

    // 시스템 언어 자동 적용
    applySystemLanguage();
  }

  function getCurrentLang() {
    // 쿠키에서 언어 정보 읽기 (다양한 형식 지원)
    try {
      var cookie = getCookie('googtrans');
      if (cookie) {
        // /ko/[lang] 형식
        var match = cookie.match(/\/ko\/([^\/;]+)/);
        if (match && match[1]) {
          return match[1];
        }
        // /auto/[lang] 또는 /[any]/[lang] 형식 (Google Translate가 변경할 수 있음)
        match = cookie.match(/\/[^\/]+\/([^\/;]+)/);
        if (match && match[1]) {
          return match[1];
        }
      }

      // 대체 방법: document.cookie 직접 읽기 (다양한 형식)
      var directMatch = document.cookie.match(/googtrans=\/[^\/]+\/([^;\/]+)/);
      if (directMatch && directMatch[1]) {
        return directMatch[1];
      }
    } catch (e) {
      // 쿠키 읽기 실패 시 한국어로 간주
    }

    // 쿠키가 없으면 한국어로 간주
    return 'ko';
  }

  // 시스템 언어 자동 적용 (한 번만 실행)
  function applySystemLanguage() {
    // 이미 실행되었는지 확인 (무한 루프 방지)
    var appliedFlag = safeSessionStorageGet('langApplied');
    if (appliedFlag === 'true') {
      return;
    }

    var currentLang = getCurrentLang();
    var savedPref = safeLocalStorageGet('preferredLang');

    // 사용자가 수동으로 선택한 언어가 있으면 그 설정을 우선 적용
    if (savedPref && savedPref !== 'system') {
      safeSessionStorageSet('langApplied', 'true');

      // 현재 언어와 저장된 선택이 다르면 저장된 선택으로 변경
      if (savedPref !== currentLang) {
        if (savedPref !== 'ko') {
          loadTranslateScript(function() {
            setTimeout(function() {
              changeLang(savedPref);
            }, 300);
          });
        } else if (currentLang !== 'ko') {
          changeLang('ko');
        }
      } else if (savedPref !== 'ko' && !translateScriptLoaded) {
        loadTranslateScript();
      }
      return;
    }

    // 저장된 선택이 없으면 시스템 언어 적용
    var preferredLang = getPreferredLanguage();

    if (preferredLang !== currentLang) {
      // 플래그 설정 (무한 루프 방지)
      safeSessionStorageSet('langApplied', 'true');

      // Google Translate 스크립트 로딩 후 언어 변경
      if (preferredLang !== 'ko') {
        loadTranslateScript(function() {
          setTimeout(function() {
            changeLang(preferredLang);
          }, 300);
        });
      } else if (currentLang !== 'ko') {
        changeLang('ko');
      }
    } else {
      // 이미 올바른 언어면 플래그 설정
      safeSessionStorageSet('langApplied', 'true');

      if (preferredLang !== 'ko' && !translateScriptLoaded) {
        loadTranslateScript();
      }
    }
  }

  function changeLang(lang) {
    // 무한 루프 방지: 이미 언어 변경이 진행 중이면 중단
    var changingFlag = safeSessionStorageGet('langChanging');
    if (changingFlag === 'true') {
      return;
    }

    // 언어 변경 시작 플래그 설정
    safeSessionStorageSet('langChanging', 'true');

    if (lang === 'ko') {
      // 한국어로 복귀: Google Translate 자체 복원 + 쿠키 완전 삭제

      // 1. Google Translate select를 원래 언어로 복원 (가장 확실한 방법)
      var select = document.querySelector('.goog-te-combo');
      if (select && translateScriptLoaded) {
        try {
          select.value = '';  // 빈 값 = 원본 언어(한국어) 복원
          var evt = document.createEvent('HTMLEvents');
          evt.initEvent('change', true, true);
          select.dispatchEvent(evt);
        } catch (e) {}
      }

      // 2. googtrans 쿠키 완전 삭제 (모든 도메인/속성 조합)
      deleteCookie('googtrans');

      // 3. Google Translate iframe/banner 제거
      var gtBanner = document.querySelector('.goog-te-banner-frame');
      if (gtBanner) { try { gtBanner.remove(); } catch (e) {} }

      // 4. body top 리셋 (Google Translate가 body를 밀어내는 경우)
      if (document.body) {
        document.body.style.top = '0';
        document.body.style.position = '';
      }

      safeSessionStorageSet('langChanging', 'false');
      safeSessionStorageSet('langApplied', 'true');

      // 5. URL 해시에서 googtrans 제거 후 클린 리로드
      setTimeout(function() {
        var cleanUrl = location.href.replace(/#googtrans\([^)]*\)/g, '').replace(/#$/, '');
        if (cleanUrl !== location.href) {
          window.location.href = cleanUrl;
        } else {
          location.reload();
        }
      }, 200);
      return;
    }

    // 다른 언어로 변경: 쿠키 설정
    var cookieVal = '/ko/' + lang;
    setCookie('googtrans', cookieVal, 365);

    // 버튼 텍스트 즉시 업데이트 (reload 전에도 반영)
    var currentLangSpan = document.getElementById('current-lang');
    if (LANG_MAP[lang] && currentLangSpan) {
      currentLangSpan.textContent = LANG_MAP[lang];
    }

    // 쿠키 설정 실패 시에도 계속 진행 (시크릿 모드에서도 작동하도록)
    var select = document.querySelector('.goog-te-combo');
    if (select && translateScriptLoaded) {
      try {
        select.value = lang;
        var changeEvent = new Event('change', { bubbles: true });
        select.dispatchEvent(changeEvent);

        // 언어 변경 완료 플래그 설정
        safeSessionStorageSet('langChanging', 'false');
        safeSessionStorageSet('langApplied', 'true');

        // Google Translate가 즉시 반영하지 않을 수 있으므로 짧은 지연 후 확인
        setTimeout(function() {
          var currentLangAfterChange = getCurrentLang();
          if (currentLangAfterChange !== lang) {
            // 변경이 반영되지 않았으면 리로드
            location.reload();
          }
        }, 500);
      } catch (e) {
        // 이벤트 디스패치 실패 시 리로드
        setTimeout(function() {
          location.reload();
        }, 150);
      }
    } else {
      // 쿠키 설정 후 짧은 지연 후 리로드 (쿠키가 확실히 설정되도록)
      safeSessionStorageSet('langChanging', 'false');
      safeSessionStorageSet('langApplied', 'true');
      setTimeout(function() {
        location.reload();
      }, 150);
    }
  }

  // Google Translate가 삽입한 font 태그 제거 (lang 옵션 UI 깨짐 방지)
  function cleanupFontTags() {
    var selectors = [
      '.notranslate font',
      '[translate="no"] font',
      '.lang-toggle-wrapper font',
      '.lang-toggle font',
      '.lang-code font',
      '.lang-dropdown font',
      '.lang-option font',
      '.chat-widget font'
    ];

    selectors.forEach(function(selector) {
      var fonts = document.querySelectorAll(selector);
      fonts.forEach(function(font) {
        var parent = font.parentNode;
        while (font.firstChild) {
          parent.insertBefore(font.firstChild, font);
        }
        parent.removeChild(font);
      });
    });
  }

  // Google Translate select 요소에 id/name 속성 추가 (접근성 및 autofill 개선)
  function addAttributesToTranslateSelect() {
    var select = document.querySelector('.goog-te-combo');
    if (select) {
      if (!select.id) {
        select.id = 'google-translate-select';
      }
      if (!select.name) {
        select.name = 'google-translate-language';
      }
      if (!select.getAttribute('aria-label')) {
        select.setAttribute('aria-label', '번역 언어 선택');
      }
    }
  }

  // lang-dropdown과 lang-option 구조 복구
  function restoreLangStructure() {
    var langDropdown = document.getElementById('lang-dropdown');
    if (!langDropdown) return;

    // lang-dropdown에 직접 추가된 텍스트 노드 제거
    var childNodes = Array.from(langDropdown.childNodes);
    childNodes.forEach(function(node) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
        // 텍스트 노드가 있고 버튼이 아닌 경우 제거
        langDropdown.removeChild(node);
      }
    });

    // lang-option 구조 복구 (Google Translate font/span 파괴 시 data-lang 기반 복원)
    var langOptions = document.querySelectorAll('.lang-option');
    langOptions.forEach(function(option) {
      var hasFlag = option.querySelector('.lang-flag');
      var hasName = option.querySelector('.lang-name');
      if (hasFlag && hasName) return;

      var dataLang = option.getAttribute('data-lang');
      var flag = '';
      var name = '';

      if (dataLang && LANG_LABELS[dataLang]) {
        flag = LANG_LABELS[dataLang].flag;
        name = LANG_LABELS[dataLang].name;
      } else {
        var textContent = option.textContent.trim();
        var flagMatch = textContent.match(/[\u{1F1E6}-\u{1F1FF}]{2}/u);
        flag = flagMatch ? flagMatch[0] : '';
        name = textContent.replace(/[\u{1F1E6}-\u{1F1FF}]{2}\s*/u, '').trim();
      }

      while (option.firstChild) option.removeChild(option.firstChild);

      if (flag) {
        var flagSpan = document.createElement('span');
        flagSpan.className = 'lang-flag';
        flagSpan.textContent = flag;
        option.appendChild(flagSpan);
      }
      if (name) {
        var nameSpan = document.createElement('span');
        nameSpan.className = 'lang-name';
        nameSpan.textContent = name;
        option.appendChild(nameSpan);
      }
    });
  }

  // Google Translate 배너/팝업 강제 숨김 및 CLS 방지
  function hideGoogleTranslateBanner() {
    var banners = document.querySelectorAll(
      '.goog-te-banner-frame, [class*="VIpgJd"], #goog-gt-tt, .goog-te-balloon-frame, .goog-te-menu-frame'
    );
    banners.forEach(function(el) {
      // CLS 방지를 위한 강력한 스타일 적용
      el.style.setProperty('display', 'none', 'important');
      el.style.setProperty('visibility', 'hidden', 'important');
      el.style.setProperty('position', 'fixed', 'important');
      el.style.setProperty('top', '0', 'important');
      el.style.setProperty('left', '0', 'important');
      el.style.setProperty('width', '0', 'important');
      el.style.setProperty('height', '0', 'important');
      el.style.setProperty('overflow', 'hidden', 'important');
      el.style.setProperty('opacity', '0', 'important');
      el.style.setProperty('z-index', '-1', 'important');
      el.style.setProperty('contain', 'strict', 'important');
    });

    if (document.body) {
      document.body.style.top = '0';
      document.body.style.position = 'static';
    }
  }

  // Google Translate 위젯 동적 추가 감지 및 CLS 방지
  function preventGoogleTranslateCLS() {
    if ('MutationObserver' in window) {
      var observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
          mutation.addedNodes.forEach(function(node) {
            if (node.nodeType === 1) { // Element node
              // VIpgJd 클래스를 가진 요소 감지
              if (node.classList && node.classList.toString().includes('VIpgJd')) {
                hideGoogleTranslateBanner();
              }
              // 하위에 있는 Google Translate 요소도 처리
              var translateElements = node.querySelectorAll && node.querySelectorAll(
                '[class*="VIpgJd"], .goog-te-banner-frame, #goog-gt-tt, .goog-te-balloon-frame'
              );
              if (translateElements && translateElements.length > 0) {
                hideGoogleTranslateBanner();
              }
            }
          });
        });
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class']
      });
    }
  }

  // DOM 준비 시 초기화
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      // 페이지 로드 후 짧은 지연으로 언어 적용 (쿠키가 확실히 읽히도록)
      setTimeout(function() {
        initLangToggle();
        cleanupFontTags();
        restoreLangStructure();
        hideGoogleTranslateBanner();
        addAttributesToTranslateSelect();
        preventGoogleTranslateCLS(); // CLS 방지 감시 시작
      }, 100);
    });
  } else {
    // 페이지 로드 후 짧은 지연으로 언어 적용 (쿠키가 확실히 읽히도록)
    setTimeout(function() {
      initLangToggle();
      cleanupFontTags();
      restoreLangStructure();
      hideGoogleTranslateBanner();
      addAttributesToTranslateSelect();
      preventGoogleTranslateCLS(); // CLS 방지 감시 시작
    }, 100);
  }

  // Google Translate select 요소가 동적으로 생성될 때 속성 추가 (MutationObserver)
  if ('MutationObserver' in window) {
    var observer = new MutationObserver(function(mutations) {
      cleanupFontTags();
      restoreLangStructure();
      hideGoogleTranslateBanner();
      addAttributesToTranslateSelect();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
  }

  // 번역이 필요한 경우에만 스크립트 로딩
  // 사용자가 명시적으로 한국어를 선택한 경우 로딩하지 않음
  var sysLang = getSystemLanguage();
  var currentLang = getCurrentLang();
  var userPref = safeLocalStorageGet('preferredLang');
  var needsTranslate = (userPref && userPref !== 'system' && userPref !== 'ko') ||
                       (!userPref && sysLang !== 'ko') ||
                       (currentLang !== 'ko');

  if (needsTranslate) {
    // 페이지 로드 완료 후 지연 로딩
    if (document.readyState === 'complete') {
      setTimeout(loadTranslateScript, 100);
    } else {
      window.addEventListener('load', function() {
        setTimeout(loadTranslateScript, 100);
      });
    }
  }
})();
