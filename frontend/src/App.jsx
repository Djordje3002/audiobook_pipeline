import { useEffect, useMemo, useState } from 'react';

const initialResult = null;

const OPERATION_CONFIG = {
  idle: {
    label: 'Idle',
    phases: ['Ready'],
    phaseDurationsSec: [1],
    maxProgressBeforeDone: 0,
  },
  upload: {
    label: 'Uploading',
    phases: ['Preparing file', 'Uploading to server', 'Saving input file'],
    phaseDurationsSec: [1, 2, 2],
    maxProgressBeforeDone: 88,
  },
  preview: {
    label: 'Translation preview',
    phases: [
      'Transcribing with Whisper',
      'Grouping transcript segments',
      'Extracting glossary',
      'Translating with GPT-4o',
      'Loading translated output',
    ],
    phaseDurationsSec: [10, 4, 3, 25, 3],
    maxProgressBeforeDone: 94,
  },
  full: {
    label: 'Full translation',
    phases: [
      'Transcribing with Whisper',
      'Grouping transcript segments',
      'Extracting glossary',
      'Translating full content',
      'Loading translated output',
    ],
    phaseDurationsSec: [14, 5, 4, 45, 3],
    maxProgressBeforeDone: 95,
  },
};

async function parseJsonOrError(response) {
  const text = await response.text();
  let data = null;

  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { status: 'error', error: text || 'Non-JSON response from server.' };
  }

  if (!response.ok) {
    const serverError = data?.error || `Request failed with status ${response.status}`;
    throw new Error(serverError);
  }

  return data;
}

function formatSeconds(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return '-';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60)
    .toString()
    .padStart(2, '0');
  return `${mins}:${secs}`;
}

