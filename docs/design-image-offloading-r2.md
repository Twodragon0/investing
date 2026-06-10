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

- 절대 R2 URL은 `site.static_files` 존재 체크가 불가능(로컬 파일 아님).
- 신규 이미지는 R2에 항상 존재하므로 가드 불필요. 단 **혼재 기간**(R2 URL + 옛 로컬 경로)에는
  현 가드가 로컬 경로만 체크 → 충돌 없음(절대 URL은 `contains '/assets/images/generated/'` 미일치).
- `og:image` avif/webp→png 정규화 로직은 R2 URL에도 동일 적용(도메인만 다름) — 검토 필요.

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

## 8. 롤아웃 단계 (무중단)

1. R2 버킷+커스텀 도메인+CDN 구성, 시크릿 등록.
2. `asset_storage.py` 추가 + `image_generator` 통합 (graceful degradation) → **신규 생성분만 R2로**.
3. 1~2주 운영 관찰(업로드 성공률, CDN 캐시 적중, 비용).
4. `migrate_images_to_r2.py --dry-run` → 검토 → `--apply`로 현존 이미지 일괄 이전.
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
