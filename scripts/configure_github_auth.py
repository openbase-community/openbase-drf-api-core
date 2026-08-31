import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

DEFAULT_SECRET_PATH = Path("/run/secrets/openbase_github_tokens_json")
DEFAULT_GH_PAT_PATH = Path("/run/secrets/gh_pat")
DEFAULT_PLATFORM_TOKEN_PATH = Path("/run/secrets/openbase_platform_github_token")
GITHUB_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def load_owner_tokens(secret_path: Path) -> dict[str, str]:
    if not secret_path.is_file():
        return {}
    payload = json.loads(secret_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = "GitHub owner-token secret must be a JSON object."
        raise TypeError(msg)

    owner_tokens = {}
    for owner, token in payload.items():
        normalized_owner = str(owner).strip().lower()
        if not GITHUB_OWNER_PATTERN.fullmatch(normalized_owner):
            msg = "GitHub owner-token secret contains an invalid owner."
            raise ValueError(msg)
        if not isinstance(token, str) or not token:
            msg = "GitHub owner-token secret contains an invalid token."
            raise ValueError(msg)
        owner_tokens[normalized_owner] = token
    return owner_tokens


def git_config_key(owner: str, token: str) -> str:
    encoded_token = quote(token, safe="")
    owner_path = f"{owner}/" if owner else ""
    return f"url.https://x-access-token:{encoded_token}@github.com/{owner_path}.insteadOf"


def load_optional_secret(secret_path: Path) -> str:
    if not secret_path.is_file():
        return ""
    return secret_path.read_text(encoding="utf-8").strip()


def github_rewrites(
    owner_tokens: dict[str, str],
    *,
    gh_pat: str = "",
    platform_token: str = "",
) -> list[tuple[str, str]]:
    rewrites = []
    if gh_pat:
        rewrites.append(("", gh_pat))
    if platform_token and "openbase-community" not in owner_tokens:
        rewrites.append(("openbase-community", platform_token))
    rewrites.extend(owner_tokens.items())
    return rewrites


def run_git_config(arguments: list[str], *, missing_is_ok: bool = False) -> None:
    result = subprocess.run(  # noqa: S603 - arguments are passed without a shell.
        ["/usr/bin/git", "config", "--global", *arguments],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0 or (missing_is_ok and result.returncode == 5):
        return
    msg = "Failed to update transient GitHub build authentication."
    raise RuntimeError(msg)


def configure(rewrites: list[tuple[str, str]]) -> None:
    for owner, token in rewrites:
        github_prefix = f"https://github.com/{owner}/" if owner else "https://github.com/"
        run_git_config(
            [
                "--replace-all",
                git_config_key(owner, token),
                github_prefix,
            ]
        )


def cleanup(rewrites: list[tuple[str, str]]) -> None:
    for owner, token in rewrites:
        run_git_config(
            ["--unset-all", git_config_key(owner, token)],
            missing_is_ok=True,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("configure", "cleanup"))
    parser.add_argument("--secret-path", type=Path, default=DEFAULT_SECRET_PATH)
    parser.add_argument("--gh-pat-path", type=Path, default=DEFAULT_GH_PAT_PATH)
    parser.add_argument(
        "--platform-token-path", type=Path, default=DEFAULT_PLATFORM_TOKEN_PATH
    )
    args = parser.parse_args(argv)
    owner_tokens = load_owner_tokens(args.secret_path)
    rewrites = github_rewrites(
        owner_tokens,
        gh_pat=load_optional_secret(args.gh_pat_path),
        platform_token=load_optional_secret(args.platform_token_path),
    )
    if args.action == "configure":
        configure(rewrites)
    else:
        cleanup(rewrites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
