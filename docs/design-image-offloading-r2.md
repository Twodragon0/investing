# 정밀 설계: 생성 이미지 외부 오브젝트 스토리지 오프로딩 (옵션 D)

> 작성 2026-06-10. 상위 문서 `design-generated-image-lifecycle.md`의 **옵션 D** 구체 설계.
> 목표: 생성 이미지 수명을 git 저장소 크기와 **분리**하여, 옛 포스트도 고유 hero/og 이미지를
> 영구 보존하면서 저장소 비대화(현재 214MB / ~2.6GB·년)와 git 히스토리 누적을 제거한다.
>
> 전제: 1차 레이아웃 가드(커밋 d3618d7cb…dcd8b076f)는 이미 적용됨 — D 도입 중/후에도
> 누락 이미지는 우아하게 폴백되므로 **무중단 점진 전환**이 가능하다.

## 1. 스토리지 선택

| 후보 | 월 비용(개념) | egress | 통합 난이도 | 비고 |
|---|---|---|---|---|
| **Cloudflare R2** (권장) | 스토리지만 과금, **egress 무료** | 무료 ✓ | S3 호환 API | 정적 이미지 대량 서빙에 최적. 커스텀 도메인+CDN 무료 |
| AWS S3 + CloudFront | 스토리지 + egress + CDN | 유료 | 성숙 | egress 비용이 트래픽 따라 증가 |
| GitHub Release Assets | 무료 | GH CDN | 단순 | 폴더 구조/수명관리 빈약, API rate limit |
| Git LFS | LFS 대역폭 과금 | 유료 | 중 | 여전히 git에 포인터, 히스토리 분리 안 됨 — **부적합** |

**결정: Cloudflare R2.** egress 무료가 이미지 호스팅의 핵심. S3 호환이라 `boto3`로 업로드.
커스텀 도메인(예: `img.2twodragon.com`)에 R2 버킷 연결 + Cloudflare CDN 캐시.

## 2. URL 스킴

- 현재: `/assets/images/generated/news-briefing-crypto-2026-03-20.png` (사이트 상대)
- 목표: `https://img.2twodragon.com/generated/news-briefing-crypto-2026-03-20.png` (절대, R2+CDN)
- 파일명 규약 불변(영문, 날짜 포함) → 키 = `generated/<filename>`. avif/webp/png 3변형 모두 업로드.
- 포스트 front matter `image:` 및 본문은 **절대 URL** 저장. 레이아웃은 절대 URL을 그대로 사용
  (단, 존재 가드의 `site.static_files` 체크는 R2 객체엔 적용 불가 → §6 참조).

## 3. 생성 파이프라인 통합 지점

핵심: `scripts/common/image_generator/`(패키지) 저장 직후 R2 업로드, 그리고
`post_generator._resolve_post_image()`(현재 line 218 — `image:` 경로 정규화 단일 지점)에서
절대 CDN URL을 반환하도록 확장.

```
image_generator.save(...)  →  로컬 임시 저장 (avif/webp/png)
                           →  [NEW] R2 업로드 (boto3 put_object, 3변형, Content-Type 지정)
                           →  post_generator에 절대 CDN URL 반환
```

- 신규 모듈 `scripts/common/asset_storage.py`: `upload_generated(local_path) -> cdn_url`.
  - `get_env()`로 자격증명 로드, 미설정 시 **graceful degradation**(로컬 경로 반환 → 기존 동작 유지).
  - `config.REQUEST_TIMEOUT`, certifi-first SSL 규약 준수.
  - 멱등: 동일 키 존재 시 skip(or overwrite) — dedup 규약과 정합.
- `post_generator`/`generate_*.py`는 `image:` 필드에 반환된 절대 URL을 기록.
- **로컬 `assets/images/generated/`에는 더 이상 커밋하지 않음** → `.gitignore`에 추가.

## 4. 기존 포스트 마이그레이션

대상: `_posts/*.md` 중 `image:`(+본문)이 `/assets/images/generated/`를 가리키는 ~1493개.
단, 이미 정리된 1051개 이미지는 **원본이 없어** R2에 올릴 수 없음 → 2분기 전략:

1. **현존 이미지(≈30일 윈도우, 3844파일)**: R2 업로드 후 해당 포스트 `image:`를 절대 URL로 치환.
2. **이미 정리된 이미지(파일 소실)**: 재생성 불가(시세/뉴스 시간의존) → 1차 가드의 폴백 유지
   (기본 og + 카테고리 아이콘). 신규 생성분부터 영구 보존되므로 **시간이 지나며 자연 해소**.

마이그레이션 스크립트 `scripts/migrate_images_to_r2.py` (dry-run 우선):
```
--dry-run  : 치환 대상 포스트/URL 목록만 출력
--apply    : R2 업로드 + 포스트 image: 치환 (백업/원자적 쓰기, _state 미수정)
```
- 안전장치: 업로드 성공 확인 후에만 포스트 치환. 실패 시 해당 포스트 skip.
- 검증: 치환 후 `python scripts/check_post_images.py`(R2 HEAD 체크로 확장) + `bundle exec jekyll build`.

