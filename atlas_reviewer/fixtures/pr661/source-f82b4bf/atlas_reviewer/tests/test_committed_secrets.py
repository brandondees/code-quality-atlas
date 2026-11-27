# SPDX-License-Identifier: MIT
from atlas_reviewer.committed_secrets import CommittedSecret, scan_diff

from .helpers import fake_token


def test_each_hit_carries_the_file_line_on_its_side_and_never_the_value():
    token = fake_token("ghp_")
    old = fake_token("gho_")
    diff = (
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
        "@@ -10,4 +20,4 @@ def f():\n"
        " keep = 1\n"
        f"-OLD = '{old}'\n"
        f"+NEW = '{token}'\n"
        " done = 2\n"
        "\\ No newline at end of file\n"
    )
    scan = scan_diff(diff)
    assert scan.findings == (
        CommittedSecret("app.py", 11, "removed", "github-token"),
        CommittedSecret("app.py", 21, "added", "github-token"),
    )
    assert set(scan.values) == {old, token}
    assert token not in repr(scan) and old not in repr(scan)


def test_a_secret_on_a_context_line_and_in_a_header_are_located():
    value = "".join(chr(97 + i) for i in range(16))
    token = fake_token("ghp_")
    diff = (
        f"diff --git a/{token}.txt b/{token}.txt\n"
        "@@ -1,2 +1,3 @@\n"
        "+first\n"
        f' password = "{value}"\n'
    )
    assert scan_diff(diff).findings == (
        CommittedSecret(f"{token}.txt", None, "header", "github-token"),
        CommittedSecret(f"{token}.txt", 2, "context", "assignment"),
    )


def test_a_key_begin_in_one_file_never_pairs_with_an_end_in_another():
    begin = "-----BEGIN " + "RSA PRIVATE KEY-----"
    end = "-----END " + "RSA PRIVATE KEY-----"
    diff = (
        f"diff --git a/a.py b/a.py\n@@ -0,0 +1 @@\n+B = '{begin}'\n"
        "diff --git a/b.py b/b.py\n@@ -0,0 +1 @@\n+x = 1\n"
        f"diff --git a/c.py b/c.py\n@@ -0,0 +1 @@\n+E = '{end}'\n"
    )
    assert scan_diff(diff).findings == (
        CommittedSecret("a.py", 1, "added", "private-key-marker"),
    )


def test_a_diff_with_no_secrets_has_no_findings():
    assert scan_diff("diff --git a/x b/x\n@@ -1 +1 @@\n-a\n+b\n").findings == ()
