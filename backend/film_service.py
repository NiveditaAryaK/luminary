import asyncio
import base64
import re
import shutil
import subprocess
import textwrap
import uuid
from pathlib import Path

from loguru import logger

from text_utils import strip_choice_markup

RENDERS_DIR = Path(__file__).parent / "renders"
FILM_WIDTH = 1280
FILM_HEIGHT = 720
FILM_FPS = 25
CROSSFADE_SECONDS = 0.6
CARD_SECONDS = 3.5
MIN_BEAT_SECONDS = 4.0
MAX_BEAT_SECONDS = 45.0
NARRATION_TAIL_SECONDS = 0.8
MAX_ZOOM = 1.12
SUBTITLE_MAX_CHARS = 170
SUBTITLE_WRAP_CHARS = 54
SUBTITLE_MIN_SECONDS = 2.0
READING_WORDS_PER_SECOND = 2.6
NARRATION_MAX_CHARS = 1800

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\georgia.ttf",
    r"C:\Windows\Fonts\times.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
]

IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


class FilmError(RuntimeError):
    """Base class for film rendering failures surfaced to the API."""


class FilmUnavailableError(FilmError):
    """ffmpeg (or ffprobe) is not installed on this machine."""


class FilmBusyError(FilmError):
    """A render for this session is already in progress."""


class FilmInputError(FilmError):
    """The session has nothing renderable yet."""


def _chunk_prose(text: str, max_chars: int = SUBTITLE_MAX_CHARS) -> list[str]:
    """Split prose into subtitle-sized chunks on sentence boundaries."""
    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?…])\s+", text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            pieces.extend(textwrap.wrap(sentence, max_chars))
        else:
            pieces.append(sentence)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


def _collect_turn_prose(history: list[dict]) -> dict[int, str]:
    """Map turn number -> narratable prose for that turn.

    Each turn starts with exactly one user entry (director prompt or live
    narration). Model prose wins when present; live narration text is the
    fallback for beats that only produced an illustration.
    """
    prose: dict[int, str] = {}
    turn = 0
    for entry in history:
        parts = entry.get("parts") or []
        joined = "\n\n".join(part.get("text", "") for part in parts if part.get("text"))
        if entry.get("role") == "user":
            turn += 1
            if joined.startswith("[Live narration]"):
                prose[turn] = joined.replace("[Live narration]", "", 1).strip()
        elif turn:
            cleaned = strip_choice_markup(joined)
            if cleaned:
                prose[turn] = cleaned
    return prose


