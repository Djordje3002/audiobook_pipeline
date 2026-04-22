# Audiobook Pipeline — Serbian to English Voice Transformation System

This system transforms existing Serbian-language audiobooks into professional English-language audiobooks using a cloned voice, preserving the original narrator's emotion, pacing, and intonation throughout the entire production process.

## What It Does

The pipeline accepts a Serbian audio file as input and produces a finished, ACX-compliant English audiobook as output. The process is fully automated with a single human review checkpoint before full production begins.

1. The system transcribes Serbian audio using OpenAI Whisper, producing timestamped segments that map precisely to the original recording.
2. Segments are translated to English using GPT-4o with a literary-quality prompt that preserves genre style, character voices, slang equivalents, and narrative rhythm.
3. Before translation begins, the system extracts a glossary of character names, recurring phrases, and stylistic notes from the source material to ensure consistency across the entire book.
4. Each translated text segment is paired with its corresponding original audio clip.
5. Clips are sent to the ElevenLabs Speech-to-Speech API using a Professional Voice Clone model, mapping the narrator's English clone voice onto the original audio while preserving emotional delivery, dramatic pauses, and intonation patterns.
6. Synthesized segments are joined with FFmpeg crossfades, processed with iterative RMS normalization, peak limiting, and a noise gate, then exported as ACX-ready audiobook files.

This Speech-to-Speech approach produces more natural results than text-to-speech because emotional performance comes from the original human recording instead of being generated only from text.

## Two-Phase Production Flow

The pipeline is preview-first to prevent unnecessary API costs.

- On upload, only the first five minutes are processed.
- The user listens to this preview and confirms voice quality.
- Full-book production starts only after confirmation.

This keeps failed attempts low-cost (cents) instead of consuming the full production budget.

## Technical Stack

### Transcription Layer

- OpenAI Whisper with Serbian language targeting.
- Overlap-based chunking to prevent sentence loss at chunk boundaries.
- Glossary-informed prompt to improve recognition of character names and domain terms.

### Translation Layer

- GPT-4o with a structured literary system prompt.
- Extracted glossary included on every API call.
- Timing constraint based on original segment duration to align English word count with Serbian pacing.
- Automatic validation for:
  - Missing character names.
  - Untranslated Serbian characters.
  - Unwanted GPT commentary.

### Synthesis Layer

- ElevenLabs Speech-to-Speech with configurable:
  - Stability.
  - Similarity.
  - Style.
- Automatic fallback to text-to-speech if Speech-to-Speech fails.
- Full resume support so interrupted runs continue from the last completed segment.

### Post-Production Layer

- Noise gate before normalization to clean ElevenLabs background artifacts.
- Iterative gain correction targeting -19 dB RMS.
- Hard peak limiting at -3.5 dBFS.
- ACX compliance verification across all required parameters before export.

## ACX Compliance Targets

- RMS amplitude: between -23 dB and -18 dB (working target: -19 dB).
- Peak level: below -3 dBFS (working ceiling: -3.5 dBFS).
- Noise floor: below -60 dBFS (achieved via noise gate preprocessing).

Every exported file includes a JSON report with measured values and pass/fail status for each required metric.

## Output Formats

- MP3 at 192 kbps.
- Lossless FLAC.

## Cost Structure

Cost scales with audiobook length.

- Example: a 6-hour book is approximately $45 total across Whisper transcription, GPT-4o translation, and ElevenLabs Speech-to-Speech synthesis.
- Preview phase costs under $1 regardless of total book length.

## Infrastructure

- Flask web application.
- Deployable to Railway or any Python-compatible host.
- HTTP Basic Authentication for access control.
- OpenAI and ElevenLabs keys can be provided per run from the UI (recommended for client billing separation), with `.env` fallback for CLI/server defaults.
- Supports large uploads, long-running background jobs, and resume-capable processing without requiring an open browser session.

## Product Goal

Build a fully automated, production-grade audiobook localization pipeline that preserves storytelling performance while delivering ACX-compliant English audiobooks efficiently and cost-effectively.

## Recommended Repository Structure

```text
audiobook_pipeline/
├── .env
├── .gitignore
├── README.md
├── requirements.txt
├── Procfile
├── runtime.txt
├── app.py
├── auth.py
├── config.py
├── main.py
├── modules/
│   ├── __init__.py
│   ├── audio_ingestion.py
│   ├── translation.py
│   ├── synthesis.py
│   └── postproduction.py
├── utils/
│   ├── __init__.py
│   ├── cost_estimator.py
│   └── validators.py
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   └── app.js
├── input_audio/
│   └── .gitkeep
├── output_audio/
│   ├── chapter_01/
│   ├── final/
│   └── previews/
├── output/
│   ├── translated/
│   └── reports/
└── temp_chunks/
    └── .gitkeep
```

## What Lives Where (And Why)

- Root level contains only immediate configuration, deployment, and entrypoint files.
- `modules/` is the core pipeline: each file owns one stage only.
- `utils/` contains cross-cutting helpers used by multiple stages.
- `templates/` and `static/` follow Flask conventions for UI assets.
- `input_audio/` is read-only source input for uploaded Serbian audiobooks.
- `output_audio/` stores synthesized segments, previews, and final mastered exports.
- `output/` stores text artifacts, glossary/translation JSON, and ACX reports.
- `temp_chunks/` is ephemeral processing storage for Whisper chunking.

## Running The Web App (React + Flask)

### Backend (Flask API)

```bash
cd /Users/djordjes/Desktop/AiVoiceTranslator/audiobook_pipeline
source venv/bin/activate
gunicorn app:app --timeout 120 --workers 1 --bind 0.0.0.0:8080
```

### Frontend (React dev mode)

```bash
cd /Users/djordjes/Desktop/AiVoiceTranslator/audiobook_pipeline/frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173` for development.

### Frontend (build for Flask serving)

```bash
cd /Users/djordjes/Desktop/AiVoiceTranslator/audiobook_pipeline/frontend
npm install
npm run build
```

After build, Flask serves the React app from `frontend/dist` at `http://127.0.0.1:8080`.

## Text-Only MVP Mode (Current)

Current MVP runs in text-only mode to reduce costs:
- Whisper transcription (Serbian)
- GPT-4o literary translation (English)
- Segment table + JSON shown in the React UI

Voice cloning, synthesis, and ACX export are temporarily disabled in orchestration.
For web runs, `openai_api_key` is required in API requests so translation always bills the end user's key.

### MVP Run Order

1. Upload source audio in the web app.
2. Paste your **OpenAI API key** in Step 2 (Run Translation).
3. Run **5-Minute Translation Preview**.
4. Review translated segments in the table.
5. Run **Full Translation** when preview quality is good.

Primary output files:
- `output/translated/<book>_transcript.json`
- `output/translated/<book>_glossary.json`
- `output/translated/<book>_translated.json`

## Re-Enable Voice Stage Later

When budget allows:
1. Uncomment the `TODO(re-enable-voice-stage)` blocks in `main.py`.
2. Restore voice-stage env validation by requiring ElevenLabs keys in runtime checks.
3. Run preview/full again to regenerate synthesized audio and ACX outputs.
