# MoneyPrinterTurbo: high-level capabilities

MoneyPrinterTurbo is a configurable production pipeline for creating short-form
videos. It turns a topic or a supplied script into one or more finished videos
by combining a script, narration, visual material, subtitles, music, and video
editing. It can be used interactively or embedded in an automated workflow.

## What a user can do

### Create videos through multiple interfaces

- Use the WebUI for guided creation, previews, settings, task history, and
  management of generated assets.
- Use the CLI for repeatable local or scripted runs.
- Use the HTTP API for integrations and queue-based automation.
- Give an AI agent the included skill instructions to install, configure, and
  run the workflow from a natural-language prompt.

The API also supports stage-specific jobs: generate a full video, narration
audio only, or subtitles only. Generation is asynchronous; callers create a
task, then inspect its status and retrieve its output.

### Start with either an idea or finished copy

- Provide a topic and have an LLM draft a multilingual video script.
- Provide or revise a complete script yourself.
- Extract visual search terms from the script, including terms aligned to the
  script order when visuals should follow the narration scene by scene.
- Generate social-post metadata for a selected platform.
- Customize the script prompt, system prompt, language, and number of
  paragraphs.

LLM access is provider-agnostic: the project includes first-class settings for
major hosted services and supports OpenAI-compatible gateways and local
runtimes.

### Supply or generate visuals

The visual-material stage can use:

- Locally uploaded images and video clips.
- Stock footage from Pexels, Pixabay, and Coverr.
- AI video integrations including Metaso MiniMax, Shengsuan Cloud, VolcEngine
  Ark Seedance, WaveSpeed, and OFox.
- OpenAI-compatible image-generation endpoints, whose images can be made into
  animated video material.

Users can choose the source, upload files through the UI or API, control clip
duration and speed, choose random or sequential concatenation, select
transitions, fit material using `cover` or `contain`, and request visuals that
match the script's sequence.

### Build the sound and captions

- Use automatic text-to-speech, a custom uploaded audio track, or no
  voiceover.
- Preview available voices and tune voice rate and volume.
- Choose from Edge TTS (the built-in no-key default), Azure, SiliconFlow,
  Gemini, Xiaomi MiMo, MiniMax, ElevenLabs, Chatterbox, Fish Audio, and
  compatible voice services.
- Produce subtitles from TTS timestamps (fast, default) or local
  `faster-whisper` transcription (more accurate timing).
- Style subtitles: font, size, foreground/outline colors and width, background,
  rounded background, position, word-by-word or sentence display, and a
  pop-spring animation.
- Add random or selected local music, or generate music with Sonilo or
  ElevenLabs; music and narration have separate volume controls.

### Produce and distribute the final video

- Create one video or a batch of variants from the same request.
- Export landscape 16:9 at 1920x1080, portrait 9:16 at 1080x1920, or square
  1:1 at 1080x1080.
- Stream or download completed task artifacts through the API.
- Review task history, restore a prior task's settings, and safely remove
  completed task output.
- Optionally cross-post completed videos to TikTok, Instagram, YouTube, and
  Facebook Reels when the publishing integration is configured.

## End-to-end workflow

```text
Topic or script
      |
      +--> script generation / refinement (optional)
      +--> visual terms and scene alignment (optional)
      |
Voiceover or custom audio --> subtitle timing --> visual material selection
      |                                          |
      +-----------------------> compose, caption, mix music
                                                   |
                                    final MP4(s) and optional cross-posting
```

The orchestration service records progress and failure details per task. Its
pipeline can stop after the audio or subtitle stage, which makes those assets
reusable outside a full video generation run.

## Interfaces and operational model

- **WebUI:** the main authoring experience; includes onboarding, previews,
  credential/settings panels, cached-material management, task history, and
  output controls.
- **CLI:** an automation-friendly entry point for creating videos without the
  browser UI.
- **REST API:** authenticated when `app.api_key` is configured. Its core paths
  are `/api/v1/videos`, `/api/v1/audio`, `/api/v1/subtitle`, task listing and
  lookup, local material/music upload and listing, streaming/download, and LLM
  endpoints for scripts, terms, and social metadata.
- **Task execution:** jobs run through a task manager with persisted state;
  task status includes progress, outputs, and structured errors. A Redis-backed
  manager is available alongside in-memory operation.

## Important configuration boundaries

The product is usable locally with Edge TTS and locally supplied assets, but
many capabilities require a provider account, API key, or a locally installed
dependency. In particular:

- Stock footage and hosted AI media services need their respective credentials.
- Hosted LLM, TTS, image, video, music, and publishing providers must be
  enabled and configured before selection.
- Whisper subtitle timing downloads a local model on first use and benefits
  from GPU resources, though a GPU is not mandatory for the core application.
- Video rendering depends on the local FFmpeg/MoviePy toolchain; the project
  supports several hardware-accelerated H.264 encoders when available.

## Where these capabilities live in the codebase

- `webui/Main.py` — interactive authoring, configuration, previews, and task
  management.
- `cli.py` — command-line entry point.
- `app/controllers/v1/` — REST endpoints for generation, tasks, assets, and
  LLM utilities.
- `app/services/task.py` — staged generation orchestration, task lifecycle,
  batching, and cross-post scheduling.
- `app/services/video.py` — rendering, fitting, concatenation, subtitle
  compositing, audio mixing, and encoding.
- `app/services/` — individual LLM, voice, material, subtitle, music,
  cache, upload, and provider adapters.
- `config.example.toml` — configuration template and provider credentials.

## Source of truth

This guide describes capabilities currently wired into the repository. For
provider-specific setup and current user instructions, see
[`README-en.md`](../README-en.md),
[`config.example.toml`](../config.example.toml), and the relevant WebUI settings.
