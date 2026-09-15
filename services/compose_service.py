import logging
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from moviepy.audio.AudioClip import concatenate_audioclips

import config
from services.errors import PipelineError

logger = logging.getLogger(__name__)

CAPTION_CHUNK_SIZE = 3
CAPTION_FONT_SIZE = 68
CAPTION_STROKE_WIDTH = 6
CAPTION_Y_RATIO = 0.72  # 화면 세로 기준 자막 위치 (0=상단, 1=하단)
YELLOW = (255, 214, 0, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)


# =========================================================
# 1) 컷별 Kling 클립을 대본 호흡(duration_sec)에 맞춰 하드컷 편집
# =========================================================
def build_video_track(cuts: list, clip_paths: list, target_duration: float):
    if len(cuts) != len(clip_paths):
        raise PipelineError("합성(MoviePy)", "cuts 개수와 생성된 클립 개수가 일치하지 않습니다.")

    subclips = []
    opened_clips = []
    try:
        for cut, clip_path in zip(cuts, clip_paths):
            if not os.path.exists(clip_path):
                raise PipelineError("합성(MoviePy)", f"클립 파일을 찾을 수 없습니다: {clip_path}")
            clip = VideoFileClip(clip_path)
            opened_clips.append(clip)
            dur = min(float(cut["duration_sec"]), clip.duration)
            sub = clip.subclip(0, dur)
            sub = _fit_vertical(sub)
            subclips.append(sub)

        video_track = concatenate_videoclips(subclips, method="compose")

        # 오디오 길이에 맞춰 마지막 프레임을 고정하여 늘리거나, 넘치면 잘라낸다.
        if video_track.duration < target_duration:
            pad = target_duration - video_track.duration
            freeze = video_track.to_ImageClip(t=video_track.duration - 0.04).set_duration(pad)
            freeze = freeze.set_fps(config.VIDEO_FPS)
            video_track = concatenate_videoclips([video_track, freeze], method="compose")
        elif video_track.duration > target_duration:
            video_track = video_track.subclip(0, target_duration)

        return video_track, opened_clips
    except PipelineError:
        raise
    except Exception as e:
        raise PipelineError("합성(MoviePy)", f"비디오 트랙 조립 실패: {e}") from e


def _fit_vertical(clip):
    """9:16(1080x1920) 캔버스에 맞춰 center-crop/resize."""
    target_w, target_h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    clip = clip.resize(height=target_h) if clip.h / clip.w < target_h / target_w else clip.resize(width=target_w)
    if clip.w > target_w:
        x_center = clip.w / 2
        clip = clip.crop(x_center=x_center, width=target_w)
    if clip.h > target_h:
        y_center = clip.h / 2
        clip = clip.crop(y_center=y_center, height=target_h)
    return clip.resize((target_w, target_h))


# =========================================================
# 2) 단어 단위 자막 클립 생성 (키워드 노란색 강조)
# =========================================================
def _normalize(word: str) -> str:
    return re.sub(r"[^\w가-힣]", "", word).lower()


def _is_keyword(word: str, keywords: list) -> bool:
    norm = _normalize(word)
    if not norm:
        return False
    if norm.isdigit():
        return True
    return any(_normalize(k) == norm for k in keywords)


def _load_font():
    if not os.path.exists(config.FONT_PATH):
        raise PipelineError(
            "합성(MoviePy)",
            f"자막 폰트 파일을 찾을 수 없습니다: {config.FONT_PATH} "
            "(한국어 TTF 폰트를 fonts/ 폴더에 넣고 FONT_PATH를 설정하세요)",
        )
    return ImageFont.truetype(config.FONT_PATH, CAPTION_FONT_SIZE)


