# SPDX-License-Identifier: MIT
"""Model providers. Only the offline provider ships; see the README for
the first live adapter to wire and what it needs."""

from __future__ import annotations

import re

from atlas_reviewer.prompt import Prompt

_LABEL = re.compile(r'<untrusted-data id="[^"]*" label="([^"]*)">')


class OfflineProvider:
    """Calls no model. Returns a deterministic description of the prompt a
    live provider would have received, and keeps every prompt it saw."""

    name = "offline"

    def __init__(self) -> None:
        self.prompts: list[Prompt] = []

    def complete(self, prompt: Prompt) -> str:
        self.prompts.append(prompt)
        labels = _LABEL.findall(prompt.user)
        return (
            "Offline provider: no model was called, so this draft contains no model findings.\n"
            f"A live provider would have received {len(labels)} untrusted block(s) "
            f"({', '.join(labels) or 'none'}), a {len(prompt.system)}-character system prompt, "
            f"and a {len(prompt.user)}-character user prompt."
        )
