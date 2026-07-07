# R2 이미지 오프로딩 — 프로비저닝 단계별 가이드

> 목적: 생성 이미지(`assets/images/generated/*`)를 Cloudflare R2로 오프로딩해 `.git` 비대(2026-06 기준 ~1.7GB, 93.7%가 이미지 blob churn)를 근본 해소한다.
> 관련 문서: 설계 `docs/design-image-offloading-r2.md` / 라이프사이클 `docs/design-generated-image-lifecycle.md` / history reclaim 플랜 `.omc/plans/git-history-image-blob-reclaim.md`
> 코드: `scripts/common/asset_storage.py`, `scripts/migrate_images_to_r2.py`
> 위키(실측·결정): `.omc/wiki/r2-q1-q2-2026-07-05.md`, `.omc/wiki/q2-404-safe-2026-07-05-661.md`, `.omc/wiki/r2-strip-b-og.md`

## 확정된 결정 (2026-07-05/06, 승인)

- **Q1 = 커스텀 도메인** (Step 2 옵션 A). r2.dev 반려(레이트리밋·브랜딩 종속). `R2_PUBLIC_BASE_URL` = 커스텀 도메인.
- **Q2 = 고아 이미지 제거**(마이그레이션 안 함). 실측 진짜 고아 **661개**(무참조 대시보드 스냅샷; og-/thumb- 파생 740은 고아 아님). **제거는 라이브 표면 404-safe로 검증됨** — sitemap-images/feed는 `site.posts × post.image` 순회(디렉토리 글롭 없음), og/hero/related는 `page.image` 파생 + `static_files` 존재 가드(부재 시 site 기본값 폴백). 상세: `q2-404-safe-2026-07-05-661.md`.
- **재발 방지 배선(2026-07-06 완료)**: `generate_market_summary.py` 자동화 은퇴(server cron 호출 제거 + 워크플로우 삭제) + 0-tracked 대시보드 고아 패턴 `.gitignore` 등록. 즉 Step 4의 "이미지 생성 워크플로우" 목록에서 market summary는 제외됐다.

## 0. 핵심 동작 — 게이트 뒤 no-op

코드는 **이미 main에 랜딩 완료**되어 있고, 아래 5개 환경변수가 **전부** 설정되기 전까지 전 구간이 no-op이다.

- `asset_storage.is_enabled()` → 5개 키가 모두 truthy일 때만 `True` (`asset_storage.py:54`).
- 비활성 시 `public_url()`은 로컬 경로(`/assets/images/generated/<name>`)를 반환 → 사이트 동작 불변.
- 따라서 **시크릿을 설정하는 순간** 신규 생성 이미지 미러링과 포스트 CDN URL 치환이 동시에 켜진다. 점진 검증을 위해 단계 순서를 지킬 것.

필수 5개 키 (`asset_storage.py:41`):

| 키 | 값 | 비고 |
|---|---|---|
| `R2_ACCOUNT_ID` | Cloudflare 계정 ID | 엔드포인트 `https://<id>.r2.cloudflarestorage.com` 에 사용 |
| `R2_ACCESS_KEY_ID` | R2 API 토큰의 Access Key ID | Step 3 |
| `R2_SECRET_ACCESS_KEY` | R2 API 토큰의 Secret | Step 3 · **시크릿** |
| `R2_BUCKET` | 버킷 이름 (예: `investing-generated`) | Step 1 |
| `R2_PUBLIC_BASE_URL` | 공개 베이스 URL (예: `https://img.2twodragon.com`) | **끝에 `/generated` 미포함** — 코드가 자동 부착 |

> 객체는 `generated/<filename>` 키로 저장되고 `{R2_PUBLIC_BASE_URL}/generated/<filename>` 로 서빙된다 (`_KEY_PREFIX = "generated/"`).

---

## Step 1 — R2 버킷 생성

1. Cloudflare 대시보드 → **R2** → **Create bucket**.
2. 이름: `investing-generated` (소문자/하이픈). 지역: **Automatic**.
3. 생성 후 버킷 이름을 `R2_BUCKET` 값으로 기록.

## Step 2 — 공개 접근 (커스텀 도메인 권장)

R2 객체를 공개로 서빙하는 두 가지 방법 중 하나:

**(A) 커스텀 도메인 (권장)** — 도메인이 Cloudflare DNS에 있어야 함
1. 버킷 → **Settings** → **Public access** → **Custom Domains** → **Connect Domain**.
2. 서브도메인 입력 (예: `img.2twodragon.com`). Cloudflare가 CNAME을 자동 생성.
3. 활성화 후 `R2_PUBLIC_BASE_URL = https://img.2twodragon.com`.

