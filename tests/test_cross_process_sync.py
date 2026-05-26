from __future__ import annotations

import json

import pytest

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB


def _worker_write_event(web_dir_path_str: str, worker_id: int, write_count: int) -> None:
    """Worker function to be run in concurrent processes to write JSONL events."""
    from pathlib import Path

    from roundtable.core import RoundtableCore
    from roundtable.db import RoundtableDB

    db = RoundtableDB(":memory:")
    core = RoundtableCore(db)
    web_dir = Path(web_dir_path_str)
    for i in range(write_count):
        event = {"worker": worker_id, "index": i, "data": "x" * 100}
        core._append_token_stream_jsonl_fallback(web_dir, event)


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


def test_cross_process_concurrent_writes(tmp_path):
    """Test that concurrent writes to token_stream.jsonl from multiple processes remain atomic and uncorrupted."""
    import multiprocessing

    web_dir = tmp_path / "web_dir"
    web_dir.mkdir()
    jsonl_path = web_dir / "token_stream.jsonl"
    # Pre-create the file
    jsonl_path.touch()

    num_workers = 4
    writes_per_worker = 50

    processes = []
    for w in range(num_workers):
        p = multiprocessing.Process(target=_worker_write_event, args=(str(web_dir), w, writes_per_worker))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    # Now read the lines and verify
    lines = jsonl_path.read_text().splitlines()
    assert len(lines) == num_workers * writes_per_worker

    # Parse each line to check if they are valid JSON and not corrupted/mangled
    counts = {}
    for line in lines:
        event = json.loads(line)
        worker = event["worker"]
        index = event["index"]
        counts.setdefault(worker, []).append(index)

    # Verify we got all events from all workers
    assert len(counts) == num_workers
    for w in range(num_workers):
        assert len(counts[w]) == writes_per_worker
        assert sorted(counts[w]) == list(range(writes_per_worker))


