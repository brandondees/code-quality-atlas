# SPDX-License-Identifier: MIT
"""Shared fixtures for the reviewer service suite."""

from __future__ import annotations

import pytest

from atlas_reviewer.call_facts import reset_events


@pytest.fixture(autouse=True)
def _clean_call_markers():
    """The request-side markers are per-context state a follow-up turn is
    meant to consume; a test whose turn never runs would otherwise stain
    the next test's spans (review Minor 5). Every test starts clean."""
    reset_events()
    yield
    reset_events()
