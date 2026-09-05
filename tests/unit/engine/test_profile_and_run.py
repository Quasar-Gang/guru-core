"""Profile arithmetic and the Station-1 state machine.

The rule under test throughout: numbers are computed here, never taken from a model.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from packages.importers.document import DocEvent, Document, TextChunk
from services.engine.domain.errors import IllegalTransition
from services.engine.domain.profile import (
    ClassifiedEvent,
    ProfileSignals,
    build_coverage,
    compute_metrics,
    window,
)
from services.engine.domain.run import RunStatus, assert_transition, is_terminal

WINDOW_START = date(2026, 1, 5)
WINDOW_END = date(2026, 3, 29)


def event(day_offset: int, ref: str, minutes: int = 60, all_day: bool = False) -> DocEvent:
    start = datetime(2026, 1, 5, 9, 0, tzinfo=UTC) + timedelta(days=day_offset)
    return DocEvent(
        title="Something",
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        all_day=all_day,
        source_ref=ref,
    )


def metrics_for(document: Document, signals: ProfileSignals):
    rows = compute_metrics(document, signals, window_start=WINDOW_START, window_end=WINDOW_END)
    return {row.dimension: row for row in rows}


class TestCoverage:
    def test_it_reports_what_was_uploaded_and_over_what_period(self):
        document = Document(
            events=[event(0, "e0"), event(20, "e1")], text_chunks=[TextChunk(text="resume")]
        )
        coverage = build_coverage(document, ["upload", "google_calendar", "upload"])
        assert coverage.events == 2
        assert coverage.text_chunks == 1
        assert coverage.sources == ["google_calendar", "upload"]
        assert coverage.period_start == date(2026, 1, 5)
        assert coverage.period_end == date(2026, 1, 25)
        assert coverage.weeks == 3

    def test_nothing_uploaded_is_an_honest_empty_answer(self):
        coverage = build_coverage(Document(), [])
        assert coverage.events == 0
        assert coverage.period_start is None


class TestMetrics:
    def test_hours_and_shares_come_from_the_events_not_the_model(self):
        document = Document(events=[event(0, "e0", 60), event(1, "e1", 180)])
        signals = ProfileSignals(
            events=[
                ClassifiedEvent(source_ref="e0", dimension="work"),
                ClassifiedEvent(source_ref="e1", dimension="learning"),
            ]
        )
        rows = metrics_for(document, signals)
        assert rows["work"].hours == 1.0
        assert rows["learning"].hours == 3.0
        assert rows["work"].share == pytest.approx(0.25)
        assert rows["learning"].share == pytest.approx(0.75)

    def test_an_unclassified_event_is_counted_not_dropped(self):
        """Unnamed time is the most valuable column, so it is never quietly discarded."""
        document = Document(events=[event(0, "e0"), event(1, "e1")])
        signals = ProfileSignals(events=[ClassifiedEvent(source_ref="e0", dimension="work")])
        rows = metrics_for(document, signals)
        assert rows["unclassified"].events == 1
        assert rows["unclassified"].hours == 1.0

    def test_an_all_day_event_takes_no_hours(self):
        document = Document(events=[event(0, "e0", all_day=True)])
        signals = ProfileSignals(events=[ClassifiedEvent(source_ref="e0", dimension="work")])
        rows = metrics_for(document, signals)
        assert rows["work"].events == 1
        assert rows["work"].hours == 0.0

    def test_the_longest_unbroken_run_is_measured_in_weeks(self):
        """ "11 weeks unbroken" is a finding; this is where the 11 comes from."""
        document = Document(events=[event(7 * week, f"e{week}") for week in range(11)])
        signals = ProfileSignals(
            events=[
                ClassifiedEvent(source_ref=f"e{week}", dimension="learning") for week in range(11)
            ]
        )
        rows = metrics_for(document, signals)
        assert rows["learning"].weeks_present == 11
        assert rows["learning"].longest_streak_weeks == 11

    def test_a_gap_breaks_the_streak_without_losing_the_weeks(self):
        document = Document(events=[event(0, "e0"), event(7, "e1"), event(28, "e2")])
        signals = ProfileSignals(
            events=[
                ClassifiedEvent(source_ref=ref, dimension="exercise") for ref in ("e0", "e1", "e2")
            ]
        )
        rows = metrics_for(document, signals)
        assert rows["exercise"].weeks_present == 3
        assert rows["exercise"].longest_streak_weeks == 2

    def test_events_outside_the_window_are_ignored(self):
        document = Document(events=[event(-30, "e0"), event(0, "e1")])
        signals = ProfileSignals(
            events=[ClassifiedEvent(source_ref=ref, dimension="work") for ref in ("e0", "e1")]
        )
        assert metrics_for(document, signals)["work"].events == 1


def test_the_window_runs_back_from_the_last_day_with_data():
    start, end = window(date(2026, 3, 29), 26, today=date(2026, 6, 1))
    assert end == date(2026, 3, 29)
    assert (end - start).days + 1 == 26 * 7


def test_the_window_falls_back_to_today_when_nothing_was_uploaded():
    _, end = window(None, 26, today=date(2026, 6, 1))
    assert end == date(2026, 6, 1)


class TestTheRunStateMachine:
    def test_the_happy_path(self):
        assert_transition(RunStatus.pending, RunStatus.analyzing)
        assert_transition(RunStatus.analyzing, RunStatus.recommending)
        assert_transition(RunStatus.recommending, RunStatus.ready)

    def test_recommending_cannot_be_skipped(self):
        """The Reports screen is shown before any verdict exists, so the states are separate."""
        with pytest.raises(IllegalTransition):
            assert_transition(RunStatus.analyzing, RunStatus.ready)

    def test_any_state_may_fail(self):
        for status in (RunStatus.pending, RunStatus.analyzing, RunStatus.recommending):
            assert_transition(status, RunStatus.failed)

    def test_terminal_states_go_nowhere(self):
        assert is_terminal(RunStatus.ready)
        assert is_terminal(RunStatus.failed)
        with pytest.raises(IllegalTransition):
            assert_transition(RunStatus.ready, RunStatus.analyzing)
