import json
import logging
import os
import shutil
import uuid

import config
from services import gemini_service, tts_service, image_service, video_service
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
        "title": None,
        "full_script": None,
        "scenes": [],
        "zip_path": None,
    }
    return job_id


def _write_script_files(job_dir: str, script_data: dict):
    with open(os.path.join(job_dir, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script_data, f, ensure_ascii=False, indent=2)

    lines = [f"제목: {script_data['title']}", "", "[전체 대본]", script_data["full_script"], "",
             f"[강조 키워드] {', '.join(script_data['keywords'])}", "", "[컷 리스트]"]
    for cut in script_data["cuts"]:
        lines.append(
            f"- Cut {cut['cut_no']:02d} [{cut['section']}] ({cut['duration_sec']}s)\n"
            f"    나레이션: {cut['narration']}\n"
            f"    image_prompt: {cut['image_prompt']}\n"
            f"    motion_prompt: {cut['motion_prompt']}"
        )
    with open(os.path.join(job_dir, "script.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def run_pipeline(job_id: str, topic: str):
    job_dir = os.path.join(config.OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        # ---- 1단계: 기획 및 대본/컷 프롬프트 생성 (Gemini) ----
        _update(job_id, status="running", stage="1/3 기획 및 대본 생성 (Gemini)", progress=5)
        script_data = gemini_service.generate_script_and_prompts(topic)
        cuts = script_data["cuts"]
        _write_script_files(job_dir, script_data)
        _update(job_id, title=script_data["title"], full_script=script_data["full_script"])

        # ---- 2단계: 나레이션 오디오 생성 (TTS) ----
        _update(job_id, stage="2/3 나레이션 오디오 생성 (TTS)", progress=15)
        narration_path = os.path.join(job_dir, "narration.mp3")
        tts_service.synthesize_speech(script_data["full_script"], narration_path)

        # ---- 3단계: 씬별 이미지(T2I) + 영상(I2V) 소스 생성 ----
        scenes = []
        total_cuts = len(cuts)
        for i, cut in enumerate(cuts):
            base_progress = 25 + int(70 * (i / max(total_cuts, 1)))
            _update(job_id, stage=f"3/3 씬 이미지/영상 소스 생성 ({i + 1}/{total_cuts})", progress=base_progress)

            image_name = f"cut_{cut['cut_no']:02d}.png"
            video_name = f"cut_{cut['cut_no']:02d}.mp4"
            image_path = os.path.join(job_dir, image_name)
            video_path = os.path.join(job_dir, video_name)

            image_service.generate_image(cut["image_prompt"], image_path,
                                          width=config.IMAGE_WIDTH, height=config.IMAGE_HEIGHT)
            video_service.generate_video_clip(image_path, cut["motion_prompt"], video_path)

            scenes.append({
                "cut_no": cut["cut_no"],
                "section": cut["section"],
                "narration": cut["narration"],
                "duration_sec": cut["duration_sec"],
                "image_file": image_name,
                "video_file": video_name,
            })
            _update(job_id, scenes=list(scenes))

        # ---- 산출물 zip 패키징 ----
        _update(job_id, stage="산출물 압축 중", progress=97)
        zip_base = os.path.join(config.OUTPUT_DIR, f"{job_id}_sources")
        zip_path = shutil.make_archive(zip_base, "zip", job_dir)

        _update(job_id, status="done", stage="완료", progress=100,
                message="대본 및 씬별 이미지/영상 소스 생성이 완료되었습니다.", zip_path=zip_path)

    except PipelineError as e:
        logger.exception("파이프라인 실패 (job=%s)", job_id)
        _update(job_id, status="error", stage=e.stage, progress=JOBS[job_id]["progress"],
                error=e.message)
    except Exception as e:
        logger.exception("알 수 없는 오류 (job=%s)", job_id)
        _update(job_id, status="error", stage=JOBS[job_id].get("stage", "알 수 없음"),
                progress=JOBS[job_id]["progress"], error=f"알 수 없는 오류: {e}")
