import re
from dataclasses import dataclass, field
from typing import List, Tuple

_SENT_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class TranscriptBuffer:
    """Accumulates incoming text fragments (caption cues or ASR partials)
    and emits completed sentences with their approximate start time (ms)."""

    min_chars: int = 40
    pending: str = ""
    pending_start_ms: int = 0
    items: List[Tuple[int, str]] = field(default_factory=list)

    def add(self, text: str, time_ms: int) -> List[Tuple[int, str]]:
        text = text.strip()
        if not text:
            return []
        if not self.pending:
            self.pending_start_ms = time_ms
        self.pending = (self.pending + " " + text).strip()

        out: List[Tuple[int, str]] = []
        parts = _SENT_END.split(self.pending)
        # Keep last fragment as still-pending if it doesn't end with punctuation.
        if parts and not re.search(r"[.!?]\s*$", self.pending):
            tail = parts.pop()
        else:
            tail = ""
        for sent in parts:
            sent = sent.strip()
            if len(sent) >= self.min_chars:
                out.append((self.pending_start_ms, sent))
            elif out:
                # merge short sentence into previous
                ms, prev = out[-1]
                out[-1] = (ms, prev + " " + sent)
        self.pending = tail
        if out:
            # next pending starts roughly at the current time_ms
            self.pending_start_ms = time_ms
        return out

    def flush(self) -> List[Tuple[int, str]]:
        if self.pending and len(self.pending) >= self.min_chars:
            out = [(self.pending_start_ms, self.pending)]
            self.pending = ""
            return out
        return []
