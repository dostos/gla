from gpa.eval.curation.journey import JourneyRow, SelectOutcome, ProduceOutcome, JudgeOutcome, TokenSpend, TerminalReason

def test_journey_row_full_commit_shape():
    row = JourneyRow(
        url="https://github.com/x/y/issues/1",
        run_id="2026-05-01-143022-a3f2b1",
        discovered_at="2026-05-01T14:30:24Z",
        discovery_query="depthWrite transparent",
        select=SelectOutcome(deduped=True, fetched=True,
                              taxonomy_cell="web-3d/three.js",
                              score=7, score_reasons=["visual_symptom"],
                              selected=True),
        produce=ProduceOutcome(extracted=True, validated=True),
        judge=JudgeOutcome(with_gla_score=1.0, code_only_score=0.0,
                            helps_verdict="yes",
                            committed_as="r20_threejs_depth_write_transparent"),
        tokens=TokenSpend(triage=0, draft=0, evaluate=12500),
        cache_hit=False,
        terminal_phase="judge",
        terminal_reason=TerminalReason.COMMITTED.value,
    )
    d = row.to_dict()
    assert d["url"] == "https://github.com/x/y/issues/1"
    assert d["select"]["score"] == 7
    assert d["produce"]["extracted"] is True
    assert d["judge"]["committed_as"] == "r20_threejs_depth_write_transparent"
    assert d["tokens"]["total"] == 12500  # auto-computed
    assert d["terminal_phase"] == "judge"
    assert d["terminal_reason"] == "committed"

def test_journey_row_select_dropped_has_null_phases():
    row = JourneyRow.dropped_at_select(
        url="https://example.com/issue/2",
        run_id="r1",
        discovered_at="2026-05-01T14:30:24Z",
        discovery_query="q",
        select=SelectOutcome(deduped=True, fetched=True,
                              taxonomy_cell="web-3d/three.js",
                              score=1, score_reasons=["visual_symptom"],
                              selected=False),
        terminal_reason=TerminalReason.BELOW_MIN_SCORE.value,
    )
    d = row.to_dict()
    assert d["produce"] is None
    assert d["judge"] is None
    assert d["tokens"]["total"] == 0
    assert d["terminal_phase"] == "select"
    assert d["terminal_reason"] == "below_min_score"

def test_journey_writer_roundtrip(tmp_path):
    from gpa.eval.curation.journey import JourneyWriter
    p = tmp_path / "journey.jsonl"
    w = JourneyWriter(p)
    w.append(JourneyRow(
        url="u1", run_id="r1", discovered_at="t",
        discovery_query="q",
        select=SelectOutcome(deduped=True, fetched=True,
                              taxonomy_cell="c", score=5, selected=True),
        terminal_phase="select", terminal_reason="not_selected",
    ))
    rows = w.read_all()
    assert len(rows) == 1
    assert rows[0]["url"] == "u1"
    assert rows[0]["select"]["score"] == 5
