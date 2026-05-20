"""Data models for the Roundtable library.

Pure dataclasses with zero external dependencies — only stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Discussion:
    id: str
    topic: str
    context: Optional[str]
    status: str  # "active" | "concluded" | "cancelled"
    max_rounds: int
    current_round: int
    speech_order: str  # "fixed" | "random" | "priority" | "free"
    created_by: str
    created_at: int
    concluded_at: Optional[int]
    conclusion: Optional[str]
    convergence_score: Optional[float]
    output_path: Optional[str]


@dataclass
class Participant:
    discussion_id: str
    participant: str
    role: Optional[str]
    perspective: Optional[str]
    display_name: Optional[str]
    joined_at: int
    is_active: bool


@dataclass
class Speech:
    id: int
    discussion_id: str
    round: int
    participant: str
    content: str
    reply_to: Optional[int]
    created_at: int


@dataclass
class Finding:
    id: int
    discussion_id: str
    type: str  # "consensus" | "disagreement" | "new_point"
    content: str
    round: int
    related_speeches: Optional[List[int]]


@dataclass
class ConvergenceRecord:
    discussion_id: str
    round: int
    score: float
    consensus_count: int
    disagreement_count: int
    new_point_count: int
