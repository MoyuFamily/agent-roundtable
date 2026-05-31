"""Pytest conftest — ensures src/ is on sys.path."""

import sys
from pathlib import Path

src = Path(__file__).resolve().parent.parent / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

import pytest
from roundtable.core import RoundtableCore
from roundtable.adapters.generic import Roundtable

@pytest.fixture(autouse=True)
def disable_web_viewer_by_default_in_tests(monkeypatch):
    """Override the default value of the web parameter to False in tests to avoid running PM2."""
    orig_core_create = RoundtableCore.create_discussion
    def patched_core_create(*args, **kwargs):
        if "web" not in kwargs:
            kwargs["web"] = False
        return orig_core_create(*args, **kwargs)
    monkeypatch.setattr(RoundtableCore, "create_discussion", patched_core_create)

    orig_core_demo = RoundtableCore.run_demo
    def patched_core_demo(*args, **kwargs):
        if "web" not in kwargs:
            kwargs["web"] = False
        return orig_core_demo(*args, **kwargs)
    monkeypatch.setattr(RoundtableCore, "run_demo", patched_core_demo)

    orig_gen_init = Roundtable.init
    def patched_gen_init(*args, **kwargs):
        if "web" not in kwargs:
            kwargs["web"] = False
        return orig_gen_init(*args, **kwargs)
    monkeypatch.setattr(Roundtable, "init", patched_gen_init)

    orig_gen_create = Roundtable.create_discussion
    def patched_gen_create(*args, **kwargs):
        if "web" not in kwargs:
            kwargs["web"] = False
        return orig_gen_create(*args, **kwargs)
    monkeypatch.setattr(Roundtable, "create_discussion", patched_gen_create)

    orig_gen_demo = Roundtable.run_demo
    def patched_gen_demo(*args, **kwargs):
        if "web" not in kwargs:
            kwargs["web"] = False
        return orig_gen_demo(*args, **kwargs)
    monkeypatch.setattr(Roundtable, "run_demo", patched_gen_demo)

