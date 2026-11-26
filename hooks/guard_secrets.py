"""PreToolUse hook (Python 3.12): bloqueia Write/Edit que gravariam chaves privadas ou segredos no codigo.

Recebe o JSON do Claude Code via stdin. Sai com codigo 2 (bloqueio) e explica no stderr.
"""
import json
import re
import sys

PATTERNS = [
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "chave privada PEM"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{24,}", "API key (sk-...)"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}", "token GitHub"),
    (r"\bxox[abpr]-[A-Za-z0-9-]{10,}", "token Slack"),
    (r"(?i)\b(?:api[_-]?secret|secret[_-]?key|private[_-]?key|mt5[_-]?password|senha)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]", "segredo literal"),
    (r"\b0x[a-fA-F0-9]{64}\b", "chave privada de carteira (hex 64)"),
]


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", errors="replace"))
    except ValueError:
        return 0
    ti = data.get("tool_input") or {}
    path = str(ti.get("file_path", ""))
    if path.endswith((".env.example", ".md")):
        return 0
    chunks = [ti.get("content"), ti.get("new_string")]
    chunks += [e.get("new_string") for e in ti.get("edits") or [] if isinstance(e, dict)]
    text = "\n".join(c for c in chunks if isinstance(c, str))
    for pat, label in PATTERNS:
        if re.search(pat, text):
            print(f"[GRUPO BRESSAN BLINDAGEM] Bloqueado: {label} detectado em {path or 'arquivo'}. "
                  "Use variaveis de ambiente (.env, fora do git) em vez de gravar segredos no codigo.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
