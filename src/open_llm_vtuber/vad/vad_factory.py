from typing import Callable, Dict, Optional

from .vad_interface import VADInterface


def _build_silero_vad(kwargs: dict) -> VADInterface:
    from .silero import VADEngine as SileroVADEngine

    return SileroVADEngine(
        kwargs.get("orig_sr"),
        kwargs.get("target_sr"),
        kwargs.get("prob_threshold"),
        kwargs.get("db_threshold"),
        kwargs.get("required_hits"),
        kwargs.get("required_misses"),
        kwargs.get("smoothing_window"),
    )


_VAD_BUILDERS: Dict[str, Callable[[dict], VADInterface]] = {
    "silero_vad": _build_silero_vad,
}


class VADFactory:
    @staticmethod
    def get_vad_engine(engine_type, **kwargs) -> Optional[VADInterface]:
        if engine_type is None:
            return None

        try:
            builder = _VAD_BUILDERS[engine_type]
        except KeyError:
            raise ValueError(f"Unknown VAD engine: {engine_type}") from None
        return builder(kwargs)
