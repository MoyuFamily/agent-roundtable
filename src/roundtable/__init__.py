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

from roundtable.adapters.generic import Roundtable
from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.exceptions import (
    DiscussionNotActiveError,
    DiscussionNotFoundError,
    InvalidFindingTypeError,
    InvalidParticipantError,
    InvalidReplyToError,
    InvalidSpeechOrderError,
    RoundtableError,
)
from roundtable.models import (
    ConvergenceRecord,
    Discussion,
    Finding,
    Participant,
    Speech,
)
from roundtable.notify import Notifier
from roundtable.web_publisher import WebPublisher

__version__ = "0.1.0"

__all__ = [
    "ConvergenceRecord",
    "Discussion",
    "DiscussionNotActiveError",
    "DiscussionNotFoundError",
    "Finding",
    "InvalidFindingTypeError",
    "InvalidParticipantError",
    "InvalidReplyToError",
    "InvalidSpeechOrderError",
    "Notifier",
    "Participant",
    "Roundtable",
    "RoundtableCore",
    "RoundtableDB",
    "RoundtableError",
    "Speech",
    "WebPublisher",
]
