from dataclasses import dataclass


@dataclass
class IdentificationPolicy:
    min_confidence: float = 0.9
    max_candidates: int = 5