## 5. 정리 워크플로우 처리

- `cleanup-old-images.yml`은 **불필요해짐**(로컬에 이미지를 더 안 둠) → 비활성/삭제.
- R2 측 수명관리: 영구 보존(권장, 비용 미미) 또는 R2 lifecycle rule로 N년 후 정리(선택).

## 6. 레이아웃/가드 영향

### 6.1 `_config.yml` 설정

`_config.yml`에 다음 필드 추가:

```yaml
# R2 공개 CDN 베이스 URL (예: https://img.2twodragon.com, 기본: 빈 문자열)
# 미설정 시 레이아웃은 로컬 경로만 참조 → graceful degradation
r2_image_base: ""
```

레이아웃 가드(`_includes/generated-picture.html`, `_layouts/default.html`, `_layouts/post.html`)가
이 값으로 R2 절대 URL을 인식하고 `<picture>` 렌더링을 활성화.

### 6.2 R2 경로 존재 검사 생략

절대 R2 URL은 `site.static_files` 존재 체크가 불가능(로컬 파일 아님).
**R2 경로는 존재 검사를 생략**하고 항상 `<picture>`(avif/webp source 포함) 렌더.
안전성은 마이그레이션의 **3변형 업로드 게이트**(§8 step4)가 보장:
png/webp/avif 3변형 모두 업로드 성공 시에만 `image:` 치환 → 존재 안 하는 `<source>` 참조 방지.

### 6.3 로컬 경로 분기 무회귀 유지

혼재 기간(R2 URL + 옛 로컬 경로) 동안 로컬 경로 분기는 바이트 동일 무회귀 유지.
7개 include 호출처(`_layouts/default.html`/`post.html`, `_includes/`, 카테고리 페이지)가 보호됨.
- 로컬 경로: 기존 가드 로직 유지(avif/webp/png 3변형 시도)
- R2 URL: `r2_image_base` 포함 시 항상 `<picture>` 렌더(존재 검사 생략)

### 6.4 post-card 썸네일(`thumb-og-*`) 표면

`_includes/post-card.html`(home/category 리스팅 카드)은 `post.image`의 `/og-`를 `/thumb-og-`로
치환한 **별도 썸네일 에셋**을 렌더한다. R2 컷오버 시 카드가 깨지지 않도록:
- post-card도 R2 인지(R2 thumb URL이면 존재 검사 생략하고 `<picture>` 렌더) — 적용됨.
- `migrate_images_to_r2 --apply`가 main(og-*) 3변형 **및** 썸네일(thumb-og-*) 3변형을 **모두**
  업로드 성공한 경우에만 `image:`를 CDN URL로 치환 — 적용됨(부분 실패 시 skip).
- `post.image`에 `/og-`가 없는 포스트(예 `news-briefing-*`)는 카드가 main 이미지를 썸네일로
  쓰므로 thumb-og 추가 업로드 불필요(main 3변형으로 충분).

## 7. 시크릿

- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`
- GitHub Actions secrets + 로컬 `.env`(커밋 금지). 미설정 시 graceful degradation.

## 구현 현황 (2026-06-10)

**Phase 1 착수 완료 (코드, 인프라 대기):**
- `scripts/common/asset_storage.py` — R2 미러 모듈. `is_enabled()`/`upload_file()`/
  `mirror_generated_variants()`/`public_url()`. 시크릿/boto3 부재 시 **완전 no-op**(절대 raise 안 함).
- `scripts/common/image_generator/base.py::_save_and_close` — 변형 저장 직후 `_mirror_to_remote()`
  훅(try/except 래핑, 생성 파이프라인 절대 차단 안 함). 모든 generated 이미지의 공통 chokepoint.
- `scripts/requirements.txt` — `boto3` 추가(미설치 시 graceful).
- `tests/test_asset_storage.py` — 19개(mock boto3): graceful no-op/업로드 파라미터/예외 삼킴/배선.

**검증됨**: 모듈 로직(mock), no-op이 기존 이미지 생성 222개 + 전체 4632 테스트 무회귀.
**미검증(인프라 대기)**: 실제 R2 업로드 — R2_* 시크릿/버킷 미프로비저닝.
**미적용(다음 단계)**: 포스트 `image:`를 CDN URL로 전환(`public_url` 헬퍼는 준비됨, generator 반환부
배선은 CDN 도메인 검증 후). 현재는 R2로 **미러만**(시크릿 설정 시), 사이트는 여전히 로컬 경로 참조.

---

**Phase 2 게이티드 코드 랜딩 (2026-06-11):**

- **`scripts/common/post_generator.py::_resolve_post_image` 배선** — `asset_storage.public_url()`
  호출을 삽입. `is_enabled()` 게이트로 보호: R2 활성 시 생성 포스트의 `image:` 필드가 절대 CDN URL
  (`R2_PUBLIC_BASE_URL/generated/<filename>`)을 반환, 비활성 시 기존 로컬 상대경로 반환(no-op).
  시크릿 미설정 환경에서 동작 변화 없음.

- **`scripts/migrate_images_to_r2.py` 신규 추가** — 기존 포스트 `image:` 일괄 이전 스크립트.
  `--dry-run`(기본): 이전 대상 포스트·URL 목록만 출력. `--apply`: `is_enabled()` 게이트 통과 후
  R2 업로드 + `image:` 절대 URL 치환. 로컬에 파일이 존재하는 이미지만 처리(소실분 skip).
  치환은 원자적 쓰기+백업으로 안전. `_state/*.json` 미수정.

- **`cleanup-old-images.yml` 폐지 예정 주석 추가** — 현재 워크플로우 동작 불변,
  R2 전환 완료(Phase 4) 후 비활성 예정임을 주석으로 기재.

**이 단계의 범위와 한계:**
- 시크릿 미설정 시 세 변경 모두 완전 no-op → **무중단 배포**.
- 인프라 프로비저닝(R2 버킷/커스텀 도메인/시크릿 등록)은 이 단계에 포함되지 않음(후속 게이트).
- 실제 포스트 CDN URL 전환(`--apply` 실행), `.gitignore` 추가, `cleanup-old-images.yml` 폐지는
  인프라 검증 후 별도 단계에서 수행.
- **도메인 결정 사항**: 커스텀 도메인(예: `img.2twodragon.com`) 또는 R2 기본 URL 선택은
  `R2_PUBLIC_BASE_URL` 환경 변수 값으로만 반영되며 코드 변경 불필요.
- 미검증(인프라 대기): 실제 R2 업로드 경로, CDN URL 접근성.

## 8. 롤아웃 단계 (무중단)

1. R2 버킷+커스텀 도메인+CDN 구성, 시크릿 등록.
2. ✅ (완료) `asset_storage.py` 추가 + `image_generator` 통합 (graceful degradation) → **신규 생성분 R2 미러**.
   ✅ (완료) `post_generator._resolve_post_image`에 `public_url()` 배선 — R2 활성 시 절대 CDN URL 반환(is_enabled 게이트).
   ✅ (완료) `migrate_images_to_r2.py` 스크립트 추가(dry-run 기본, --apply는 is_enabled 게이트).
   ✅ (완료) `cleanup-old-images.yml`에 폐지 예정 주석 추가(동작 불변).
3. 1~2주 운영 관찰(업로드 성공률, CDN 캐시 적중, 비용).
4. **선행 완료 확인**:
   - ✅ 템플릿 가드 R2 확장(`_includes/generated-picture.html`, `_layouts/default.html`, `_layouts/post.html`에
     `r2_image_base` 인식 추가, 절대 URL은 존재 검사 생략, 로컬 경로는 기존 로직 유지)
   - ✅ 3변형 업로드 게이트 구현(`asset_storage.py`, `image_generator`)

   그 후 `migrate_images_to_r2.py --dry-run` → 검토 → `--apply`로 현존 이미지 일괄 이전:

   **3변형 업로드 게이트**:
   `--apply` 실행 시 `migrate_images_to_r2.py`는 png/webp/avif **3변형 모두 로컬 존재 + 모두 업로드 성공**
   확인 후에만 포스트 `image:` 필드를 절대 CDN URL로 치환.
   부분 업로드(예: avif만 성공) 시 `image:` 치환 안 함 → 존재 안 하는 `<source>` 참조 방지.
   검증: 치환 후 `python scripts/check_post_images.py`(R2 HEAD 체크로 확장) + `bundle exec jekyll build`.
5. `assets/images/generated/` gitignore + 트래킹 제거(`git rm --cached`), `cleanup-old-images.yml` 비활성.
6. `check_post_images.py`/회귀 테스트를 R2 HEAD 체크로 확장.

## 9. 리스크 / 비결정 사항

- **R2 가용성**: 이미지 호스팅이 외부 의존 → CDN 캐시 + 폴백(가드 유지)로 완화.
- **비용**: 스토리지 누적(연 ~2.6GB 추가)은 R2 기준 월 수 센트 수준, egress 무료 → 무시 가능.
- **검색엔진 og:image 도메인 변경**: 절대 URL 도메인이 바뀌므로 일부 재크롤 필요(점진).
- **결정 필요(사용자)**: (a) 커스텀 도메인 사용 여부, (b) 옛 정리분 폴백 수용 여부(재생성 불가),
  (c) R2 vs S3 최종 선택.

## 참고
- 상위: `docs/design-generated-image-lifecycle.md`
- 1차 가드/테스트: `_includes/generated-picture.html`, `tests/test_generated_image_guard.py`
- 통합 지점: `scripts/common/image_generator.py`, `scripts/common/post_generator.py`
- 메모리: `project_generated_image_pruning_guard`
