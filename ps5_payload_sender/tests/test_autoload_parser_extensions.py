"""Tests for the wait_for_loader + notify directive extensions, and
for the per-flow ``# ~notify …`` header parsing/serialization."""
from __future__ import annotations

import pytest

from autoload_parser import (
    NotifyDirective,
    WaitForLoaderDirective,
    WaitPortDirective,
    parse_autoload_file,
    parse_line,
    parse_notify_config,
    render_notify_config,
    set_notify_config,
)


# ── wait_for_loader directive ────────────────────────────────────


def test_wfl_defaults():
    d = parse_line("??9021")
    assert isinstance(d, WaitForLoaderDirective)
    assert d.port == 9021
    assert d.max_wait_seconds == 10800.0
    assert d.interval_seconds == 30.0
    assert d.stability_count == 1


def test_wfl_full_form():
    d = parse_line("??9026 7200 15 2")
    assert isinstance(d, WaitForLoaderDirective)
    assert (d.port, d.max_wait_seconds, d.interval_seconds, d.stability_count) == (
        9026, 7200.0, 15.0, 2,
    )


def test_wfl_clamps_minimums():
    """interval < 1s and stability < 1 must be normalized."""
    d = parse_line("??9021 600 0.2 0")
    assert d.interval_seconds == 1.0
    assert d.stability_count == 1


def test_short_wait_port_still_works():
    """`?` must continue to parse to the short WaitPortDirective."""
    d = parse_line("?9021 60")
    assert isinstance(d, WaitPortDirective)
    assert d.timeout_seconds == 60.0


def test_double_question_does_not_match_short():
    """`??` must not accidentally parse as `?` with a junk port."""
    d = parse_line("??9021")
    assert isinstance(d, WaitForLoaderDirective)
    assert not isinstance(d, WaitPortDirective)


# ── notify directive ─────────────────────────────────────────────


def test_notify_title_only():
    d = parse_line('@notify "Loader ready"')
    assert isinstance(d, NotifyDirective)
    assert d.title == "Loader ready"
    assert d.message == ""
    assert d.service_override is None


def test_notify_with_message():
    d = parse_line('@notify "Hi" "world"')
    assert d.title == "Hi"
    assert d.message == "world"


def test_notify_with_service_override():
    d = parse_line('@notify "Done" "Body" notify.mobile_app_x')
    assert d.service_override == "notify.mobile_app_x"


def test_notify_third_arg_not_service_folds_into_message():
    """If the 3rd token isn't a notify.* override, it's just extra text."""
    d = parse_line('@notify "Done" "Body" extra_garbage')
    assert d.service_override is None


# ── ~notify header config ────────────────────────────────────────


def test_parse_notify_config_defaults():
    cfg = parse_notify_config("# no header\nfoo.elf\n")
    assert cfg == {
        "loader_ready":   True,
        "flow_started":   False,
        "flow_completed": True,
        "flow_failed":    True,
        "service":        "",
    }


def test_parse_notify_config_header():
    content = ('# ~notify loader_ready=off flow_started=on flow_completed=off '
               'flow_failed=on service="notify.mob"\n'
               'foo.elf\n')
    cfg = parse_notify_config(content)
    assert cfg["loader_ready"]   is False
    assert cfg["flow_started"]   is True
    assert cfg["flow_completed"] is False
    assert cfg["flow_failed"]    is True
    assert cfg["service"]        == "notify.mob"


def test_set_notify_config_inserts_when_missing():
    out = set_notify_config(
        "foo.elf\n",
        {"loader_ready": True, "flow_started": False,
         "flow_completed": True, "flow_failed": True, "service": "notify.foo"},
    )
    assert out.splitlines()[0].startswith("# ~notify")
    assert 'service="notify.foo"' in out


def test_set_notify_config_replaces_existing_in_place():
    src = "# ~notify loader_ready=off\nfoo.elf\n"
    out = set_notify_config(src, {"loader_ready": True, "flow_started": False,
                                  "flow_completed": True, "flow_failed": True,
                                  "service": ""})
    assert "loader_ready=on" in out
    # Still only one header
    assert out.count("# ~notify") == 1


def test_render_notify_config_round_trip():
    cfg = {
        "loader_ready": True, "flow_started": False,
        "flow_completed": True, "flow_failed": False,
        "service": "notify.x",
    }
    line = render_notify_config(cfg)
    # parsing the line back must yield the same config
    parsed = parse_notify_config(line + "\n")
    assert parsed == cfg


# ── full file integration ────────────────────────────────────────


def test_parse_full_file_with_new_step_types():
    content = (
        '# Created by Auto-Load Builder\n'
        '# ~notify loader_ready=on flow_completed=on service="notify.foo"\n'
        '# ~version kstuff.elf v1.2\n'
        'kstuff.elf\n'
        '??9021 7200 30 2\n'
        '@notify "Loader up" "Continuing flow"\n'
        '!1500\n'
        'kpayload.elf\n'
        '?9020 90 500\n'
    )
    steps = parse_autoload_file(content)
    types = [type(s).__name__ for s in steps]
    assert types == [
        "SendDirective", "WaitForLoaderDirective", "NotifyDirective",
        "DelayDirective", "SendDirective", "WaitPortDirective",
    ]


# ── invariants ───────────────────────────────────────────────────


def test_invalid_notify_lines_return_none():
    assert parse_line("@notify") is None
    assert parse_line("@notify ") is None


def test_invalid_wfl_returns_none():
    assert parse_line("??") is None
    assert parse_line("??abc") is None
