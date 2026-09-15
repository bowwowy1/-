import logging
import time

import requests

import config
from services.errors import PipelineError

logger = logging.getLogger(__name__)


def generate_image(prompt: str, output_path: str, width: int = 1080, height: int = 1920) -> str:
    """Flux(T2I) API로 세로 9:16 이미지를 생성하고 output_path에 저장한다."""
    if not config.FLUX_API_KEY:
        raise PipelineError("이미지(T2I)", "FLUX_API_KEY가 설정되지 않았습니다.")

    headers = {
        "x-key": config.FLUX_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "prompt_upsampling": False,
        "safety_tolerance": 2,
    }

    try:
        # 1) 생성 요청 (task id 발급)
        resp = requests.post(config.FLUX_API_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise PipelineError("이미지(T2I)", f"Flux 요청 실패: {e}") from e

    task_id = data.get("id")
    polling_url = data.get("polling_url")
    if not task_id and not polling_url:
        raise PipelineError("이미지(T2I)", f"Flux 응답에서 task id를 찾을 수 없습니다: {data}")

    image_url = _poll_flux_result(polling_url or f"{config.FLUX_API_URL}/{task_id}", headers)

    try:
        img_resp = requests.get(image_url, timeout=60)
        img_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(img_resp.content)
    except requests.RequestException as e:
        raise PipelineError("이미지(T2I)", f"이미지 다운로드 실패: {e}") from e

    return output_path


def _poll_flux_result(polling_url: str, headers: dict, max_tries: int = 40, interval: int = 2) -> str:
    for _ in range(max_tries):
        try:
            resp = requests.get(polling_url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise PipelineError("이미지(T2I)", f"Flux 상태 조회 실패: {e}") from e

        status = data.get("status")
        if status == "Ready":
            image_url = data.get("result", {}).get("sample")
            if not image_url:
                raise PipelineError("이미지(T2I)", f"Flux 완료 응답에 이미지 URL이 없습니다: {data}")
            return image_url
        if status in ("Error", "Content Moderated", "Request Moderated"):
            raise PipelineError("이미지(T2I)", f"Flux 이미지 생성 실패: {data}")
        time.sleep(interval)

    raise PipelineError("이미지(T2I)", "Flux 이미지 생성 타임아웃")