class FilmService:
    """Assembles a session's storyboard into a narrated MP4 via ffmpeg."""

    def __init__(self, narration_service=None):
        self.narration_service = narration_service
        self.jobs: dict[str, dict] = {}
        self._tasks: set[asyncio.Task] = set()
        RENDERS_DIR.mkdir(exist_ok=True)

    def ffmpeg_available(self) -> bool:
        return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

    def get_job(self, session_id: str) -> dict | None:
        return self.jobs.get(session_id)

    def job_public(self, job: dict) -> dict:
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": round(job["progress"], 3),
            "message": job["message"],
            "error": job["error"],
        }

    def start_render(self, session, voice_name: str | None = None, language_code: str | None = None) -> dict:
        if not self.ffmpeg_available():
            raise FilmUnavailableError(
                "ffmpeg is not installed on the server. "
                "Install it (Windows: winget install Gyan.FFmpeg) and restart Luminary."
            )

        existing = self.jobs.get(session.session_id)
        if existing and existing["status"] in {"queued", "rendering"}:
            raise FilmBusyError("A film render is already in progress for this story.")

        beats = [beat for beat in session.storyboard if beat.image]
        if not beats:
            raise FilmInputError("This story has no illustrated beats yet — play a few scenes first.")

        prose_by_turn = _collect_turn_prose(session.history)
        film_data = {
            "session_id": session.session_id,
            "title": session.title,
            "genre": session.genre,
            "voice_name": voice_name,
            "language_code": language_code,
            "beats": [
                {
                    "caption": beat.caption or "",
                    "image": beat.image,
                    "mime_type": beat.mime_type or "image/png",
                    "narration": prose_by_turn.get(beat.turn) or beat.caption or "",
                }
                for beat in beats
            ],
        }

        job = {
            "job_id": str(uuid.uuid4()),
            "status": "queued",
            "progress": 0.0,
            "message": "Queued",
            "error": None,
            "output_path": None,
        }
        self.jobs[session.session_id] = job

        task = asyncio.create_task(asyncio.to_thread(self._render, job, film_data))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info(
            "Film render queued for session_id={} beats={} job_id={}",
            session.session_id, len(beats), job["job_id"],
        )
        return self.job_public(job)

    # ------------------------------------------------------------------
    # Everything below runs in a worker thread.
    # ------------------------------------------------------------------

    def _render(self, job: dict, film: dict):
        workdir = RENDERS_DIR / f"tmp_{job['job_id']}"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            job["status"] = "rendering"

            font = self._prepare_font(workdir)
            beats = film["beats"]
            total_steps = len(beats) + 3  # cards + concat
            done_steps = 0

            def step(message: str):
                nonlocal done_steps
                done_steps += 1
                job["progress"] = min(done_steps / total_steps, 0.98)
                job["message"] = message

            segments: list[Path] = []

            job["message"] = "Preparing title card"
            title_card = self._render_title_card(workdir, film, font)
            segments.append(title_card)
            step("Title card ready")

            for index, beat in enumerate(beats):
                job["message"] = f"Rendering scene {index + 1} of {len(beats)}"
                segments.append(self._render_beat_segment(workdir, film, beat, index, font))
                step(f"Scene {index + 1} of {len(beats)} rendered")

            job["message"] = "Preparing end card"
            segments.append(self._render_end_card(workdir, font))
            step("End card ready")

            job["message"] = "Assembling final film"
            output = RENDERS_DIR / f"{film['session_id']}.mp4"
            self._concat_with_crossfades(workdir, segments, output)

            job["output_path"] = str(output)
            job["progress"] = 1.0
            job["status"] = "done"
            job["message"] = "Film ready"
            logger.info("Film render complete for session_id={} -> {}", film["session_id"], output)
        except Exception as exc:
            logger.exception("Film render failed for session_id={}: {}", film["session_id"], exc)
            job["status"] = "error"
            job["error"] = str(exc)[:400]
            job["message"] = "Render failed"
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _run(self, args: list[str], cwd: Path):
        result = subprocess.run(
            args, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            tail = (result.stderr or "").strip().splitlines()[-6:]
            raise FilmError("ffmpeg failed: " + " | ".join(tail))

    def _probe_duration(self, path: Path) -> float:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            capture_output=True, text=True,
        )
        try:
            return float(result.stdout.strip())
        except ValueError as exc:
            raise FilmError(f"Could not probe duration of {path.name}") from exc

    def _prepare_font(self, workdir: Path) -> str | None:
        """Copy a serif/sans font into the workdir so drawtext can use a
        relative path (absolute Windows paths need filter escaping)."""
        for candidate in FONT_CANDIDATES:
            source = Path(candidate)
            if source.is_file():
                shutil.copy(source, workdir / "font.ttf")
                return "font.ttf"
        logger.warning("No font found for drawtext — film will have no burned-in text")
        return None

    def _write_textfile(self, workdir: Path, name: str, text: str, wrap: int | None = None) -> str:
        content = text.strip()
        if wrap:
            content = "\n".join(textwrap.wrap(content, wrap)) or content
        (workdir / name).write_text(content, encoding="utf-8")
        return name

    def _drawtext(self, textfile: str, font: str, fontsize: int, y: str, enable: str | None = None) -> str:
        filter_expr = (
            f"drawtext=textfile={textfile}:fontfile={font}:fontsize={fontsize}:"
            "fontcolor=0xf7e9bf:borderw=2:bordercolor=black@0.6:"
            f"x=(w-text_w)/2:y={y}:box=1:boxcolor=black@0.45:boxborderw=14:"
            "line_spacing=8"
        )
        if enable:
            filter_expr += f":enable='{enable}'"
        return filter_expr

    def _subtitle_filters(self, workdir: Path, index: int, text: str, font: str, duration: float) -> list[str]:
        """Burn the beat's prose as sequential subtitle chunks, timed
        proportionally to each chunk's length across the beat."""
        chunks = _chunk_prose(text)
        if not chunks:
            return []
        max_chunks = max(1, int(duration // SUBTITLE_MIN_SECONDS))
        merge_chars = SUBTITLE_MAX_CHARS
        while len(chunks) > max_chunks:
            merge_chars = int(merge_chars * 1.5)
            chunks = _chunk_prose(text, merge_chars)

        filters = []
        weights = [len(chunk) for chunk in chunks]
        total_weight = sum(weights)
        window = duration - 0.2
        start = 0.0
        for chunk_index, chunk in enumerate(chunks):
            end = start + window * weights[chunk_index] / total_weight
            textfile = self._write_textfile(
                workdir, f"sub_{index}_{chunk_index}.txt", chunk, wrap=SUBTITLE_WRAP_CHARS,
            )
            filters.append(self._drawtext(
                textfile, font, 26, "h-text_h-40",
                enable=f"between(t\\,{start:.2f}\\,{end:.2f})",
            ))
            start = end
        return filters

    def _render_card(self, workdir: Path, name: str, filters: list[str], fade_in: bool, fade_out: bool) -> Path:
        chain = filters[:]
        if fade_in:
            chain.append("fade=t=in:st=0:d=1")
        if fade_out:
            chain.append(f"fade=t=out:st={CARD_SECONDS - 1:.2f}:d=1")
        chain.append("format=yuv420p")
        output = workdir / name
        self._run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i",
            f"color=c=0x0d0f18:s={FILM_WIDTH}x{FILM_HEIGHT}:d={CARD_SECONDS}:r={FILM_FPS}",
            "-f", "lavfi", "-t", str(CARD_SECONDS), "-i", "anullsrc=r=44100:cl=stereo",
            "-filter_complex", f"[0:v]{','.join(chain)}[v]",
            "-map", "[v]", "-map", "1:a", "-t", str(CARD_SECONDS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            name,
        ], cwd=workdir)
        return output

    def _render_title_card(self, workdir: Path, film: dict, font: str | None) -> Path:
        filters = []
        if font:
            title_file = self._write_textfile(workdir, "title.txt", film["title"] or "Untitled", wrap=26)
            subtitle_file = self._write_textfile(
                workdir, "subtitle.txt",
                f"A Luminary film · {film['genre']}".strip(),
            )
            filters.append(self._drawtext(title_file, font, 58, "(h-text_h)/2-40"))
            filters.append(self._drawtext(subtitle_file, font, 26, "(h-text_h)/2+70"))
        return self._render_card(workdir, "seg_title.mp4", filters, fade_in=True, fade_out=False)

    def _render_end_card(self, workdir: Path, font: str | None) -> Path:
        filters = []
        if font:
            end_file = self._write_textfile(workdir, "endcard.txt", "The End")
            filters.append(self._drawtext(end_file, font, 52, "(h-text_h)/2"))
        return self._render_card(workdir, "seg_end.mp4", filters, fade_in=False, fade_out=True)

    def _synthesize_beat_audio(self, workdir: Path, film: dict, beat: dict, index: int) -> Path | None:
        if not self.narration_service or not beat["narration"].strip():
            return None
        try:
            result = self.narration_service.synthesize(
                text=beat["narration"],
                genre=film["genre"],
                voice_name=film.get("voice_name"),
                language_code=film.get("language_code"),
            )
            audio_path = workdir / f"beat_{index}.mp3"
            audio_path.write_bytes(base64.b64decode(result["audio_base64"]))
            return audio_path
        except Exception as exc:
            logger.warning("Beat {} narration synthesis failed, using silence: {}", index, exc)
            return None

    def _ken_burns(self, index: int, frames: int) -> str:
        rate = (MAX_ZOOM - 1.0) / max(frames, 1)
        center_x = "iw/2-(iw/zoom)/2"
        center_y = "ih/2-(ih/zoom)/2"
        style = index % 4
        if style == 0:  # slow zoom in
            zoom, x, y = f"1+{rate:.6f}*on", center_x, center_y
        elif style == 1:  # slow zoom out
            zoom, x, y = f"max({MAX_ZOOM}-{rate:.6f}*on\\,1)", center_x, center_y
        elif style == 2:  # pan right
            zoom, x, y = "1.08", f"(iw-iw/zoom)*on/{frames}", center_y
        else:  # pan left
            zoom, x, y = "1.08", f"(iw-iw/zoom)*(1-on/{frames})", center_y
        return (
            f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:"
            f"s={FILM_WIDTH}x{FILM_HEIGHT}:fps={FILM_FPS}"
        )

    def _render_beat_segment(self, workdir: Path, film: dict, beat: dict, index: int, font: str | None) -> Path:
        extension = IMAGE_EXTENSIONS.get(beat["mime_type"], "png")
        image_path = workdir / f"beat_{index}.{extension}"
        image_path.write_bytes(base64.b64decode(beat["image"]))

        narration_text = (beat["narration"] or "").strip()[:NARRATION_MAX_CHARS]
        audio_path = self._synthesize_beat_audio(workdir, film, beat, index)
        if audio_path:
            duration = self._probe_duration(audio_path) + NARRATION_TAIL_SECONDS
        else:
            # Silent beat: hold the scene long enough to read the prose.
            word_count = len(narration_text.split())
            duration = word_count / READING_WORDS_PER_SECOND + 1.2 if word_count else 6.0
        duration = max(MIN_BEAT_SECONDS, min(duration, MAX_BEAT_SECONDS))
        frames = int(duration * FILM_FPS)

        # Upscale before zoompan to avoid sub-pixel jitter during the pan.
        big_w, big_h = FILM_WIDTH * 4, FILM_HEIGHT * 4
        video_chain = [
            f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase",
            f"crop={big_w}:{big_h}",
            "setsar=1",
            self._ken_burns(index, frames),
        ]
        if font:
            subtitle_text = narration_text or beat["caption"].strip()
            video_chain += self._subtitle_filters(workdir, index, subtitle_text, font, duration)
        video_chain.append("format=yuv420p")

        name = f"seg_beat_{index}.mp4"
        args = ["ffmpeg", "-y", "-i", image_path.name]
        if audio_path:
            args += ["-i", audio_path.name]
            audio_filter = f"[1:a]apad,atrim=0:{duration:.3f}[a]"
        else:
            args += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
            audio_filter = f"[1:a]atrim=0:{duration:.3f}[a]"
        args += [
            "-filter_complex", f"[0:v]{','.join(video_chain)}[v];{audio_filter}",
            "-map", "[v]", "-map", "[a]", "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            name,
        ]
        self._run(args, cwd=workdir)
        return workdir / name

    def _concat_with_crossfades(self, workdir: Path, segments: list[Path], output: Path):
        if len(segments) == 1:
            shutil.copy(segments[0], output)
            return

        durations = [self._probe_duration(segment) for segment in segments]
        inputs: list[str] = []
        for segment in segments:
            inputs += ["-i", segment.name]

        video_parts = []
        audio_parts = []
        offset = 0.0
        for index in range(1, len(segments)):
            offset += durations[index - 1] - CROSSFADE_SECONDS
            prev_v = "[0:v]" if index == 1 else f"[v{index - 1}]"
            prev_a = "[0:a]" if index == 1 else f"[a{index - 1}]"
            video_parts.append(
                f"{prev_v}[{index}:v]xfade=transition=fade:"
                f"duration={CROSSFADE_SECONDS}:offset={offset:.3f}[v{index}]"
            )
            audio_parts.append(
                f"{prev_a}[{index}:a]acrossfade=d={CROSSFADE_SECONDS}[a{index}]"
            )

        last = len(segments) - 1
        filter_complex = ";".join(video_parts + audio_parts)
        self._run([
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex,
            "-map", f"[v{last}]", "-map", f"[a{last}]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output),
        ], cwd=workdir)
