import logging

from openai import OpenAI

import config
from services.errors import PipelineError

logger = logging.getLogger(__name__)


def transcribe_words(audio_path: str) -> list:
    """OpenAI Whisper API로 오디오를 단어 단위 타임스탬프로 변환한다.
    반환값: [{"word": str, "start": float, "end": float}, ...]
    """
    if not config.OPENAI_API_KEY:
        raise PipelineError("자막(STT)", "OPENAI_API_KEY가 설정되지 않았습니다.")

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    try:
        with open(audio_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model=config.WHISPER_MODEL,
                file=f,
                language="ko",
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
    except Exception as e:
        raise PipelineError("자막(STT)", f"Whisper STT 호출 실패: {e}") from e

    words = getattr(transcript, "words", None)
    if not words:
        raise PipelineError("자막(STT)", "Whisper 응답에 word 타임스탬프가 없습니다.")

    return [{"word": w.word, "start": w.start, "end": w.end} for w in words]


def words_to_srt(words: list, chunk_size: int = 3) -> str:
    """단어 리스트를 chunk_size개씩 묶어 SRT 자막 문자열로 변환한다."""
    lines = []
    idx = 1
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        text = " ".join(w["word"].strip() for w in chunk)
        lines.append(str(idx))
        lines.append(f"{_format_timestamp(start)} --> {_format_timestamp(end)}")
        lines.append(text)
        lines.append("")
        idx += 1
    return "\n".join(lines)


def _format_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
