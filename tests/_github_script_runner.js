// `actions/github-script` 본문을 목(mock) 환경에서 실행하는 하네스.
//
// 왜 있나: close-stale 스윕의 판정 로직 전부가 워크플로우 YAML 안의 JS 본문에 있다.
// 그 본문을 소스 텍스트로만 검사하면 **제어 흐름을 볼 수 없다** — 2026-09-13 실측에서
// `continue;` 한 줄을 지우자 사람이 트리아지한 이슈가 "kept" 로 기록되면서 동시에
// 닫히는 회귀가 만들어졌는데, 가드 15건이 전부 통과했다.
//
// 계약: stdin 으로 {script, env, issues} 를 받아 stdout 으로 관측 결과 JSON 을 낸다.
//   - closed:   update({state:'closed'}) 가 호출된 이슈 번호 (실제로 닫힌 것)
//   - commented: createComment 가 호출된 이슈 번호
//   - failed:    호출이 예외를 던진 이슈 번호
//   - summary:   core.summary.addRaw 로 쌓인 텍스트
//   - notices / warnings / failures: core.* 채널
//
// `closed` 가 이 하네스의 핵심이다. "요약에 뭐라고 적혔나"가 아니라 "실제로 무엇이
// 닫혔나"를 묻는다 — 위 회귀에서 그 둘이 어긋났다.

const chunks = [];
process.stdin.on('data', (c) => chunks.push(c));
process.stdin.on('end', async () => {
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const issues = input.issues || [];
  // 호출별로 예외를 던지게 하는 주입 지점 (실패 처리 경로 검증용).
  const failOn = new Set(input.failOnIssueNumbers || []);

  const observed = {
    closed: [],
    commented: [],
    failed: [],
    listArgs: null,
    paginateUsed: false,
    summary: '',
    notices: [],
    warnings: [],
    failures: [],
  };

  const listForRepo = (args) => {
    observed.listArgs = args;
    return issues;
  };

  const github = {
    paginate: async (fn, args) => {
      observed.paginateUsed = fn === listForRepo;
      return fn(args);
    },
    rest: {
      issues: {
        listForRepo,
        createComment: async ({ issue_number: n }) => {
          if (failOn.has(n)) throw new Error(`injected failure on #${n}`);
          observed.commented.push(n);
        },
        update: async ({ issue_number: n, state }) => {
          if (failOn.has(n)) throw new Error(`injected failure on #${n}`);
          if (state === 'closed') observed.closed.push(n);
        },
      },
    },
  };

  const core = {
    notice: (m) => observed.notices.push(String(m)),
    warning: (m) => observed.warnings.push(String(m)),
    setFailed: (m) => observed.failures.push(String(m)),
    summary: {
      addRaw: (t) => {
        observed.summary += String(t);
        return core.summary;
      },
      write: async () => core.summary,
    },
  };

  const context = {
    repo: { owner: 'probe-owner', repo: 'probe-repo' },
    runId: 12345,
    workflow: 'probe-workflow',
  };

  for (const [k, v] of Object.entries(input.env || {})) process.env[k] = String(v);

  // github-script 는 본문을 async 함수 몸통으로 감싼다. `return` 과 top-level
  // `await` 이 본문에 있으므로 같은 형태로 감싸야 동작이 같다.
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const fn = new AsyncFunction('github', 'context', 'core', 'require', input.script);
  try {
    await fn(github, context, core, require);
  } catch (error) {
    observed.uncaught = String(error && error.message);
  }

  // 예외를 던지도록 주입한 이슈 중 실제로 스크립트가 집계한 것.
  observed.failed = [...failOn].filter(
    (n) => observed.warnings.some((w) => w.includes(`#${n}`)),
  );

  process.stdout.write(JSON.stringify(observed));
});
