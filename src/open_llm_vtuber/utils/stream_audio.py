import base64
import io
import os
from pydub import AudioSegment
from pydub.utils import make_chunks
from ..agent.output_types import Actions
from ..agent.output_types import DisplayText


_PASSTHROUGH_AUDIO_MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def _load_audio(audio_path: str) -> tuple[AudioSegment, bytes, str]:
    """Decode audio for volume analysis while keeping its original encoding."""
    extension = os.path.splitext(audio_path)[1].lower()
    audio_mime = _PASSTHROUGH_AUDIO_MIME.get(extension)

    # pydub skips its own file.close() when it decodes a WAV path directly, so
    # own the handle here and close it deterministically.
    with open(audio_path, "rb") as audio_file:
        if audio_mime:
            # Ship the engine's own encoding (Edge TTS emits MP3) instead of
            # inflating it to WAV; base64 WAV frames were stalling playback.
            audio_bytes = audio_file.read()
            audio_file.seek(0)
        audio = AudioSegment.from_file(
            audio_file, format="wav" if extension == ".wav" else None
        )
        if not audio_mime:
            converted = io.BytesIO()
            audio.export(converted, format="wav")
            audio_bytes = converted.getvalue()

    return audio, audio_bytes, audio_mime or "audio/wav"


def _get_volume_by_chunks(audio: AudioSegment, chunk_length_ms: int) -> list:
    """
    Calculate the normalized volume (RMS) for each chunk of the audio.

    Parameters:
        audio (AudioSegment): The audio segment to process.
        chunk_length_ms (int): The length of each audio chunk in milliseconds.

    Returns:
        list: Normalized volumes for each chunk.
    """
    chunks = make_chunks(audio, chunk_length_ms)
    volumes = [chunk.rms for chunk in chunks]
    max_volume = max(volumes)
    if max_volume == 0:
        raise ValueError("Audio is empty or all zero.")
    return [volume / max_volume for volume in volumes]


def prepare_audio_payload(
    audio_path: str | None,
    chunk_length_ms: int = 20,
    display_text: DisplayText = None,
    actions: Actions = None,
    forwarded: bool = False,
    streamed: bool = False,
) -> dict[str, any]:
    """
    Prepares the audio payload for sending to a broadcast endpoint.
    If audio_path is None, returns a payload with audio=None for silent display.

    Parameters:
        audio_path (str | None): The path to the audio file to be processed, or None for silent display
        chunk_length_ms (int): The length of each audio chunk in milliseconds
        display_text (DisplayText, optional): Text to be displayed with the audio
        actions (Actions, optional): Actions associated with the audio

    Returns:
        dict: The audio payload to be sent
    """
    if isinstance(display_text, DisplayText):
        display_text = display_text.to_dict()

    audio_base64 = None
    audio_mime = None
    volumes = []

    if audio_path:
        try:
            audio, audio_bytes, audio_mime = _load_audio(audio_path)
        except Exception as e:
            raise ValueError(f"Error loading generated audio file '{audio_path}': {e}")
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        volumes = _get_volume_by_chunks(audio, chunk_length_ms)

    return {
        "type": "audio",
        "audio": audio_base64,
        "audio_mime": audio_mime,
        "volumes": volumes,
        "slice_length": chunk_length_ms,
        "display_text": display_text,
        "actions": actions.to_dict() if actions else None,
        "forwarded": forwarded,
        "streamed": streamed,
    }


# Example usage:
# payload, duration = prepare_audio_payload("path/to/audio.mp3", display_text="Hello", expression_list=[0,1,2])