function toSlug(filename) {
  return (
    filename
      .replace(/\.[^/.]+$/, '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'moja_knjiga'
  );
}

function formatUsd(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '-';
  return `$${amount.toFixed(2)}`;
}

function estimatePreRunCost(durationSec) {
  if (!Number.isFinite(durationSec) || durationSec <= 0) return null;
  const durationMin = durationSec / 60;
  const whisperUsd = durationMin * 0.006;
  const estimatedChars = durationMin * 900; // rough narration density estimate
  const gptUsd = (estimatedChars / 1_000_000) * 20;
  return {
    durationMin,
    estimatedChars,
    whisperUsd,
    gptUsd,
    totalUsd: whisperUsd + gptUsd,
  };
}

function errorHelp(message) {
  const msg = String(message || '').toLowerCase();

  if (msg.includes('unexpected keyword argument') && msg.includes('proxies')) {
    return {
      title: 'Dependency mismatch',
      fix: 'Run `pip install -r requirements.txt` to install compatible OpenAI/httpx versions.',
    };
  }
  if (msg.includes('401') || msg.includes('access denied') || msg.includes('authentication')) {
    return {
      title: 'Authentication failed',
      fix: 'Check APP_USERNAME and APP_PASSWORD in .env, then re-enter them in the UI.',
    };
  }
  if (msg.includes('source_path is required') || msg.includes('upload a file first')) {
    return {
      title: 'No source file selected',
      fix: 'Upload an audio file first, then run preview or full translation.',
    };
  }
  if (msg.includes('input audio file not found')) {
    return {
      title: 'Source file missing on server',
      fix: 'Upload the file again to regenerate a valid source path.',
    };
  }
  if (msg.includes('ffmpeg')) {
    return {
      title: 'FFmpeg is missing',
      fix: 'Install FFmpeg locally and restart the backend process.',
    };
  }
  return {
    title: 'Pipeline error',
    fix: 'Check the raw API response below for details and retry once.',
  };
}

function progressState(operation, elapsedSec) {
  const config = OPERATION_CONFIG[operation] || OPERATION_CONFIG.idle;
  const totalExpected = config.phaseDurationsSec.reduce((sum, item) => sum + item, 0);
  const cappedElapsed = Math.min(elapsedSec, totalExpected);

  let remaining = cappedElapsed;
  let phaseIndex = 0;
  for (let idx = 0; idx < config.phaseDurationsSec.length; idx += 1) {
    if (remaining <= config.phaseDurationsSec[idx]) {
      phaseIndex = idx;
      break;
    }
    remaining -= config.phaseDurationsSec[idx];
    phaseIndex = idx;
  }

  const pct = totalExpected
    ? Math.min(config.maxProgressBeforeDone, Math.max(4, Math.round((cappedElapsed / totalExpected) * config.maxProgressBeforeDone)))
    : 0;

  return {
    phaseIndex,
    progressPct: pct,
    phases: config.phases,
    label: config.label,
  };
}

export default function App() {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedDurationSec, setSelectedDurationSec] = useState(0);
  const [sourcePath, setSourcePath] = useState('');
  const [bookTitle, setBookTitle] = useState('moja_knjiga');
  const [skipTranscription, setSkipTranscription] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [loading, setLoading] = useState(false);
  const [operation, setOperation] = useState('idle');
  const [elapsedSec, setElapsedSec] = useState(0);
  const [progressPct, setProgressPct] = useState(0);
  const [activePhaseIndex, setActivePhaseIndex] = useState(0);
  const [statusText, setStatusText] = useState('Ready. Step 1: enter credentials. Step 2: upload file. Step 3: run.');

  const [result, setResult] = useState(initialResult);
  const [error, setError] = useState('');
  const [translatedSegments, setTranslatedSegments] = useState([]);
  const [translationArtifactError, setTranslationArtifactError] = useState('');

  const authHeader = useMemo(() => {
    if (!username || !password) return '';
    return `Basic ${btoa(`${username}:${password}`)}`;
  }, [username, password]);

  const translatedPath = useMemo(() => {
    if (!result) return '';
    return result.translated_path || '';
  }, [result]);

  const translatedMediaUrl = useMemo(() => {
    if (!translatedPath) return '';
    return `/media/${encodeURI(translatedPath)}`;
  }, [translatedPath]);

  const currentPhases = OPERATION_CONFIG[operation]?.phases || OPERATION_CONFIG.idle.phases;
  const errGuide = error ? errorHelp(error) : null;
  const preRunEstimate = useMemo(() => estimatePreRunCost(selectedDurationSec), [selectedDurationSec]);
  const backendEstimate = result?.cost_estimate || null;

  useEffect(() => {
    if (!loading || operation === 'idle') return undefined;

    const timer = setInterval(() => {
      setElapsedSec((prev) => {
        const next = prev + 1;
        const state = progressState(operation, next);
        setActivePhaseIndex(state.phaseIndex);
        setProgressPct(state.progressPct);
        return next;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [loading, operation]);

  useEffect(() => {
    async function loadTranslatedArtifact() {
      if (!translatedMediaUrl) {
        setTranslatedSegments([]);
        setTranslationArtifactError('');
        return;
      }

      try {
        const response = await fetch(translatedMediaUrl, {
          headers: authHeader ? { Authorization: authHeader } : {},
        });
        const data = await parseJsonOrError(response);
        if (!Array.isArray(data)) {
          throw new Error('Translated artifact is not a segment array.');
        }
        setTranslatedSegments(data);
        setTranslationArtifactError('');
      } catch (artifactError) {
        setTranslatedSegments([]);
        setTranslationArtifactError(artifactError.message);
      }
    }

    loadTranslatedArtifact();
  }, [translatedMediaUrl, authHeader]);

  function handleFileSelection(file) {
    setSelectedFile(file);
    setSelectedDurationSec(0);

    if (!file) return;

    const objectUrl = URL.createObjectURL(file);
    const probe = document.createElement('audio');
    probe.preload = 'metadata';
    probe.src = objectUrl;
    probe.onloadedmetadata = () => {
      if (Number.isFinite(probe.duration)) {
        setSelectedDurationSec(probe.duration);
      }
      URL.revokeObjectURL(objectUrl);
    };
    probe.onerror = () => {
      URL.revokeObjectURL(objectUrl);
    };
  }

  function startOperation(nextOperation, text) {
    setOperation(nextOperation);
    setElapsedSec(0);
    setProgressPct(4);
    setActivePhaseIndex(0);
    setStatusText(text);
  }

  function finishOperation(successText) {
    setProgressPct(100);
    setStatusText(successText);
    setLoading(false);
    setTimeout(() => {
      setOperation('idle');
    }, 800);
  }

  async function uploadAudioFile() {
    if (!selectedFile) {
      setError('Select an audio file first.');
      return;
    }

    if (!authHeader) {
      setError('Enter API credentials first.');
      return;
    }

    setLoading(true);
    setError('');
    startOperation('upload', `Uploading ${selectedFile.name}...`);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const response = await fetch('/api/upload', {
        method: 'POST',
        headers: authHeader ? { Authorization: authHeader } : {},
        body: formData,
      });
      const data = await parseJsonOrError(response);
      setSourcePath(data.source_path || '');
      setBookTitle((prev) => (prev.trim() && prev !== 'moja_knjiga' ? prev : toSlug(data.filename || selectedFile.name)));
      setResult(data);
      finishOperation(`Uploaded: ${data.filename}`);
    } catch (uploadError) {
      setError(uploadError.message);
      setStatusText('Upload failed.');
      setLoading(false);
      setOperation('idle');
    }
  }

  async function runPipeline(mode) {
    if (!authHeader) {
      setError('Enter API credentials first.');
      return;
    }

    if (!sourcePath.trim()) {
      setError('Upload a file first.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);
    setTranslatedSegments([]);
    setTranslationArtifactError('');

    startOperation(
      mode,
      mode === 'preview' ? 'Running 5-minute translation preview...' : 'Running full translation...',
    );

    const endpoint = mode === 'preview' ? '/api/preview' : '/api/full';
    const payload = {
      source_path: sourcePath.trim(),
      book_title: bookTitle.trim() || undefined,
      skip_transcription: skipTranscription,
    };

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeader ? { Authorization: authHeader } : {}),
        },
        body: JSON.stringify(payload),
      });
      const data = await parseJsonOrError(response);
      setResult(data);

      if (data.status === 'success') {
        finishOperation(
          mode === 'preview'
            ? 'Translation preview completed successfully.'
            : 'Full translation completed successfully.',
        );
      } else {
        setError(data.error || 'Pipeline finished with errors.');
        setStatusText('Pipeline finished with errors.');
        setLoading(false);
        setOperation('idle');
      }
    } catch (pipelineError) {
      setError(pipelineError.message);
      setStatusText('Pipeline request failed.');
      setLoading(false);
      setOperation('idle');
    }
  }

  return (
    <div className="page-shell">
      <header className="hero">
        <p className="eyebrow">Audiobook Pipeline</p>
        <h1>Serbian to English Translation MVP</h1>
        <p>
          Upload Serbian audiobook audio, run translation preview/full mode, and inspect translated segments.
        </p>
      </header>

      <div className="warning-banner">
        Voice cloning is temporarily disabled for MVP. ElevenLabs integration is preserved in code and can be
        re-enabled later.
      </div>

      <main className="layout-grid">
        <section className="panel">
          <h2>0) API Credentials</h2>
          <label>
            Username
            <input type="text" value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
        </section>

        <section className="panel">
          <h2>1) Upload Source Audio</h2>
          <input
            className="file-input"
            type="file"
            accept="audio/*,.mp3,.wav,.flac,.m4a"
            onChange={(event) => handleFileSelection(event.target.files?.[0] || null)}
          />
          <button className="action-button" onClick={uploadAudioFile} disabled={loading || !selectedFile || !authHeader}>
            {loading && operation === 'upload' ? 'Uploading...' : 'Upload File'}
          </button>
        </section>

        <section className="panel">
          <h2>2) Run Translation</h2>
          <p className="status">Uploaded Source: {sourcePath ? <code>{sourcePath}</code> : 'No file uploaded yet.'}</p>

          <label>
            Book Title
            <input type="text" value={bookTitle} onChange={(event) => setBookTitle(event.target.value)} />
          </label>

          <div className="button-row">
            <button className="action-button" disabled={loading || !sourcePath || !authHeader} onClick={() => runPipeline('preview')}>
              Run 5-Minute Translation Preview
            </button>
            <button className="action-button secondary" disabled={loading || !sourcePath || !authHeader} onClick={() => runPipeline('full')}>
              Run Full Translation
            </button>
          </div>

          <button
            className="link-button"
            type="button"
            onClick={() => setShowAdvanced((prev) => !prev)}
          >
            {showAdvanced ? 'Hide Advanced Options' : 'Show Advanced Options'}
          </button>

          {showAdvanced && (
            <div className="advanced-box">
              <label>
                Source Path (manual override)
                <input
                  type="text"
                  value={sourcePath}
                  placeholder="input_audio/knjiga.mp3"
                  onChange={(event) => setSourcePath(event.target.value)}
                />
              </label>

              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={skipTranscription}
                  onChange={(event) => setSkipTranscription(event.target.checked)}
                />
                Skip transcription on rerun (if transcript already exists)
              </label>
            </div>
          )}
        </section>

        <section className="panel wide">
          <h2>Cost Estimate</h2>
          <div className="cost-grid">
            <div className="cost-card">
              <h3>Before Run (Rough)</h3>
              {preRunEstimate ? (
                <>
                  <p>Duration: {preRunEstimate.durationMin.toFixed(2)} min</p>
                  <p>Whisper: {formatUsd(preRunEstimate.whisperUsd)}</p>
                  <p>GPT-4o Translation: {formatUsd(preRunEstimate.gptUsd)}</p>
                  <p><strong>Total: {formatUsd(preRunEstimate.totalUsd)}</strong></p>
                </>
              ) : (
                <p className="status">Select an audio file to see a rough pre-run estimate.</p>
              )}
            </div>

            <div className="cost-card">
              <h3>After Run (Backend)</h3>
              {backendEstimate ? (
                <>
                  <p>Duration: {Number(backendEstimate.duration_min || 0).toFixed(2)} min</p>
                  <p>Characters: {Number(backendEstimate.characters || 0).toLocaleString()}</p>
                  <p>Whisper: {formatUsd(backendEstimate.whisper_usd)}</p>
                  <p>GPT-4o Translation: {formatUsd(backendEstimate.gpt_translation_usd)}</p>
                  <p><strong>Total: {formatUsd(backendEstimate.total_usd)}</strong></p>
                </>
              ) : (
                <p className="status">Run preview/full once for backend-calculated estimate.</p>
              )}
            </div>
          </div>
        </section>

        <section className="panel wide">
          <h2>3) Progress & Status</h2>
          <div className="progress-head">
            <span>{statusText}</span>
            <span>{loading ? `${OPERATION_CONFIG[operation]?.label || 'Working'} • ${elapsedSec}s` : 'Idle'}</span>
          </div>
          <div className={`progress-track ${loading ? 'active' : ''}`}>
            <div className="progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="progress-meta">{progressPct}%</div>

          <ol className="phase-list">
            {currentPhases.map((phase, idx) => {
              const state = idx < activePhaseIndex ? 'done' : idx === activePhaseIndex ? 'active' : 'todo';
              return (
                <li key={phase} className={`phase-item ${state}`}>
                  <span className="phase-dot" />
                  <span>{phase}</span>
                </li>
              );
            })}
          </ol>

          {error && errGuide && (
            <div className="error-card">
              <strong>{errGuide.title}</strong>
              <p>{error}</p>
              <p className="error-fix">Fix: {errGuide.fix}</p>
            </div>
          )}

          {translationArtifactError && (
            <div className="error-card">
              <strong>Translated artifact load error</strong>
              <p>{translationArtifactError}</p>
            </div>
          )}

          <h3>Translated Segments</h3>
          {translatedSegments.length === 0 ? (
            <p className="status">No translated segments loaded yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="segment-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Time</th>
                    <th>Original (SR)</th>
                    <th>Translated (EN)</th>
                  </tr>
                </thead>
                <tbody>
                  {translatedSegments.map((segment) => (
                    <tr key={segment.segment_index}>
                      <td>{segment.segment_index}</td>
                      <td>{formatSeconds(segment.start)} - {formatSeconds(segment.end)}</td>
                      <td>{segment.original_text || '-'}</td>
                      <td>
                        <div>{segment.translated_text || '-'}</div>
                        <div className="segment-meta">
                          <strong>Status:</strong> {segment.translation_status || '-'}
                        </div>
                        <div className="segment-meta">
                          <strong>Warnings:</strong>{' '}
                          {Array.isArray(segment.validation_warnings) && segment.validation_warnings.length
                            ? segment.validation_warnings.join('; ')
                            : '-'}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3>Raw Translated JSON</h3>
          <pre>{translatedSegments.length ? JSON.stringify(translatedSegments, null, 2) : 'No translated artifact loaded yet.'}</pre>

          <h3>Last API Response</h3>
          <pre>{result ? JSON.stringify(result, null, 2) : 'No response yet.'}</pre>
        </section>
      </main>
    </div>
  );
}
