"""The origin fetch survives its own quoting.

`scripts/origin_check.py` replaces a command that was hand-assembled ~35 times in
one week and nested three levels of shell deep:

    ssh homeserver "docker exec vb_nginx sh -c \"wget --header=\\\"Host: ...\\\" ...\""

Two things break silently in that form and both are what these tests pin. A
`Host:` header carries a space, so an under-quoted one splits into two argv
elements and nginx serves the default vhost instead of the site. A path carries
`?` and `&`, so an under-quoted one loses its query string to the remote shell —
and the page still returns 200, which is why nobody noticed.

The round-trip test is the load-bearing one: rather than pinning a literal
command string (which passes for whatever the code currently emits), it re-splits
the ssh argument the way the remote login shell will and asserts the remote argv
comes back byte-identical.
"""

import importlib.util
import shlex
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "origin_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("origin_check", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


oc = _load()


@pytest.mark.parametrize("path,expected", [
    ("/salaries/", "/salaries/"),
    ("salaries/", "/salaries/"),
    ("https://visa-bulletin.us/predictions/", "/predictions/"),
    ("http://visa-bulletin.us/a/?q=1&b=2", "/a/?q=1&b=2"),
    ("https://visa-bulletin.us", "/"),
])
def test_paths_are_normalised_to_origin_relative(path, expected):
    assert oc.normalize_path(path) == expected


def test_host_header_is_one_argv_element_with_its_space():
    argv = oc.remote_argv("/")
    header = [a for a in argv if a.startswith("--header=")]
    assert header == ["--header=Host: visa-bulletin.us"]


def test_no_nested_shell_to_escape_through():
    """`docker exec` takes argv directly — an inner `sh -c` is the bug, not the tool."""
    assert "sh" not in oc.remote_argv("/")
    assert "-c" not in oc.remote_argv("/")


def test_ssh_argument_resplits_to_exactly_the_remote_argv():
    """What the remote login shell reconstructs must equal what we meant to send."""
    for path in ("/", "/salaries/?q=ZZZ&state=NY", "/employer/o'brien-inc/"):
        remote = oc.remote_argv(path)
        wrapper = oc.local_argv(path, ssh_host="homeserver")
        assert wrapper[:3] == ["ssh", "-o", "BatchMode=yes"]
        assert wrapper[3] == "homeserver"
        assert shlex.split(wrapper[4]) == remote


def test_query_string_survives_the_ssh_hop():
    wrapper = oc.local_argv("/salaries/?q=ZZZ&state=NY", ssh_host="homeserver")
    assert shlex.split(wrapper[4])[-1] == "http://127.0.0.1:80/salaries/?q=ZZZ&state=NY"


def test_local_mode_runs_the_remote_argv_with_no_ssh_wrapper():
    assert oc.local_argv("/", ssh_host=None) == oc.remote_argv("/")


def test_staging_selects_its_own_container_and_vhost():
    argv = oc.remote_argv("/", env="staging")
    assert argv[2] == "vb_stg_nginx"
    assert "--header=Host: staging.visa-bulletin.us" in argv


def test_body_and_status_differ_only_in_the_output_sink():
    status = oc.remote_argv("/", body=False)
    body = oc.remote_argv("/", body=True)
    assert status[status.index("-O") + 1] == "/dev/null"
    assert body[body.index("-O") + 1] == "-"
    assert "-S" in body, "a body fetch still needs the status line to report a non-200"


def test_named_user_agent_expands_and_a_literal_one_passes_through():
    assert any("Googlebot" in a for a in oc.remote_argv("/", user_agent="googlebot"))
    assert "--user-agent=custom/1.0" in oc.remote_argv("/", user_agent="custom/1.0")
    assert not any(a.startswith("--user-agent=") for a in oc.remote_argv("/"))


@pytest.mark.parametrize("stderr,expected", [
    ("  HTTP/1.1 200 OK\n  Server: nginx\n", 200),
    ("  HTTP/1.1 301 Moved\n  HTTP/1.1 200 OK\n", 200),   # last hop of a redirect wins
    ("  HTTP/1.1 404 Not Found\n", 404),
    ("ssh: Could not resolve hostname\n", None),
    ("", None),
])
def test_status_is_read_from_the_last_response_line(stderr, expected):
    assert oc.parse_status(stderr) == expected