def _render_caption_image(words_with_flags: list, font: ImageFont.FreeTypeFont, canvas_w: int):
    text = " ".join(w for w, _ in words_with_flags)
    dummy = Image.new("RGBA", (canvas_w, 10))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=CAPTION_STROKE_WIDTH)
    text_h = bbox[3] - bbox[1]
    pad = 40
    img = Image.new("RGBA", (canvas_w, text_h + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    total_w = draw.textlength(text, font=font)
    x = (canvas_w - total_w) / 2
    y = pad

    cursor_x = x
    for word, is_kw in words_with_flags:
        color = YELLOW if is_kw else WHITE
        draw.text((cursor_x, y), word, font=font, fill=color,
                   stroke_width=CAPTION_STROKE_WIDTH, stroke_fill=BLACK)
        word_w = draw.textlength(word + " ", font=font)
        cursor_x += word_w

    return np.array(img)


def build_caption_clips(words: list, keywords: list, video_duration: float):
    font = _load_font()
    clips = []
    for i in range(0, len(words), CAPTION_CHUNK_SIZE):
        chunk = words[i:i + CAPTION_CHUNK_SIZE]
        start = max(0.0, chunk[0]["start"])
        end = min(video_duration, chunk[-1]["end"])
        if end <= start:
            continue
        words_with_flags = [(w["word"].strip(), _is_keyword(w["word"], keywords)) for w in chunk]
        img_array = _render_caption_image(words_with_flags, font, config.VIDEO_WIDTH - 80)
        clip = (
            ImageClip(img_array)
            .set_start(start)
            .set_duration(end - start)
            .set_position(("center", int(config.VIDEO_HEIGHT * CAPTION_Y_RATIO)))
        )
        clips.append(clip)
    return clips


# =========================================================
# 3) BGM / 효과음 믹싱 (파일이 없으면 건너뛰고 경고만 남김)
# =========================================================
def _safe_audio_clip(path: str, volume: float = 1.0):
    if not path or not os.path.exists(path):
        logger.warning("오디오 리소스를 찾을 수 없어 건너뜁니다: %s", path)
        return None
    try:
        clip = AudioFileClip(path)
        return clip.volumex(volume)
    except Exception as e:
        logger.warning("오디오 로드 실패, 건너뜁니다 (%s): %s", path, e)
        return None


def build_mixed_audio(narration_path: str, video_duration: float, cuts: list):
    narration = AudioFileClip(narration_path)
    tracks = [narration]

    bgm = _safe_audio_clip(config.BGM_PATH, volume=0.15)
    if bgm is not None:
        loops = int(video_duration // bgm.duration) + 1
        bgm_full = concatenate_audioclips([bgm] * loops).subclip(0, video_duration)
        tracks.append(bgm_full)

    # 오프닝 컷(충격 도입부)에 impact 사운드
    impact = _safe_audio_clip(config.SFX_IMPACT_PATH, volume=0.9)
    if impact is not None and cuts:
        tracks.append(impact.set_start(0))

    # 각 컷 전환 지점마다 whoosh 사운드
    whoosh = _safe_audio_clip(config.SFX_WHOOSH_PATH, volume=0.5)
    if whoosh is not None:
        t = 0.0
        for cut in cuts[:-1]:
            t += float(cut["duration_sec"])
            if t < video_duration:
                tracks.append(whoosh.set_start(max(0.0, t - 0.05)))

    return CompositeAudioClip(tracks).set_duration(video_duration)


# =========================================================
# 4) 최종 조립
# =========================================================
def compose_final_video(cuts: list, clip_paths: list, narration_path: str,
                         words: list, keywords: list, output_path: str) -> str:
    opened = []
    try:
        narration = AudioFileClip(narration_path)
        target_duration = narration.duration

        video_track, opened = build_video_track(cuts, clip_paths, target_duration)
        caption_clips = build_caption_clips(words, keywords, target_duration)

        final_video = CompositeVideoClip([video_track, *caption_clips],
                                          size=(config.VIDEO_WIDTH, config.VIDEO_HEIGHT))
        final_video = final_video.set_duration(target_duration)

        mixed_audio = build_mixed_audio(narration_path, target_duration, cuts)
        final_video = final_video.set_audio(mixed_audio)

        final_video.write_videofile(
            output_path,
            fps=config.VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
            temp_audiofile=output_path + ".temp-audio.m4a",
            remove_temp=True,
            logger=None,
        )
        return output_path
    except PipelineError:
        raise
    except Exception as e:
        raise PipelineError("합성(MoviePy)", f"최종 영상 합성 실패: {e}") from e
    finally:
        for c in opened:
            try:
                c.close()
            except Exception:
                pass
