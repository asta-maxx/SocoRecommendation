"""Negative raw is a defect, not a state. DS-008 section 8.

Clamp at zero, store no share for that user, log a coherence failure. It should
not happen once the reversal is aged from the original order -- but the handling
has to exist, because data check 7 needs something to report against.
"""

from __future__ import annotations

import logging

from reco.store.scores import normalise_to_shares, normalise_with_coherence


def test_clean_user_gets_shares_and_no_failures() -> None:
    raws = {"fashion & apparel": 30.0, "electronics": 10.0}

    clamped, shares, failures = normalise_with_coherence("u1", raws)

    assert failures == []
    assert clamped == raws
    assert shares == {"fashion & apparel": 0.75, "electronics": 0.25}


def test_negative_raw_is_clamped_to_zero() -> None:
    clamped, _, _ = normalise_with_coherence(
        "u1", {"fashion & apparel": 20.0, "electronics": -2.66}
    )

    assert clamped["electronics"] == 0.0


def test_negative_raw_suppresses_shares_for_the_WHOLE_user() -> None:
    """Not just the offending category.

    Every share is computed against a denominator the bad value contributed to,
    so the whole distribution is suspect -- returning shares for the categories
    that happen to be positive would publish numbers derived from a known-bad
    total.
    """
    _, shares, failures = normalise_with_coherence(
        "u1", {"fashion & apparel": 20.0, "electronics": -2.66}
    )

    assert shares == {}
    assert len(failures) == 1


def test_failure_records_what_was_observed() -> None:
    """Check 7 reports against these, so they carry the evidence."""
    _, _, failures = normalise_with_coherence("u1", {"electronics": -2.66})

    failure = failures[0]
    assert failure.user_id == "u1"
    assert failure.category == "electronics"
    assert failure.observed_raw == -2.66
    assert failure.detected_at.tzinfo is not None


def test_every_negative_category_is_recorded() -> None:
    _, _, failures = normalise_with_coherence(
        "u1", {"electronics": -1.0, "books": -2.0, "toys": 5.0}
    )

    assert {f.category for f in failures} == {"electronics", "books"}


def test_coherence_failure_is_logged_at_error(caplog) -> None:
    """Silently clamping and carrying on would leave the profile wrong with
    nothing in the logs to say so.
    """
    with caplog.at_level(logging.ERROR, logger="reco.store.scores"):
        normalise_with_coherence("u1", {"electronics": -2.66})

    assert "coherence failure" in caplog.text
    assert "u1" in caplog.text
    # The message names the actual cause, so whoever reads it knows where to look.
    assert "aged from the original order" in caplog.text


def test_zero_total_stores_no_share_and_is_not_a_failure() -> None:
    """A cold user is not a defect. No share, no error log -- the ladder answers."""
    clamped, shares, failures = normalise_with_coherence("u1", {"electronics": 0.0})

    assert shares == {}
    assert failures == []
    assert clamped == {"electronics": 0.0}


def test_uniform_share_is_never_fabricated() -> None:
    """One of the five things not to do. A uniform distribution is
    indistinguishable from a genuine even spread of interest and hides that the
    user is unknown.
    """
    assert normalise_to_shares({"a & b": 0.0, "c & d": 0.0}) == {}

    _, shares, _ = normalise_with_coherence("u1", {"a & b": 0.0, "c & d": 0.0})
    assert shares == {}


def test_raws_survive_a_failure_for_diagnosis() -> None:
    """raw is diagnostics, and it is what makes the failure explainable."""
    clamped, shares, failures = normalise_with_coherence(
        "u1", {"fashion & apparel": 20.0, "electronics": -2.66}
    )

    assert clamped["fashion & apparel"] == 20.0
    assert shares == {} and failures
