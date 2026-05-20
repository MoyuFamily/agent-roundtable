"""Roundtable — independent multi-agent discussion library.

A framework-agnostic Python package for structured roundtable discussions
between AI agents. Works standalone or integrates with any agent framework
via adapters.

Usage::

    from roundtable import RoundtableDB, RoundtableCore

    db = RoundtableDB()
    core = RoundtableCore(db)
    disc = core.create_discussion(topic="...", participants=[...])
"""

from roundtable.models import (
    ConvergenceRecord,
    Discussion,
    Finding,
    Participant,
    Speech,
)
from roundtable.db import RoundtableDB
from roundtable.core import RoundtableCore
from roundtable.exceptions import (
    RoundtableError,
    DiscussionNotFoundError,
    DiscussionNotActiveError,
    InvalidParticipantError,
    InvalidSpeechOrderError,
    InvalidFindingTypeError,
)

__version__ = "0.1.0"

__all__ = [
    "RoundtableDB",
    "RoundtableCore",
    "Discussion",
    "Participant",
    "Speech",
    "Finding",
    "ConvergenceRecord",
    "RoundtableError",
    "DiscussionNotFoundError",
    "DiscussionNotActiveError",
    "InvalidParticipantError",
    "InvalidSpeechOrderError",
    "InvalidFindingTypeError",
]
