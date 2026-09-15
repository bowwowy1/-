import logging
import os
import time

import requests

import config
from services.errors import PipelineError

logger = logging.getLogger(__name__)


def synthesize_speech(text: str, output_path: str) -> str:
    """Typecast API로 전체 대본을 음성(mp3)으로 합성한다. 완성된 파일 경로를 반환한다."""
    if not config.TYPECAST_API_KEY:
        raise PipelineError("오디오(TTS)", "TYPECAST_API_KEY가 설정되지 않았습니다.")
    if not config.TYPECAST_ACTOR_ID:
        raise PipelineError("오디오(TTS)", "TYPECAST_ACTOR_ID가 설정되지 않았습니다.")

    headers = {
        "X-API-KEY": config.TYPECAST_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "actor_id": config.TYPECAST_ACTOR_ID,
        "text": text,
        "model": config.TYPECAST_MODEL,
        "lang": "ko",
        "output": {"volume": 100, "audio_pitch": 0, "audio_tempo": 1.0, "audio_format": "mp3"},
    }

    try:
        # 1) 음성 합성 요청 (비동기 speak_url 발급형 API 기준)
        resp = requests.post(config.TYPECAST_API_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise PipelineError("오디오(TTS)", f"Typecast 요청 실패: {e}") from e
    except ValueError as e:
        raise PipelineError("오디오(TTS)", f"Typecast 응답 파싱 실패: {e}") from e

    audio_url = _extract_audio_url(data)

    # 2) 비동기 처리(status: progress)인 경우 폴링
    if audio_url is None:
        speak_url = data.get("result", {}).get("speak_v2_url") or data.get("speak_v2_url")
        if not speak_url:
            raise PipelineError("오디오(TTS)", f"Typecast 응답에서 오디오 URL을 찾을 수 없습니다: {data}")
        audio_url = _poll_typecast_result(speak_url, headers)

    # 3) 오디오 파일 다운로드
    try:
        audio_resp = requests.get(audio_url, timeout=60)
        audio_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(audio_resp.content)
    except requests.RequestException as e:
        raise PipelineError("오디오(TTS)", f"오디오 파일 다운로드 실패: {e}") from e

    return output_path


def _extract_audio_url(data: dict):
    for key in ("audio_url", "url", "wav_url", "mp3_url"):
        if key in data:
            return data[key]
        if "result" in data and isinstance(data["result"], dict) and key in data["result"]:
            return data["result"][key]
    return None


def _poll_typecast_result(speak_url: str, headers: dict, max_tries: int = 30, interval: int = 2) -> str:
    for _ in range(max_tries):
        try:
            resp = requests.get(speak_url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise PipelineError("오디오(TTS)", f"Typecast 상태 조회 실패: {e}") from e

        status = data.get("result", {}).get("status") or data.get("status")
        if status == "done":
            return data.get("result", {}).get("audio_download_url") or data.get("audio_download_url")
        if status == "failed":
            raise PipelineError("오디오(TTS)", f"Typecast 음성 합성 실패: {data}")
        time.sleep(interval)

    raise PipelineError("오디오(TTS)", "Typecast 음성 합성 타임아웃")
