import json
import subprocess
from pathlib import Path

import pytest

from scripts.configure_github_auth import main


def test_docker_install_layers_mount_configure_and_cleanup_owner_tokens():
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text(encoding="utf-8")
    install_layers = dockerfile.split("RUN --mount=type=secret,id=gh_pat \\\n")[1:]

    assert len(install_layers) == 11
    for layer in install_layers:
        install_layer = layer.split("\nRUN ", 1)[0]
        assert "id=openbase_github_tokens_json" in install_layer
        assert install_layer.index(
            "configure_github_auth.py configure"
        ) < install_layer.index("uv ")
        assert install_layer.index("uv ") < install_layer.index(
            "configure_github_auth.py cleanup"
        )


def test_configure_and_cleanup_owner_specific_rewrites(tmp_path, monkeypatch):
    secret_path = tmp_path / "github-tokens.json"
    secret_path.write_text(
        json.dumps(
            {
                "big-help-ai": "big-help-token",
                "montaguegabe": "montague-token",
            }
        ),
        encoding="utf-8",
    )
    global_config = tmp_path / "gitconfig"
    gh_pat_path = tmp_path / "gh-pat"
    gh_pat_path.write_text("legacy-token", encoding="utf-8")
    platform_token_path = tmp_path / "platform-token"
    platform_token_path.write_text("platform-token", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    secret_arguments = [
        "--secret-path",
        str(secret_path),
        "--gh-pat-path",
        str(gh_pat_path),
        "--platform-token-path",
        str(platform_token_path),
    ]

    assert main(["configure", *secret_arguments]) == 0
    configured = subprocess.run(
        ["/usr/bin/git", "config", "--global", "--get-regexp", r"^url\."],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "github.com/big-help-ai/" in configured
    assert "github.com/montaguegabe/" in configured
    assert "github.com/openbase-community/" in configured
    assert " https://github.com/\n" in configured

    assert main(["cleanup", *secret_arguments]) == 0
    result = subprocess.run(
        ["/usr/bin/git", "config", "--global", "--get-regexp", r"^url\."],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"owner/child": "super-secret-value"},
        {"owner": ""},
        {"owner": 123},
    ],
)
def test_rejects_invalid_secret_without_echoing_it(tmp_path, payload):
    secret_path = tmp_path / "github-tokens.json"
    secret_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        (TypeError, ValueError), match="GitHub owner-token secret"
    ) as raised:
        main(["configure", "--secret-path", str(secret_path)])

    assert "super-secret-value" not in str(raised.value)