**(B) r2.dev 개발 URL (임시 검증용)**
1. 버킷 → **Settings** → **Public access** → **Allow Access** (`*.r2.dev`).
2. 제공된 `https://pub-xxxx.r2.dev` 를 `R2_PUBLIC_BASE_URL` 로 사용.
3. r2.dev는 rate-limit/캐싱 제약이 있어 **운영 전 커스텀 도메인으로 전환** 권장.

> 캐싱: 파일명이 날짜 스탬프로 사실상 불변이라 `Cache-Control: public, max-age=31536000, immutable` 로 업로드된다 (`asset_storage.py:_CACHE_CONTROL`). egress는 R2 특성상 무료.

## Step 3 — R2 API 토큰 발급

1. R2 → **Manage R2 API Tokens** → **Create API Token**.
2. 권한: **Object Read & Write**, 대상 버킷: `investing-generated` 만 지정(최소 권한).
3. 발급된 **Access Key ID** → `R2_ACCESS_KEY_ID`, **Secret Access Key** → `R2_SECRET_ACCESS_KEY`.
4. 계정 ID(대시보드 우측 또는 토큰 화면)를 `R2_ACCOUNT_ID` 로 기록.

> ⚠️ Secret은 발급 직후 한 번만 노출된다. 안전한 시크릿 매니저에 저장하고 평문 커밋 금지.

## Step 4 — 환경변수 등록

### 로컬 (마이그레이션 실행용)
프로젝트 `.env` (gitignore됨) 또는 셸 환경에 5개 키 설정. `config.get_env()` 가 읽는다.

```bash
export R2_ACCOUNT_ID=...
export R2_ACCESS_KEY_ID=...
export R2_SECRET_ACCESS_KEY=...
export R2_BUCKET=investing-generated
export R2_PUBLIC_BASE_URL=https://img.2twodragon.com
```

### GitHub Actions (신규 생성 이미지 자동 미러링용)
1. Repo → **Settings** → **Secrets and variables** → **Actions** → 5개 시크릿 등록.
   - `R2_PUBLIC_BASE_URL`, `R2_BUCKET` 은 비밀이 아니지만 일관성을 위해 시크릿 또는 변수로 등록.
2. 이미지를 생성하는 워크플로우(수집기 `collect_*`, `generate_*`)의 잡 `env:` 에 5개 키를 주입.
   미러링은 `image_generator/base.py:_save_and_close` 의 공통 chokepoint에서 일어나므로, 이미지를 만드는 모든 워크플로우에 노출돼야 신규분이 R2로 올라간다.
3. `boto3` 는 이미 `scripts/requirements.txt:23` (`boto3>=1.40,<2`) 에 포함 — 추가 설치 불필요.

### ⚠️ Jekyll 프론트 동기 (필수, 누락 시 hero 이미지 누락)
`R2_PUBLIC_BASE_URL` 을 켜는 것과 **동시에** `_config.yml:17` `r2_image_base` 를 설정해야 한다.
- 레이아웃(`_layouts/post.html`, `_layouts/default.html`, `_includes/generated-picture.html`)은 `image contains site.r2_image_base` 로 CDN URL을 원격으로 분류해 `static_files` 존재 가드를 건너뛴다.
- `r2_image_base` 가 빈 값이면 CDN URL(`https://.../generated/...`)이 원격으로도, 로컬(`/assets/images/generated/`)로도 매칭되지 않아 hero/og 이미지가 드롭될 수 있다.
- 값은 `R2_PUBLIC_BASE_URL` 의 substring이어야 한다 (예: `r2_image_base: "img.2twodragon.com"` 또는 `https://img.2twodragon.com`).

## Step 5 — 활성화 검증 (쓰기 없음)

```bash
# 5개 키 설정 상태에서:
PYTHONPATH=scripts python3 -c "from common import asset_storage as a; print('enabled:', a.is_enabled()); print(a.public_url('foo-2026-06-25.png'))"
# 기대: enabled: True / https://img.2twodragon.com/generated/foo-2026-06-25.png
```

마이그레이션 대상 dry-run (포스트/건수만 출력, 쓰기 없음):

```bash
PYTHONPATH=scripts python3 scripts/migrate_images_to_r2.py        # dry-run 기본
git status --porcelain                                            # clean 이어야 함
```

## Step 6 — 과거 포스트 마이그레이션 (`--apply`)

`is_enabled()` 가 `True` 여야만 실행된다(아니면 거부). 각 포스트의 로컬 이미지 3변형(png/webp/avif)을 업로드하고, **업로드 성공 시에만** 포스트 front matter `image:` 를 CDN URL로 원자적 치환한다(백업 동반). 실패 포스트는 skip.

```bash
PYTHONPATH=scripts python3 scripts/migrate_images_to_r2.py --apply
```

