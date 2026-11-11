"""Keep ordinary core tests from starting the optional viewer process."""

from functools import wraps

import pytest

from roundtable.adapters.generic import Roundtable
from roundtable.core import RoundtableCore


@pytest.fixture(autouse=True)
def disable_web_viewer_by_default_in_tests(monkeypatch, request):
    if request.node.get_closest_marker("web_defaults"):
        return

    def default_to_disabled(method):
        @wraps(method)
        def call(*args, **kwargs):
            kwargs.setdefault("web", False)
            return method(*args, **kwargs)

        return call

    for cls, names in [
        (RoundtableCore, ("create_discussion", "run_demo")),
        (Roundtable, ("init", "create_discussion", "run_demo")),
    ]:
        for name in names:
            monkeypatch.setattr(cls, name, default_to_disabled(getattr(cls, name)))
