"""Fail loudly if any model other than gpt-6-luna appears in the project.

The assignment deducts points if another model shows up in the code or runs.
This is cheap insurance against a stray copy-paste. Run it before committing:

    python scripts/check_model_guard.py

VARIANTS OF THE PERMITTED MODEL
-------------------------------
`gpt-6-luna` is the name we request. The platform answers in its own names, and
two of them show up in this repo without anyone choosing them:

* `gpt-6-luna-2026-09-22` — the dated snapshot returned in the `model` field of
  every API response, and therefore recorded against every step of the audit
  trail.
* `gpt-6-luna-global` — the Azure deployment name, which appears only inside an
  error message quoted in a docstring.

Both are the permitted model under a name the provider picked, so they are
accepted and reported separately rather than failing the check. Anything that
is not `gpt-6-luna` or `gpt-6-luna-<suffix>` is still a violation — the rule is
one model, and this keeps the check honest about which names it saw rather than
quietly broadening it.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = "gpt-6-luna"
# A provider-chosen variant: the permitted model plus a snapshot or deployment
# suffix. `gpt-6-lunar` or `gpt-6-luna2` would NOT match -- the separator is
# required, so a different model cannot sneak in on a prefix.
VARIANT = re.compile(rf"^{re.escape(ALLOWED)}-[\w.\-]+$", re.IGNORECASE)

# Anything that looks like a model identifier.
PATTERN = re.compile(
    r"\b(gpt-[\w.\-]+|o[1-9][\w.\-]*|claude-[\w.\-]+|gemini-[\w.\-]+"
    r"|llama-?[\w.\-]*|mistral-[\w.\-]+|deepseek-[\w.\-]+)\b",
    re.IGNORECASE,
)

SKIP_DIRS = {".git", "venv", "node_modules", "__pycache__", "dist", "data"}
# Lockfiles are machine-generated and full of base64 integrity hashes, which
# collide with the o-series model pattern by chance (e.g. "sha512-O5mpokth6...").
# A lockfile pins package versions and cannot express a model choice, so there
# is nothing here worth scanning.
SKIP_FILES = {
    "check_model_guard.py",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}
EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".toml", ".yaml", ".yml"}


def main() -> int:
    violations = []
    variants: dict[str, int] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in EXTS:
            continue
        if SKIP_DIRS & set(path.relative_to(ROOT).parts) or path.name in SKIP_FILES:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            for match in PATTERN.findall(line):
                low = match.lower()
                if low == ALLOWED:
                    continue
                if VARIANT.match(low):
                    variants[low] = variants.get(low, 0) + 1
                    continue
                rel = path.relative_to(ROOT)
                violations.append(f"  {rel}:{lineno}  {match}  |  {line.strip()[:90]}")

    if violations:
        print(f"FAIL: model identifiers other than '{ALLOWED}' found:\n")
        print("\n".join(violations))
        return 1

    print(f"PASS: '{ALLOWED}' is the only model in the project.")
    if variants:
        print("\nProvider-chosen variants of the same model (not violations):")
        for name, count in sorted(variants.items()):
            print(f"  {name:<26} {count} occurrence(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