검증:
- `git diff -- _posts/ | grep 'image:'` → 치환된 포스트의 `image:` 가 CDN 절대 URL인지 확인.
- 변경 포스트 1~2개를 로컬 빌드/브라우저로 OG/hero 이미지 200 확인.
- 원본 소실(이미 정리된 ~1051건)은 로컬 파일이 없어 skip됨 → 레이아웃 가드 폴백 유지.

## Step 7 — cleanup 워크플로우 폐지 + 추적 중단

마이그레이션 `--apply` 성공 **이후에만** 진행:

1. `cleanup-old-images.yml` 제거 또는 `workflow_dispatch` 만 유지(이미 schedule 비활성).
2. `.gitignore` 에 `assets/images/generated/` 추가 (단, `git rm --cached` 전까지 빌드 소스로 필요하므로 컷오버 직후에).
3. `git rm -r --cached assets/images/generated/` → 추적 중단(워킹트리 파일은 유지). 신규 이미지는 R2로만 가고 git에 안 들어옴.
4. Vercel 빌드는 R2 CDN URL을 직접 참조하므로 로컬 이미지 불필요.

> 컷오버 순서가 핵심: R2에 이미지가 올라가기 **전에** git에서 지우면 빌드가 깨진다. `migrate --apply` 성공 + 빌드 검증 후에만 `git rm --cached`.

## Step 8 — git history reclaim (~1.05GB 회수, 비가역)

Step 7로 **앞으로의** churn은 멈추지만, 과거 history의 죽은 blob(~20,000개)은 그대로 남는다. 회수는 별도 force-push 캠페인:

- 플랜: `.omc/plans/git-history-image-blob-reclaim.md` (4차 critic APPROVE) + 컷오버→strip 시퀀스 `.omc/wiki/r2-strip-b-og.md` (시나리오 B).
- **전체 strip 도구 = `git filter-repo --invert-paths --path assets/images/generated/`.** BFG는 HEAD 보호로 현재분(HEAD 트리)을 못 지워 full strip에 부적합 → filter-repo 사용(미설치 시 설치가 게이트). BFG는 churn-only 축소에만 유효.
- strip은 **비가역** → 표본 아닌 **전수 검증**: 마이그레이션 후 잔존 `grep==0` + **실행 시점 라이브 grep으로 도출한 전체 참조 포스트**(2026-07-06 실측 1,879, 매일 증가 — 고정 수치 금지) ~6변형(main 3 + og-* thumb 3) **전수 curl 200** 확인 후에만 strip. V→S 구간 신규 포스트 자동화 동결 필수.
- 전 협업자 재클론 필요, force-push 전 자동화 크론 일시 중단 필수.
- **별도 승인·정비 윈도우에서 실행** (이 가이드 범위 밖).

---

## 알려진 제약 (활성화 후, PR #1041 리뷰 반영)

R2 활성화로 front matter `image:` 가 CDN 절대 URL이 되면서 생기는 비-blocking 동작 변화. 결함은 아니나 인지 필요:

- **`check_post_images.py:23` 이 CDN URL을 스킵한다.** `IMAGE_RE` 는 `/` 시작 값만 매칭하므로 `https://` CDN URL은 이미지 무결성/auto-heal 검사에서 제외된다 → 해당 포스트 커버리지 감소. (기존 `migrate_images_to_r2` 경로도 동일 URL을 생성하므로 신규 회귀 아님.)
- **generator 간 front matter URL 정책이 갈린다.** journal-OG 경로(`generate_og_images.py:637`)는 활성 시 CDN URL을 쓰지만 `backfill_images.py:568/575` 는 로컬 경로를 유지한다. 의도적(마이그레이션 스크립트가 backfill 산출물을 나중에 sweep) — 컷오버 시 backfill 산출물이 마이그레이션 대상에 포함되는지 확인.

## 롤백 / 안전성

- 어느 단계든 5개 시크릿을 제거하면 `is_enabled()=False` → 즉시 로컬 경로로 복귀(no-op). 단 이미 `--apply`로 CDN URL이 박힌 포스트는 되돌리려면 백업 복원 필요.
- 미러링·업로드는 전부 best-effort(예외를 삼켜 생성 hot path를 깨지 않음, `asset_storage.py:138`).

## 검증 체크리스트

- [ ] Step 4: `_config.yml` `r2_image_base` 가 `R2_PUBLIC_BASE_URL` substring으로 설정됨 (누락 시 hero 드롭)
- [ ] Step 5: `is_enabled()=True`, `public_url` 이 CDN URL 반환
- [ ] Step 5: dry-run 건수 > 0, `git status` clean
- [ ] Step 6: `--apply` 후 샘플 포스트 OG/hero 이미지 200
- [ ] Step 7: `git rm --cached` 후 빌드 그린 + 라이브 이미지 정상
- [ ] 신규 수집 1회 후 R2 버킷에 `generated/` 키 증가 확인
