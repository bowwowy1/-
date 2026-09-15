import logging
import os
import uuid

import config
from services import gemini_service, tts_service, image_service, video_service, stt_service, compose_service
from services.errors import PipelineError

logger = logging.getLogger(__name__)

# job_id -> 진행 상태 딕셔너리 (인메모리, 단일 프로세스 기준)
JOBS = {}


def _update(job_id: str, **kwargs):
    JOBS[job_id].update(kwargs)


def new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "status": "pending",
        "stage": "대기 중",
        "progress": 0,
        "message": "",
        "error": None,
        "video_path": None,
    }
    return job_id


def run_pipeline(job_id: str, topic: str):
    job_dir = os.path.join(config.OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        # ---- 1단계: 기획 (Gemini) ----
        _update(job_id, status="running", stage="1/4 기획 및 대본 생성 (Gemini)", progress=5)
        script_data = gemini_service.generate_script_and_prompts(topic)
        cuts = script_data["cuts"]
        keywords = script_data["keywords"]
        full_script = script_data["full_script"]

        # ---- 2단계: TTS ----
        _update(job_id, stage="2/4 음성 합성 (TTS)", progress=20)
        narration_path = os.path.join(job_dir, "narration.mp3")
        tts_service.synthesize_speech(full_script, narration_path)

        # ---- 2단계: 이미지(T2I) + 영상(I2V) ----
        clip_paths = []
        total_cuts = len(cuts)
        for i, cut in enumerate(cuts):
            base_progress = 30 + int(40 * (i / max(total_cuts, 1)))
            _update(job_id, stage=f"2/4 이미지/영상 생성 ({i + 1}/{total_cuts})", progress=base_progress)

            image_path = os.path.join(job_dir, f"cut_{cut['cut_no']:02d}.png")
            image_service.generate_image(cut["image_prompt"], image_path,
                                          width=config.VIDEO_WIDTH, height=config.VIDEO_HEIGHT)

            clip_path = os.path.join(job_dir, f"cut_{cut['cut_no']:02d}.mp4")
            video_service.generate_video_clip(image_path, cut["motion_prompt"], clip_path)
            clip_paths.append(clip_path)

        # ---- 3단계: STT (자막 싱크) ----
        _update(job_id, stage="3/4 자막 싱크 생성 (STT)", progress=75)
        words = stt_service.transcribe_words(narration_path)
        srt_text = stt_service.words_to_srt(words)
        srt_path = os.path.join(job_dir, "subtitle.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_text)

        # ---- 4단계: 최종 조립 (MoviePy) ----
        _update(job_id, stage="4/4 최종 영상 합성 (MoviePy)", progress=90)
        output_path = os.path.join(job_dir, "final_short.mp4")
        compose_service.compose_final_video(cuts, clip_paths, narration_path, words, keywords, output_path)

        _update(job_id, status="done", stage="완료", progress=100,
                message="쇼츠 영상 생성이 완료되었습니다.", video_path=output_path)

    except PipelineError as e:
        logger.exception("파이프라인 실패 (job=%s)", job_id)
        _update(job_id, status="error", stage=e.stage, progress=JOBS[job_id]["progress"],
                error=e.message)
    except Exception as e:
        logger.exception("알 수 없는 오류 (job=%s)", job_id)
        _update(job_id, status="error", stage=JOBS[job_id].get("stage", "알 수 없음"),
                progress=JOBS[job_id]["progress"], error=f"알 수 없는 오류: {e}")
