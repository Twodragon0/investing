const BLOCKED_BASH_PATTERNS = [
  /\bgit\s+reset\s+--hard\b/i,
  /\bgit\s+clean\s+-fdx?\b/i,
  /\bgit\s+push\b.*\s--force(\b|$)/i,
  /\bgit\s+push\b.*\s\bmain\b/i,
  /\bgit\s+push\b.*\s\bmaster\b/i,
  /\brm\s+-rf\s+\/$/i,
  /\bsudo\b/i
]

const BLOCKED_READ_PATTERNS = [/\.env(\.|$)/i, /gcp-oauth\.keys\.json/i]

function matchesAny(value, patterns) {
  return patterns.some((pattern) => pattern.test(value))
}

function isAmbiguousGitPush(command) {
  const normalized = command.trim().replace(/\s+/g, " ")
  return /^git push( (?:-u|--set-upstream) \S+)?$/.test(normalized)
}

export const SafetyHooksPlugin = async () => {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool === "read") {
        const path = String(output.args?.filePath || "")
        if (path && matchesAny(path, BLOCKED_READ_PATTERNS)) {
          throw new Error(`Blocked read target by policy: ${path}`)
        }
      }

      if (input.tool === "bash") {
        const command = String(output.args?.command || "")
        if (isAmbiguousGitPush(command)) {
          throw new Error(
            "Blocked ambiguous git push. Push feature branches explicitly and never push directly from main/master."
          )
        }
        if (command && matchesAny(command, BLOCKED_BASH_PATTERNS)) {
          throw new Error(`Blocked bash command by policy: ${command}`)
        }
      }
    },
    "shell.env": async (_input, output) => {
      output.env.CI = output.env.CI || "1"
      output.env.TECH_BLOG_AUTO_YES = output.env.TECH_BLOG_AUTO_YES || "1"
      output.env.GIT_TERMINAL_PROMPT = output.env.GIT_TERMINAL_PROMPT || "0"
    }
  }
}
