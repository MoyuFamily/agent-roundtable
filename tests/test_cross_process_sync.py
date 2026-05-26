from __future__ import annotations

import json
import time
from pathlib import Path
import pytest

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB


@pytest.fixture
def core_with_web(tmp_path):
    """Isolated RoundtableCore setup with web directory mocked to tmp_path."""
    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core = RoundtableCore(db)
    
    # We patch Path("/tmp") / "roundtable_web" to target tmp_path directly
    # by mocking Path inside core.py if possible, or we can structure the test
    # to mock Path("/tmp") / "roundtable_web" / discussion_id.
    # Actually, a simpler way is to patch the path constructed in core.py.
    return core


def test_cross_process_sync_flow(tmp_path, monkeypatch):
    """Test that cross-process calls synchronize findings and final summaries correctly."""
    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core = RoundtableCore(db)

    # Redirect Path("/tmp") / "roundtable_web" to our tmp_path
    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)

    # Monkeypatch the _get_web_dir inside core to use web_base_dir instead of /tmp/roundtable_web
    monkeypatch.setattr(core, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    # Now let's create a discussion with web=True (so discussion.json is created)
    participants = [
        {"profile": "alice", "role": "Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "display_name": "Bob"},
    ]
    
    # We patch WebPublisher to not run PM2 but write the actual discussion.json
    from roundtable.web_publisher import WebPublisher
    original_start_pm2 = WebPublisher._start_pm2
    monkeypatch.setattr(WebPublisher, "_start_pm2", lambda *args, **kwargs: None)
    monkeypatch.setattr(WebPublisher, "stop", lambda *args, **kwargs: None)

    res = core.create_discussion("Test topic", participants, web=True, max_rounds=2)
    disc_id = res["discussion_id"]
    
    # Discussion dir should be under web_base_dir / disc_id
    disc_web_dir = web_base_dir / disc_id
    assert disc_web_dir.exists()
    assert (disc_web_dir / "discussion.json").exists()

    # Now simulate a cross-process speaker (we clear _publishers to force fallback)
    core._publishers.clear()
    
    # 1. Speak Round 0 (coordinator opening)
    core.speak(disc_id, "coordinator", "Opening")
    
    # Read discussion.json and verify speeches
    disc_json_path = disc_web_dir / "discussion.json"
    data = json.loads(disc_json_path.read_text())
    assert len(data["speeches"]) == 1
    assert data["speeches"][0]["participant"] == "coordinator"
    
    # 2. Speak Round 1 speeches
    core.speak(disc_id, "alice", "Alice says hi")
    core.speak(disc_id, "bob", "Bob says hi")
    
    # Round 1 completes! But wait, findings are NOT added yet.
    # In fallback mode, round_summaries should be created but empty if no findings exist yet.
    data = json.loads(disc_json_path.read_text())
    assert data["status"] == "active"
    
    # 3. Add findings for Round 1 to database directly (simulating demo/runner behavior)
    conn = core.db.connect()
    try:
        core.db.add_finding(conn, disc_id, "consensus", "We agree on A", 1)
        core.db.add_finding(conn, disc_id, "disagreement", "We disagree on B", 1)
        core.db.calculate_convergence(conn, disc_id, 1)
    finally:
        conn.close()
        
    # Since findings are in DB, let's call speak for the next round (Round 2)
    # This should trigger synchronization of Round 1 findings to discussion.json and token_stream.jsonl!
    core.speak(disc_id, "alice", "Alice round 2")
    
    # Check discussion.json
    data = json.loads(disc_json_path.read_text())
    assert len(data["round_summaries"]) == 1
    assert data["round_summaries"][0]["round"] == 1
    assert len(data["round_summaries"][0]["consensus"]) == 1
    assert data["round_summaries"][0]["consensus"][0]["content"] == "We agree on A"
    assert len(data["round_summaries"][0]["disagreement"]) == 1
    assert data["round_summaries"][0]["disagreement"][0]["content"] == "We disagree on B"
    
    # Check token_stream.jsonl
    jsonl_path = disc_web_dir / "token_stream.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    
    # We should have a round_summary event for round 1
    rs_events = [e for e in events if e.get("type") == "round_summary"]
    assert len(rs_events) == 1
    assert rs_events[0]["round"] == 1
    assert len(rs_events[0]["consensus"]) == 1
    assert rs_events[0]["consensus"][0]["content"] == "We agree on A"
    
    # 4. Speak Bob's speech for Round 2, completing the discussion (max_rounds = 2)
    core.speak(disc_id, "bob", "Bob round 2")
    
    # Add findings for Round 2
    conn = core.db.connect()
    try:
        core.db.add_finding(conn, disc_id, "consensus", "We agree on C", 2)
        core.db.calculate_convergence(conn, disc_id, 2)
    finally:
        conn.close()
        
    # Conclude the discussion with a conclusion/verdict
    conclusion = "Final conclusion text"
    core.end_discussion(disc_id, conclusion=conclusion)
    
    # Verify final_summary is synchronized and not locked out by empty verdict
    data = json.loads(disc_json_path.read_text())
    assert data["status"] == "concluded"
    assert data["conclusion"] == conclusion
    assert data["final_summary"] is not None
    assert data["final_summary"]["verdict"] == conclusion
    # It should contain consensus from both round 1 and 2
    assert len(data["final_summary"]["consensus"]) == 2
    assert len(data["final_summary"]["disagreement"]) == 1
    
    # Check final events in token_stream.jsonl
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    fs_events = [e for e in events if e.get("type") == "final_summary"]
    assert len(fs_events) >= 1
    assert fs_events[-1]["verdict"] == conclusion
    assert len(fs_events[-1]["consensus"]) == 2
