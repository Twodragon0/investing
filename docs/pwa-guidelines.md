# PWA Guidelines

## 매니페스트 아이콘 규칙

`manifest.json`의 `icons` 배열에는 **표준 PWA 사이즈만** 포함합니다.

| 용도 | 위치 | 사이즈 |
|------|------|--------|
| PWA 표준 | `manifest.json` | 192×192, 512×512 (`purpose: "any maskable"`) |
| 파비콘 | `manifest.json` | 32×32 (`purpose` 생략) |
| iOS 홈스크린 | `_layouts/default.html` `<link rel="apple-touch-icon">` | 180×180 |

### 왜 180×180을 매니페스트에 넣지 않는가

- Chrome은 `manifest.json`에서 비표준 사이즈(180×180 등)를 감지하면 `"Resource size is not correct - typo in the Manifest?"` 경고를 띄웁니다.
- iOS Safari는 매니페스트를 참조하지 않고 `<link rel="apple-touch-icon">` HTML 태그만 사용합니다 — 매니페스트에 중복 선언할 필요가 없습니다.
- 따라서 180×180 아이콘은 **HTML `<link>` 태그 전용**으로 유지합니다.

### 현재 아이콘 파일

```
assets/images/
├── favicon-32.png       (32×32, 매니페스트+브라우저 탭)
├── favicon-192.png      (192×192, 매니페스트 표준)
├── favicon-512.png      (512×512, 매니페스트 표준)
└── apple-touch-icon.png (180×180, HTML <link>만)
```

## 이미지 Preload 규칙

`_layouts/default.html`에서 LCP 히어로 이미지(`page.image`)를 preload할 때:

- **AVIF 한 가지만** preload (`type="image/avif"` 힌트로 미지원 브라우저는 스킵)
- 동일 이미지의 WebP/PNG는 preload하지 않음 — `<picture>` 엘리먼트가 브라우저에 맞춰 선택
- 여러 포맷을 동시에 preload하면 브라우저가 실제로 사용하지 않은 포맷에 대해 "preloaded but not used" 콘솔 경고 발생

```html
<link rel="preload" as="image" type="image/avif"
      href="{{ preload_avif | relative_url }}" fetchpriority="high">
```

## 관련 파일

- `manifest.json` — PWA 매니페스트
- `_layouts/default.html` — 아이콘/이미지 preload HTML 태그
- `_includes/generated-picture.html` — AVIF/WebP/PNG `<picture>` 렌더링
- `sw.js` — 서비스 워커 (이미지 캐시)