def test_sync_convergence_score_only(tmp_path, monkeypatch):
    """Test that convergence_score is synchronized even if consensus/disagreement points are unchanged."""
    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core = RoundtableCore(db)

    # Redirect Path("/tmp") / "roundtable_web" to our tmp_path
    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    # Patch WebPublisher to avoid PM2
    from roundtable.web_publisher import WebPublisher

    monkeypatch.setattr(WebPublisher, "_start_pm2", lambda *args, **kwargs: None)
    monkeypatch.setattr(WebPublisher, "stop", lambda *args, **kwargs: None)

    participants = [
        {"profile": "alice", "role": "Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "display_name": "Bob"},
    ]
    res = core.create_discussion("Topic", participants, web=True, max_rounds=2)
    disc_id = res["discussion_id"]
    disc_web_dir = web_base_dir / disc_id
    disc_json_path = disc_web_dir / "discussion.json"

    # 1. Add finding in database
    conn = core.db.connect()
    try:
        core.db.add_finding(conn, disc_id, "consensus", "Agreement Point", 1)
    finally:
        conn.close()

    # 2. Sync to write the initial round summary (no convergence score in DB yet)
    conn = core.db.connect()
    try:
        core._sync_web_discussion_state(disc_id, conn)
    finally:
        conn.close()

    # Verify existing round summary does NOT have convergence_score
    data = json.loads(disc_json_path.read_text())
    assert len(data["round_summaries"]) == 1
    assert "convergence_score" not in data["round_summaries"][0]

    # 3. Add convergence score to the database (consensus/disagreement points remain unchanged)
    conn = core.db.connect()
    try:
        core.db.calculate_convergence(conn, disc_id, 1)
    finally:
        conn.close()

    # 4. Sync again
    conn = core.db.connect()
    try:
        core._sync_web_discussion_state(disc_id, conn)
    finally:
        conn.close()

    # Verify convergence score is now synchronized!
    data = json.loads(disc_json_path.read_text())
    assert len(data["round_summaries"]) == 1
    assert data["round_summaries"][0]["convergence_score"] is not None


def test_cross_process_auto_conclude_replay_events(tmp_path, monkeypatch):
    """Test that status_delta concluded event is written to token_stream.jsonl on auto-conclude in fallback scenario."""
    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core = RoundtableCore(db)

    # Redirect Path("/tmp") / "roundtable_web" to our tmp_path
    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    # Patch WebPublisher to avoid PM2
    from roundtable.web_publisher import WebPublisher

    monkeypatch.setattr(WebPublisher, "_start_pm2", lambda *args, **kwargs: None)
    monkeypatch.setattr(WebPublisher, "stop", lambda *args, **kwargs: None)

    participants = [
        {"profile": "alice", "role": "Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "display_name": "Bob"},
    ]

    # max_rounds=2 (auto-conclude after round 2 completes)
    res = core.create_discussion("Topic", participants, web=True, max_rounds=2)
    disc_id = res["discussion_id"]
    disc_web_dir = web_base_dir / disc_id
    disc_json_path = disc_web_dir / "discussion.json"
    jsonl_path = disc_web_dir / "token_stream.jsonl"

    # Now clear publisher to simulate fallback (cross-process)
    core._publishers.clear()

    # Speak speeches for Round 0, 1, 2 to complete discussion
    core.speak(disc_id, "coordinator", "Opening")
    core.speak(disc_id, "alice", "Round 1 alice")
    core.speak(disc_id, "bob", "Round 1 bob")
    core.speak(disc_id, "alice", "Round 2 alice")
    result = core.speak(disc_id, "bob", "Round 2 bob")

    assert result["discussion_complete"] is True

    # Read events from discussion.json and token_stream.jsonl
    data = json.loads(disc_json_path.read_text())
    assert data["status"] == "concluded"

    # Verify status_delta concluded event exists in discussion.json
    events_in_json = data.get("events", [])
    status_events_in_json = [e for e in events_in_json if e.get("type") == "status_delta"]
    assert len(status_events_in_json) >= 1
    assert status_events_in_json[-1]["status"] == "concluded"

    # Verify status_delta concluded event exists in token_stream.jsonl
    events_in_jsonl = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    status_events_in_jsonl = [e for e in events_in_jsonl if e.get("type") == "status_delta"]
    assert len(status_events_in_jsonl) >= 1
    assert status_events_in_jsonl[-1]["status"] == "concluded"


def test_reconclusion_updates_verdict(tmp_path, monkeypatch):
    """Test that re-concluding a discussion with a new conclusion updates final_summary.verdict."""
    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core = RoundtableCore(db)

    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    from roundtable.web_publisher import WebPublisher

    monkeypatch.setattr(WebPublisher, "_start_pm2", lambda *args, **kwargs: None)
    monkeypatch.setattr(WebPublisher, "stop", lambda *args, **kwargs: None)

    participants = [
        {"profile": "alice", "role": "Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "display_name": "Bob"},
    ]
    res = core.create_discussion("Topic", participants, web=True, max_rounds=2)
    disc_id = res["discussion_id"]
    disc_web_dir = web_base_dir / disc_id
    disc_json_path = disc_web_dir / "discussion.json"

    # Conclude with first conclusion (publisher is alive)
    core.end_discussion(disc_id, conclusion="旧结论")

    data = json.loads(disc_json_path.read_text())
    assert data["conclusion"] == "旧结论"
    assert data["final_summary"]["verdict"] == "旧结论"

    # Re-conclude with new conclusion text
    core.end_discussion(disc_id, conclusion="新结论")

    data = json.loads(disc_json_path.read_text())
    assert data["conclusion"] == "新结论"
    assert data["final_summary"]["verdict"] == "新结论"


def test_live_publisher_round_summary_has_convergence_score(tmp_path, monkeypatch):
    """Test that live publisher writes convergence_score in round_summaries and doesn't produce duplicate events."""
    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core = RoundtableCore(db)

    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    from roundtable.web_publisher import WebPublisher

    monkeypatch.setattr(WebPublisher, "_start_pm2", lambda *args, **kwargs: None)
    monkeypatch.setattr(WebPublisher, "stop", lambda *args, **kwargs: None)

    participants = [
        {"profile": "alice", "role": "Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "display_name": "Bob"},
    ]
    res = core.create_discussion("Topic", participants, web=True, max_rounds=3)
    disc_id = res["discussion_id"]
    disc_web_dir = web_base_dir / disc_id
    disc_json_path = disc_web_dir / "discussion.json"
    jsonl_path = disc_web_dir / "token_stream.jsonl"

    # Publisher is alive (do NOT clear _publishers)
    core.speak(disc_id, "coordinator", "Opening")
    core.speak(disc_id, "alice", "Round 1 alice")

    # Add findings BEFORE the round-completing speak so calculate_convergence returns a real score
    conn = core.db.connect()
    try:
        core.db.add_finding(conn, disc_id, "consensus", "We agree on X", 1)
        core.db.add_finding(conn, disc_id, "disagreement", "We disagree on Y", 1)
    finally:
        conn.close()

    core.speak(disc_id, "bob", "Round 1 bob")

    # After round 1 completes, check that convergence_score is in discussion.json
    data = json.loads(disc_json_path.read_text())
    assert len(data["round_summaries"]) == 1
    assert "convergence_score" in data["round_summaries"][0]
    assert data["round_summaries"][0]["convergence_score"] is not None

    # Count round_summary events for round 1 in token_stream.jsonl
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    r1_events_before = [e for e in events if e.get("type") == "round_summary" and e.get("round") == 1]

    # Speak again in round 2 — this should NOT produce a duplicate round 1 summary event
    core.speak(disc_id, "alice", "Round 2 alice")

    # Re-read and verify no duplicate round 1 summary events appeared
    data = json.loads(disc_json_path.read_text())
    assert "convergence_score" in data["round_summaries"][0]

    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    r1_events_after = [e for e in events if e.get("type") == "round_summary" and e.get("round") == 1]
    assert len(r1_events_after) == len(r1_events_before)


def test_concurrent_speeches_are_all_preserved_in_json(tmp_path, monkeypatch):
    """Test that concurrent speak calls (cross-process fallback paths) do not overwrite each other."""
    import concurrent.futures

    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core = RoundtableCore(db)

    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    participants = [{"profile": f"user_{i}", "role": "Engineer", "display_name": f"User {i}"} for i in range(10)]
    res = core.create_discussion("Topic", participants, web=True, max_rounds=20)
    disc_id = res["discussion_id"]
    disc_web_dir = web_base_dir / disc_id
    disc_json_path = disc_web_dir / "discussion.json"

    # Make sure _publishers doesn't have it (so it uses fallback cross-process path)
    core._publishers.pop(disc_id, None)

    # 1. Coordinator opening statement to advance to round 1
    core.speak(disc_id, "coordinator", "Let's begin.")

    # Let's perform 10 concurrent speeches from different participants.
    # Each thread will use a separate RoundtableCore instance sharing
    # the same RoundtableDB to simulate multi-process/multi-client environment.
    cores = [RoundtableCore(db) for _ in range(10)]
    for c in cores:
        monkeypatch.setattr(c, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)
        c._publishers.pop(disc_id, None)

    def run_speak(idx):
        cores[idx].speak(disc_id, f"user_{idx}", f"speech from {idx}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(run_speak, i) for i in range(10)]
        concurrent.futures.wait(futures)

    # Verify no exceptions were raised
    for f in futures:
        f.result()

    # Verify that all 10 speeches (plus the coordinator opening statement) are preserved in discussion.json
    data = json.loads(disc_json_path.read_text())
    contents = [s["content"] for s in data.get("speeches", [])]

    # 10 user speeches + 1 coordinator opening
    assert len(contents) == 11
    assert "Let's begin." in contents
    for i in range(10):
        assert f"speech from {i}" in contents


def test_live_publisher_does_not_overwrite_fallback_speech(tmp_path, monkeypatch):
    """Test that live publisher and fallback writer mixed-writes are merged properly without losing data."""
    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core_live = RoundtableCore(db)
    core_fallback = RoundtableCore(db)

    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core_live, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)
    monkeypatch.setattr(core_fallback, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    from roundtable.web_publisher import WebPublisher

    monkeypatch.setattr(WebPublisher, "_start_pm2", lambda *args, **kwargs: None)
    monkeypatch.setattr(WebPublisher, "stop", lambda *args, **kwargs: None)

    participants = [
        {"profile": "alice", "role": "Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "display_name": "Bob"},
    ]
    res = core_live.create_discussion("Topic", participants, web=True, max_rounds=5)
    disc_id = res["discussion_id"]
    disc_web_dir = web_base_dir / disc_id
    disc_json_path = disc_web_dir / "discussion.json"

    # core_live retains the live publisher (in memory)
    # core_fallback acts as fallback writer (no publisher in memory)
    core_fallback._publishers.pop(disc_id, None)

    # 1. Live publisher writes opening
    core_live.speak(disc_id, "coordinator", "Opening speech")

    # 2. Fallback writer writes speech B
    core_fallback.speak(disc_id, "alice", "Fallback speech")

    # 3. Live publisher writes speech C
    core_live.speak(disc_id, "bob", "Live speech")

    # Verify that both fallback and live speeches are preserved
    data = json.loads(disc_json_path.read_text())
    contents = [s["content"] for s in data.get("speeches", [])]

    assert "Fallback speech" in contents
    assert "Live speech" in contents
    assert "Opening speech" in contents


def test_stale_live_publisher_does_not_revert_fallback_conclusion(tmp_path, monkeypatch):
    """Test that a stale live publisher update does not revert a newer conclusion written by fallback sync."""
    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core_live = RoundtableCore(db)
    core_fallback = RoundtableCore(db)

    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core_live, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)
    monkeypatch.setattr(core_fallback, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    from roundtable.web_publisher import WebPublisher

    monkeypatch.setattr(WebPublisher, "_start_pm2", lambda *args, **kwargs: None)
    monkeypatch.setattr(WebPublisher, "stop", lambda *args, **kwargs: None)

    participants = [
        {"profile": "alice", "role": "Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "display_name": "Bob"},
    ]
    res = core_live.create_discussion("Topic", participants, web=True, max_rounds=5)
    disc_id = res["discussion_id"]
    disc_web_dir = web_base_dir / disc_id
    disc_json_path = disc_web_dir / "discussion.json"

    # core_live retains the live publisher (in memory)
    # core_fallback acts as fallback writer (no publisher in memory)
    core_fallback._publishers.pop(disc_id, None)

    # 1. Live publisher ends the discussion with "旧结论"
    # This writes conclusion="旧结论" with t1
    core_live.end_discussion(disc_id, conclusion="旧结论")

    # 2. Fallback updates conclusion to "新结论"
    # This writes conclusion="新结论" with t2 (where t2 > t1)
    core_fallback.end_discussion(disc_id, conclusion="新结论")

    # 3. Simulate a stale live publisher write using its old in-memory state
    # Under old logic, this would revert the disk's conclusion/final_summary to "旧结论"
    publisher = core_live._publishers[disc_id]
    publisher._write_discussion_json()

    # Verify that the conclusion and final summary verdict remain "新结论"
    data = json.loads(disc_json_path.read_text())
    assert data["conclusion"] == "新结论"
    assert data["final_summary"]["verdict"] == "新结论"


def test_stale_live_publisher_does_not_overwrite_newer_round_summary(tmp_path, monkeypatch):
    """Test that a stale live publisher update does not revert a newer round summary written on disk."""
    import time

    db_path = tmp_path / "roundtable.db"
    db = RoundtableDB(db_path)
    core_live = RoundtableCore(db)
    core_fallback = RoundtableCore(db)

    web_base_dir = tmp_path / "roundtable_web"
    web_base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core_live, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)
    monkeypatch.setattr(core_fallback, "_get_web_dir", lambda discussion_id: web_base_dir / discussion_id)

    from roundtable.web_publisher import WebPublisher

    monkeypatch.setattr(WebPublisher, "_start_pm2", lambda *args, **kwargs: None)
    monkeypatch.setattr(WebPublisher, "stop", lambda *args, **kwargs: None)

    participants = [
        {"profile": "alice", "role": "Engineer", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "display_name": "Bob"},
    ]
    res = core_live.create_discussion("Topic", participants, web=True, max_rounds=5)
    disc_id = res["discussion_id"]
    disc_web_dir = web_base_dir / disc_id
    disc_json_path = disc_web_dir / "discussion.json"

    # core_live retains the live publisher (in memory)
    # core_fallback acts as fallback writer (no publisher in memory)
    core_fallback._publishers.pop(disc_id, None)

    publisher = core_live._publishers[disc_id]

    t1 = time.time()
    t2 = t1 + 10.0

    # 1. Live publisher writes round 1 summary with older timestamp t1 and no score
    publisher.on_round_summary(summary={"consensus": [{"content": "Live Consensus"}], "timestamp": t1}, round_num=1)

    # 2. Simulate fallback writer updating the disk with a newer round summary (with convergence_score and timestamp t2)
    # Read existing
    data = json.loads(disc_json_path.read_text())
    # Modify round 1 summary
    for r_s in data.get("round_summaries", []):
        if r_s.get("round") == 1:
            r_s["convergence_score"] = 0.83
            r_s["timestamp"] = t2
    # Write back
    disc_json_path.write_text(json.dumps(data, indent=2))

    # 3. Live publisher triggers a write using its old in-memory state (where round 1 has t1 and no score)
    publisher._write_discussion_json()

    # 4. Verify that the newer round 1 summary with convergence_score and t2 is retained on disk
    data = json.loads(disc_json_path.read_text())
    round_summaries = data.get("round_summaries", [])
    assert len(round_summaries) == 1
    assert round_summaries[0]["round"] == 1
    assert round_summaries[0]["convergence_score"] == 0.83
    assert round_summaries[0]["timestamp"] == t2
