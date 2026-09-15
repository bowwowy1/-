import base64
import logging
import time

import jwt
import requests

import config
from services.errors import PipelineError

logger = logging.getLogger(__name__)


def _build_kling_jwt() -> str:
    """Kling API는 AccessKey/SecretKey로 서명한 단기 JWT를 Bearer 토큰으로 사용한다."""
    if not config.KLING_ACCESS_KEY or not config.KLING_SECRET_KEY:
        raise PipelineError("영상(I2V)", "KLING_ACCESS_KEY/KLING_SECRET_KEY가 설정되지 않았습니다.")

    now = int(time.time())
    payload = {
        "iss": config.KLING_ACCESS_KEY,
        "exp": now + 1800,
        "nbf": now - 5,
    }
    token = jwt.encode(payload, config.KLING_SECRET_KEY, algorithm="HS256", headers={"alg": "HS256", "typ": "JWT"})
    return token


def _image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def generate_video_clip(image_path: str, motion_prompt: str, output_path: str,
                         duration: int = None) -> str:
    """Kling I2V API로 이미지 + 모션 프롬프트를 8초(하드컷 지원) 클립(mp4)으로 변환한다."""
    duration = duration or config.KLING_CLIP_DURATION

    token = _build_kling_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model_name": "kling-v1-6",
        "image": _image_to_base64(image_path),
        "prompt": motion_prompt,
        "duration": str(duration),
        "mode": "std",
        "cfg_scale": 0.5,
        # 하드컷(cut) 지원: 씬 내 급격한 전환을 허용
        "camera_control": {"type": "simple"},
    }

    create_url = f"{config.KLING_API_BASE}/v1/videos/image2video"
    try:
        resp = requests.post(create_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise PipelineError("영상(I2V)", f"Kling 요청 실패: {e}") from e

    task_id = data.get("data", {}).get("task_id")
    if not task_id:
        raise PipelineError("영상(I2V)", f"Kling 응답에서 task_id를 찾을 수 없습니다: {data}")

    video_url = _poll_kling_result(task_id, headers)

    try:
        video_resp = requests.get(video_url, timeout=120)
        video_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(video_resp.content)
    except requests.RequestException as e:
        raise PipelineError("영상(I2V)", f"영상 다운로드 실패: {e}") from e

    return output_path


def _poll_kling_result(task_id: str, headers: dict, max_tries: int = 90, interval: int = 5) -> str:
    status_url = f"{config.KLING_API_BASE}/v1/videos/image2video/{task_id}"
    for _ in range(max_tries):
        try:
            resp = requests.get(status_url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise PipelineError("영상(I2V)", f"Kling 상태 조회 실패: {e}") from e

        task_status = data.get("data", {}).get("task_status")
        if task_status == "succeed":
            videos = data.get("data", {}).get("task_result", {}).get("videos", [])
            if not videos:
                raise PipelineError("영상(I2V)", f"Kling 완료 응답에 영상이 없습니다: {data}")
            return videos[0]["url"]
        if task_status == "failed":
            raise PipelineError("영상(I2V)", f"Kling 영상 생성 실패: {data}")
        time.sleep(interval)

    raise PipelineError("영상(I2V)", "Kling 영상 생성 타임아웃")
