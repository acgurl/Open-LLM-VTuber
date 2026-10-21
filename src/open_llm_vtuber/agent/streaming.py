from typing import Dict


TEXT_DELTA_TYPE = "text_delta"


def make_text_delta(text: str) -> Dict[str, str]:
    """Build the internal event emitted for displayable LLM tokens."""
    return {"type": TEXT_DELTA_TYPE, "text": text}
