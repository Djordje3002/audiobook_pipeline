import { useEffect, useMemo, useRef, useState } from 'react';

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

const WORD_TOKEN_RE = /^[A-Za-z0-9ČĆŽŠĐčćžšđÀ-ÖØ-öø-ÿĀ-ž]+$/;
const WORD_SPLIT_RE = /([A-Za-z0-9ČĆŽŠĐčćžšđÀ-ÖØ-öø-ÿĀ-ž]+)/g;
const DEFAULT_READER_PLAYBACK_RATE = 0.75;
const DEFAULT_ELEVENLABS_PLAYBACK_RATE = 1.0;
const DEFAULT_TTS_BASE_RATE = 200;
const ELEVENLABS_WORDS_PER_MINUTE = 150;

const ELEVENLABS_MODEL_OPTIONS = [
  {
    id: 'eleven_flash_v2_5',
    label: 'Eleven Flash v2.5',
    costPerMinuteUsd: 0.08,
    note: 'Fastest, lower quality',
  },
  {
    id: 'eleven_turbo_v2_5',
    label: 'Eleven Turbo v2.5',
    costPerMinuteUsd: 0.20,
    note: 'Balanced speed/quality',
  },
  {
    id: 'eleven_multilingual_v2',
    label: 'Eleven Multilingual v2',
    costPerMinuteUsd: 0.30,
    note: 'Highest quality multilingual',
  },
];

const CREDENTIAL_STORAGE = {
  username: 'audiobook_pipeline_username',
  password: 'audiobook_pipeline_password',
};

function getStoredCredential(key, fallback = '') {
  if (typeof window === 'undefined') return fallback;
  try {
    return window.localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}


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

  if (
    msg.includes('elevenlabs quota exceeded') ||
    (msg.includes('elevenlabs') && msg.includes('quota_exceeded')) ||
    (msg.includes('elevenlabs') && msg.includes('quota exceeded')) ||
    msg.includes('credits remaining')
  ) {
    return {
      title: 'ElevenLabs quota exceeded',
      fix: 'Your ElevenLabs credits are 0. Add credits/upgrade plan, shorten text, or use Local reader mode.',
    };
  }
  if (msg.includes('elevenlabs authentication failed') || (msg.includes('elevenlabs') && msg.includes('invalid_api_key'))) {
    return {
      title: 'ElevenLabs API key invalid',
      fix: 'Paste a valid ElevenLabs API key in the ElevenLabs card and retry.',
    };
  }
  if (msg.includes('elevenlabs') && msg.includes('voice')) {
    return {
      title: 'ElevenLabs voice issue',
      fix: 'Load voices from ElevenLabs and select one, or paste a valid Voice ID.',
    };
  }
  if (msg.includes('elevenlabs') && msg.includes('model')) {
    return {
      title: 'ElevenLabs model issue',
      fix: 'Choose a supported model in the ElevenLabs card and retry.',
    };
  }
  if (msg.includes('elevenlabs') && msg.includes('429')) {
    return {
      title: 'ElevenLabs rate limit',
      fix: 'Wait a minute and retry, or generate shorter chunks.',
    };
  }
  if (msg.includes('elevenlabs') && msg.includes('401')) {
    return {
      title: 'ElevenLabs authentication failed',
      fix: 'Check ElevenLabs API key in the ElevenLabs card (this is separate from app login credentials).',
    };
  }

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
  if (msg.includes('openai_api_key is required')) {
    return {
      title: 'OpenAI API key missing',
      fix: 'Paste your OpenAI key in Step 2 (Run Translation), then start preview/full.',
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

function elevenlabsErrorHelp(message) {
  const msg = String(message || '').toLowerCase();

  if (msg.includes('quota exceeded') || msg.includes('quota_exceeded') || msg.includes('credits remaining')) {
    return {
      title: 'ElevenLabs quota exceeded',
      fix: 'Add credits/upgrade, shorten text, or use Local reader mode.',
    };
  }
  if (msg.includes('authentication failed') || msg.includes('invalid_api_key')) {
    return {
      title: 'ElevenLabs authentication failed',
      fix: 'Paste a valid ElevenLabs API key in the ElevenLabs card.',
    };
  }
  if (msg.includes('voice')) {
    return {
      title: 'ElevenLabs voice issue',
      fix: 'Load voices and select one, or paste a valid Voice ID manually.',
    };
  }
  if (msg.includes('model')) {
    return {
      title: 'ElevenLabs model issue',
      fix: 'Switch to another model in the ElevenLabs card.',
    };
  }
  if (msg.includes('429')) {
    return {
      title: 'ElevenLabs rate limit',
      fix: 'Wait a minute and retry.',
    };
  }
  return {
    title: 'ElevenLabs error',
    fix: 'Check key, voice, model, and credits in the ElevenLabs section.',
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

function countWords(text) {
  const matches = String(text || '').match(/[A-Za-z0-9ČĆŽŠĐčćžšđÀ-ÖØ-öø-ÿĀ-ž]+/g);
  return matches ? matches.length : 0;
}

function elevenlabsProgressState(elapsedSec, estimatedDurationSec) {
  const totalExpected = Math.max(12, Number(estimatedDurationSec) || 20);
  const phaseDurationsSec = [
    2,
    Math.max(3, Math.round(totalExpected * 0.18)),
    Math.max(5, Math.round(totalExpected * 0.64)),
    Math.max(2, totalExpected - 2 - Math.max(3, Math.round(totalExpected * 0.18)) - Math.max(5, Math.round(totalExpected * 0.64))),
  ];

  const cappedElapsed = Math.min(elapsedSec, totalExpected);
  let remaining = cappedElapsed;
  let phaseIndex = 0;

  for (let idx = 0; idx < phaseDurationsSec.length; idx += 1) {
    if (remaining <= phaseDurationsSec[idx]) {
      phaseIndex = idx;
      break;
    }
    remaining -= phaseDurationsSec[idx];
    phaseIndex = idx;
  }

  const progressPct = Math.min(96, Math.max(5, Math.round((cappedElapsed / totalExpected) * 96)));
  return { phaseIndex, progressPct };
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function replaceWholeWord(text, sourceWord, targetWord) {
  const source = String(sourceWord || '').trim();
  const target = String(targetWord || '').trim();
  const input = String(text || '');
  if (!source || !target || source === target) {
    return { text: input, replacements: 0 };
  }

  const pattern = new RegExp(`(^|[^\\p{L}\\p{N}_])(${escapeRegExp(source)})(?=$|[^\\p{L}\\p{N}_])`, 'gu');
  let replacements = 0;
  const output = input.replace(pattern, (match, prefix, word) => {
    if (word !== source) {
      return match;
    }
    replacements += 1;
    return `${prefix}${target}`;
  });
  return { text: output, replacements };
}

export default function App() {
  const [username, setUsername] = useState(() => getStoredCredential(CREDENTIAL_STORAGE.username, 'admin'));
  const [password, setPassword] = useState(() => getStoredCredential(CREDENTIAL_STORAGE.password, ''));
  const [openAiApiKeyInput, setOpenAiApiKeyInput] = useState('');
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
  const [statusText, setStatusText] = useState(
    'Ready. Step 1: app login. Step 2: upload file. Step 3: paste your OpenAI key. Step 4: run.',
  );

  const [result, setResult] = useState(initialResult);
  const [error, setError] = useState('');
  const [translatedSegments, setTranslatedSegments] = useState([]);
  const [translationArtifactError, setTranslationArtifactError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [jumpSegmentInput, setJumpSegmentInput] = useState('');
  const [pageSize, setPageSize] = useState(50);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasUnsavedEdits, setHasUnsavedEdits] = useState(false);
  const [saveStateMessage, setSaveStateMessage] = useState('');
  const [savingEdits, setSavingEdits] = useState(false);
  const [localReadbackPath, setLocalReadbackPath] = useState('');
  const [localReadbackStatus, setLocalReadbackStatus] = useState('');
  const [creatingLocalReadback, setCreatingLocalReadback] = useState(false);
  const [confirmLocalReadbackReady, setConfirmLocalReadbackReady] = useState(false);
  const [readbackPlaybackRate, setReadbackPlaybackRate] = useState(DEFAULT_READER_PLAYBACK_RATE);
  const [elevenlabsPlaybackRate, setElevenlabsPlaybackRate] = useState(DEFAULT_ELEVENLABS_PLAYBACK_RATE);
  const [elevenlabsReadbackPath, setElevenlabsReadbackPath] = useState('');
  const [elevenlabsReadbackStatus, setElevenlabsReadbackStatus] = useState('');
  const [creatingElevenlabsReadback, setCreatingElevenlabsReadback] = useState(false);
  const [confirmElevenlabsReadbackReady, setConfirmElevenlabsReadbackReady] = useState(false);
  const [elevenlabsElapsedSec, setElevenlabsElapsedSec] = useState(0);
  const [elevenlabsProgressPct, setElevenlabsProgressPct] = useState(0);
  const [elevenlabsPhaseIndex, setElevenlabsPhaseIndex] = useState(0);
  const [elevenlabsStatusText, setElevenlabsStatusText] = useState('Idle');
  const [elevenLabsApiKeyInput, setElevenLabsApiKeyInput] = useState('');
  const [elevenLabsVoiceIdInput, setElevenLabsVoiceIdInput] = useState('');
  const [elevenLabsModelIdInput, setElevenLabsModelIdInput] = useState('eleven_multilingual_v2');
  const [elevenLabsVoiceOptions, setElevenLabsVoiceOptions] = useState([]);
  const [elevenLabsSelectedVoiceOption, setElevenLabsSelectedVoiceOption] = useState('');
  const [loadingElevenLabsVoices, setLoadingElevenLabsVoices] = useState(false);
  const [elevenLabsVoiceLoadError, setElevenLabsVoiceLoadError] = useState('');
  const [elevenlabsError, setElevenlabsError] = useState('');
  const [wordEdit, setWordEdit] = useState({
    open: false,
    segmentIndex: null,
    field: 'translated_text',
    selectedWord: '',
    replacement: '',
    scope: 'segment',
  });

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
  const localReadbackMediaUrl = useMemo(() => {
    if (!localReadbackPath) return '';
    return `/media/${encodeURI(localReadbackPath)}`;
  }, [localReadbackPath]);
  const elevenlabsReadbackMediaUrl = useMemo(() => {
    if (!elevenlabsReadbackPath) return '';
    return `/media/${encodeURI(elevenlabsReadbackPath)}`;
  }, [elevenlabsReadbackPath]);

  const currentPhases = OPERATION_CONFIG[operation]?.phases || OPERATION_CONFIG.idle.phases;
  const errGuide = error ? errorHelp(error) : null;
  const elevenlabsErrGuide = elevenlabsError ? elevenlabsErrorHelp(elevenlabsError) : null;
  const preRunEstimate = useMemo(() => estimatePreRunCost(selectedDurationSec), [selectedDurationSec]);
  const backendEstimate = result?.cost_estimate || null;
  const filteredSegments = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return translatedSegments;
    return translatedSegments.filter((segment) => {
      const idxText = String(segment.segment_index ?? '');
      const original = String(segment.original_text ?? '').toLowerCase();
      const translated = String(segment.translated_text ?? '').toLowerCase();
      return idxText.includes(query) || original.includes(query) || translated.includes(query);
    });
  }, [translatedSegments, searchQuery]);
  const totalPages = Math.max(1, Math.ceil(filteredSegments.length / pageSize));
  const pagedSegments = useMemo(() => {
    const safePage = Math.min(currentPage, totalPages);
    const start = (safePage - 1) * pageSize;
    return filteredSegments.slice(start, start + pageSize);
  }, [filteredSegments, currentPage, pageSize, totalPages]);
  const warningSegmentsCount = useMemo(
    () =>
      translatedSegments.filter(
        (segment) =>
          Array.isArray(segment.validation_warnings) &&
          segment.validation_warnings.length > 0,
      ).length,
    [translatedSegments],
  );
  const selectedElevenlabsModel = useMemo(
    () =>
      ELEVENLABS_MODEL_OPTIONS.find((item) => item.id === elevenLabsModelIdInput) ||
      ELEVENLABS_MODEL_OPTIONS[ELEVENLABS_MODEL_OPTIONS.length - 1],
    [elevenLabsModelIdInput],
  );
  const elevenlabsEstimate = useMemo(() => {
    const charCount = translatedSegments.reduce(
      (sum, segment) => sum + String(segment.translated_text || '').length,
      0,
    );
    const wordCount = translatedSegments.reduce(
      (sum, segment) => sum + countWords(segment.translated_text),
      0,
    );
    const estimatedMinutes = wordCount > 0 ? wordCount / ELEVENLABS_WORDS_PER_MINUTE : 0;
    const costPerMinute = Number(selectedElevenlabsModel?.costPerMinuteUsd || 0);
    const estimatedCostUsd = estimatedMinutes * costPerMinute;
    const estimatedProcessingSec = Math.max(
      14,
      Math.min(240, Math.round(8 + estimatedMinutes * 8)),
    );
    return {
      charCount,
      estimatedCredits: charCount,
      wordCount,
      estimatedMinutes,
      estimatedCostUsd,
      estimatedProcessingSec,
      costPerMinute,
    };
  }, [translatedSegments, selectedElevenlabsModel]);
  const localReadbackAudioRef = useRef(null);
  const elevenlabsReadbackAudioRef = useRef(null);

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
    if (!creatingElevenlabsReadback) return undefined;

    const timer = setInterval(() => {
      setElevenlabsElapsedSec((prev) => {
        const next = prev + 1;
        const state = elevenlabsProgressState(next, elevenlabsEstimate.estimatedProcessingSec);
        setElevenlabsPhaseIndex(state.phaseIndex);
        setElevenlabsProgressPct(state.progressPct);
        setElevenlabsStatusText('Generating...');
        return next;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [creatingElevenlabsReadback, elevenlabsEstimate.estimatedProcessingSec]);

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
        setHasUnsavedEdits(false);
        setSaveStateMessage('');
        setLocalReadbackPath('');
        setLocalReadbackStatus('');
        setConfirmLocalReadbackReady(false);
        setElevenlabsReadbackPath('');
        setElevenlabsReadbackStatus('');
        setConfirmElevenlabsReadbackReady(false);
        setElevenlabsElapsedSec(0);
        setElevenlabsProgressPct(0);
        setElevenlabsPhaseIndex(0);
        setElevenlabsStatusText('Idle');
        setElevenlabsPlaybackRate(DEFAULT_ELEVENLABS_PLAYBACK_RATE);
        setElevenLabsVoiceOptions([]);
        setElevenLabsSelectedVoiceOption('');
        setLoadingElevenLabsVoices(false);
        setElevenLabsVoiceLoadError('');
        setElevenlabsError('');
        setWordEdit((prev) => ({ ...prev, open: false }));
        setTranslationArtifactError('');
      } catch (artifactError) {
        setTranslatedSegments([]);
        setHasUnsavedEdits(false);
        setSaveStateMessage('');
        setLocalReadbackPath('');
        setLocalReadbackStatus('');
        setConfirmLocalReadbackReady(false);
        setElevenlabsReadbackPath('');
        setElevenlabsReadbackStatus('');
        setConfirmElevenlabsReadbackReady(false);
        setElevenlabsElapsedSec(0);
        setElevenlabsProgressPct(0);
        setElevenlabsPhaseIndex(0);
        setElevenlabsStatusText('Idle');
        setElevenlabsPlaybackRate(DEFAULT_ELEVENLABS_PLAYBACK_RATE);
        setElevenLabsVoiceOptions([]);
        setElevenLabsSelectedVoiceOption('');
        setLoadingElevenLabsVoices(false);
        setElevenLabsVoiceLoadError('');
        setElevenlabsError('');
        setTranslationArtifactError(artifactError.message);
      }
    }

    loadTranslatedArtifact();
  }, [translatedMediaUrl, authHeader]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, pageSize, translatedSegments.length]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      if (username.trim()) {
        window.localStorage.setItem(CREDENTIAL_STORAGE.username, username);
      } else {
        window.localStorage.removeItem(CREDENTIAL_STORAGE.username);
      }
    } catch {
      // Ignore storage errors in restricted browser contexts.
    }
  }, [username]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      if (password) {
        window.localStorage.setItem(CREDENTIAL_STORAGE.password, password);
      } else {
        window.localStorage.removeItem(CREDENTIAL_STORAGE.password);
      }
    } catch {
      // Ignore storage errors in restricted browser contexts.
    }
  }, [password]);

  useEffect(() => {
    if (!localReadbackAudioRef.current) return;
    localReadbackAudioRef.current.playbackRate = readbackPlaybackRate;
  }, [localReadbackMediaUrl, readbackPlaybackRate]);

  useEffect(() => {
    if (!elevenlabsReadbackAudioRef.current) return;
    elevenlabsReadbackAudioRef.current.playbackRate = elevenlabsPlaybackRate;
  }, [elevenlabsReadbackMediaUrl, elevenlabsPlaybackRate]);

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

  function clearSavedCredentials() {
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.removeItem(CREDENTIAL_STORAGE.username);
        window.localStorage.removeItem(CREDENTIAL_STORAGE.password);
      } catch {
        // Ignore storage errors in restricted browser contexts.
      }
    }
    setUsername('admin');
    setPassword('');
    setStatusText('Saved login cleared. Enter credentials again.');
  }

  function jumpToSegment() {
    const target = Number(jumpSegmentInput);
    if (!Number.isFinite(target)) return;
    const idx = filteredSegments.findIndex((segment) => Number(segment.segment_index) === target);
    if (idx < 0) {
      setError(`Segment #${jumpSegmentInput} not found in current filter.`);
      return;
    }
    const nextPage = Math.floor(idx / pageSize) + 1;
    setCurrentPage(nextPage);
    setError('');
  }

  function downloadTranslatedJson() {
    if (!translatedSegments.length) return;
    const blob = new Blob([JSON.stringify(translatedSegments, null, 2)], {
      type: 'application/json;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${bookTitle || 'translation'}_translated.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function downloadSerbianText() {
    if (!translatedSegments.length) return;
    const serbianOnly = translatedSegments
      .map(
        (segment) =>
          `#${segment.segment_index} [${formatSeconds(segment.start)} - ${formatSeconds(segment.end)}]\n` +
          `${segment.original_text || ''}`,
      )
      .join('\n\n');

    const blob = new Blob([serbianOnly], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${bookTitle || 'translation'}_sr.txt`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function downloadEnglishText() {
    if (!translatedSegments.length) return;
    const englishOnly = translatedSegments
      .map(
        (segment) =>
          `#${segment.segment_index} [${formatSeconds(segment.start)} - ${formatSeconds(segment.end)}]\n` +
          `${segment.translated_text || ''}`,
      )
      .join('\n\n');

    const blob = new Blob([englishOnly], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${bookTitle || 'translation'}_en.txt`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function downloadElevenlabsAudio() {
    if (!elevenlabsReadbackMediaUrl) return;
    const link = document.createElement('a');
    link.href = elevenlabsReadbackMediaUrl;
    link.download = `${bookTitle || 'translation'}_elevenlabs_tts.mp3`;
    link.click();
  }

  function openWordEditor(segmentIndex, field, clickedWord) {
    setWordEdit({
      open: true,
      segmentIndex,
      field,
      selectedWord: clickedWord,
      replacement: clickedWord,
      scope: 'segment',
    });
    setSaveStateMessage('');
    setError('');
  }

  function closeWordEditor() {
    setWordEdit((prev) => ({ ...prev, open: false }));
  }

  function applyWordEdit() {
    if (!wordEdit.open) return;

    const sourceWord = String(wordEdit.selectedWord || '').trim();
    const replacement = String(wordEdit.replacement || '').trim();
    if (!sourceWord) {
      setError('No source word selected.');
      return;
    }
    if (!replacement) {
      setError('Replacement word cannot be empty.');
      return;
    }

    let totalReplacements = 0;
    const updatedSegments = translatedSegments.map((segment) => {
      const isTargetSegment = Number(segment.segment_index) === Number(wordEdit.segmentIndex);
      const shouldEdit = wordEdit.scope === 'all' || isTargetSegment;
      if (!shouldEdit) return segment;

      const currentText = String(segment[wordEdit.field] || '');
      const replacementResult = replaceWholeWord(currentText, sourceWord, replacement);
      totalReplacements += replacementResult.replacements;
      if (replacementResult.replacements === 0) return segment;
      return { ...segment, [wordEdit.field]: replacementResult.text };
    });

    if (totalReplacements === 0) {
      setError(`No exact matches found for "${sourceWord}" in the selected scope.`);
      return;
    }

    setTranslatedSegments(updatedSegments);
    setHasUnsavedEdits(true);
    setSaveStateMessage(
      `Applied ${totalReplacements} replacement${totalReplacements === 1 ? '' : 's'} for "${sourceWord}".`,
    );
    setError('');
    closeWordEditor();
  }

  async function saveEditedSegments() {
    if (!authHeader) {
      setError('Enter API credentials first.');
      return;
    }
    if (!translatedPath) {
      setError('No translated artifact path available.');
      return;
    }
    if (!translatedSegments.length) {
      setError('No translated segments loaded.');
      return;
    }

    setSavingEdits(true);
    setError('');

    try {
      const response = await fetch('/api/save-translated', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeader ? { Authorization: authHeader } : {}),
        },
        body: JSON.stringify({
          translated_path: translatedPath,
          segments: translatedSegments,
        }),
      });
      const data = await parseJsonOrError(response);
      setHasUnsavedEdits(false);
      setSaveStateMessage(`Edits saved (${data.segments_saved} segments).`);
      setResult((prev) => {
        if (!prev || typeof prev !== 'object') return prev;
        return {
          ...prev,
          translated_path: data.translated_path || translatedPath,
          edited_segments_saved: data.segments_saved,
          translated_saved_at: data.saved_at,
        };
      });
    } catch (saveError) {
      setError(saveError.message);
      setSaveStateMessage('');
    } finally {
      setSavingEdits(false);
    }
  }

  async function createLocalReadbackAudio() {
    if (!authHeader) {
      setError('Enter API credentials first.');
      return;
    }
    if (!translatedPath) {
      setError('No translated artifact path available.');
      return;
    }
    if (!confirmLocalReadbackReady) {
      setError('Please confirm translation quality before generating voice readback.');
      return;
    }

    setCreatingLocalReadback(true);
    setLocalReadbackStatus('Generating local reader audio...');
    setError('');
    const normalizedSpeechRate = Math.max(80, Math.round(DEFAULT_TTS_BASE_RATE * readbackPlaybackRate));

    try {
      const response = await fetch('/api/read', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeader ? { Authorization: authHeader } : {}),
        },
        body: JSON.stringify({
          translated_path: translatedPath,
          book_title: bookTitle.trim() || undefined,
          speech_rate: normalizedSpeechRate,
          provider: 'local',
        }),
      });
      const data = await parseJsonOrError(response);
      setLocalReadbackPath(data.readback_path || '');
      setLocalReadbackStatus('Local reader audio is ready.');
    } catch (readerError) {
      setLocalReadbackPath('');
      setLocalReadbackStatus('');
      setError(readerError.message);
    } finally {
      setCreatingLocalReadback(false);
    }
  }

  async function createElevenlabsReadbackAudio() {
    if (!authHeader) {
      setElevenlabsError('Enter API credentials first.');
      return;
    }
    if (!translatedPath) {
      setElevenlabsError('No translated artifact path available.');
      return;
    }
    if (!confirmElevenlabsReadbackReady) {
      setElevenlabsError('Please confirm translation quality before generating ElevenLabs TTS.');
      return;
    }
    if (!elevenLabsApiKeyInput.trim()) {
      setElevenlabsError('Enter ElevenLabs API key for this test run.');
      return;
    }
    if (!elevenLabsVoiceIdInput.trim()) {
      setElevenlabsError('Enter Voice ID manually or load free/premade voices and select one.');
      return;
    }

    setCreatingElevenlabsReadback(true);
    setElevenlabsReadbackStatus('Generating ElevenLabs TTS audio...');
    setElevenlabsStatusText('Starting ElevenLabs request...');
    setElevenlabsElapsedSec(0);
    setElevenlabsProgressPct(4);
    setElevenlabsPhaseIndex(0);
    setElevenlabsError('');
    setError('');

    try {
      const response = await fetch('/api/read', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeader ? { Authorization: authHeader } : {}),
        },
        body: JSON.stringify({
          translated_path: translatedPath,
          book_title: bookTitle.trim() || undefined,
          provider: 'elevenlabs',
          elevenlabs_api_key: elevenLabsApiKeyInput.trim(),
          elevenlabs_voice_id: elevenLabsVoiceIdInput.trim(),
          elevenlabs_model_id: elevenLabsModelIdInput.trim(),
        }),
      });
      const data = await parseJsonOrError(response);
      setElevenlabsReadbackPath(data.readback_path || '');
      setElevenlabsReadbackStatus('ElevenLabs reader audio is ready.');
      setElevenlabsProgressPct(100);
      setElevenlabsStatusText('Completed');
    } catch (readerError) {
      setElevenlabsReadbackPath('');
      setElevenlabsReadbackStatus('');
      setElevenlabsStatusText('Failed');
      setElevenlabsError(readerError.message);
    } finally {
      setCreatingElevenlabsReadback(false);
    }
  }

  async function loadElevenLabsVoices() {
    if (!authHeader) {
      setElevenlabsError('Enter API credentials first.');
      return;
    }
    if (!elevenLabsApiKeyInput.trim()) {
      setElevenlabsError('Enter ElevenLabs API key first.');
      return;
    }

    setLoadingElevenLabsVoices(true);
    setElevenLabsVoiceLoadError('');
    setElevenlabsError('');
    try {
      const response = await fetch('/api/elevenlabs/voices', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeader ? { Authorization: authHeader } : {}),
        },
        body: JSON.stringify({
          elevenlabs_api_key: elevenLabsApiKeyInput.trim(),
        }),
      });
      const data = await parseJsonOrError(response);
      const freeVoices = Array.isArray(data.free_voices) ? data.free_voices : [];
      const fallbackVoices = Array.isArray(data.voices) ? data.voices : [];
      const usableVoices = freeVoices.length ? freeVoices : fallbackVoices;
      setElevenLabsVoiceOptions(usableVoices);
      if (usableVoices.length > 0) {
        const firstVoiceId = String(usableVoices[0].voice_id || '');
        setElevenLabsSelectedVoiceOption(firstVoiceId);
        setElevenLabsVoiceIdInput(firstVoiceId);
      } else {
        setElevenLabsSelectedVoiceOption('');
      }
      setElevenLabsVoiceLoadError('');
    } catch (voiceError) {
      setElevenLabsVoiceOptions([]);
      setElevenLabsSelectedVoiceOption('');
      setElevenLabsVoiceLoadError(voiceError.message);
      setElevenlabsError(voiceError.message);
    } finally {
      setLoadingElevenLabsVoices(false);
    }
  }

  function renderEditableText(segment, field) {
    const rawText = String(segment[field] || '');
    if (!rawText) return '-';
    const parts = rawText.split(WORD_SPLIT_RE);
    return (
      <div className="editable-text" title="Click a word to edit">
        {parts.map((part, idx) => {
          if (!part) return null;
          if (WORD_TOKEN_RE.test(part)) {
            return (
              <button
                key={`${segment.segment_index}-${field}-${idx}`}
                type="button"
                className="word-token"
                onClick={() => openWordEditor(segment.segment_index, field, part)}
              >
                {part}
              </button>
            );
          }
          return <span key={`${segment.segment_index}-${field}-${idx}`}>{part}</span>;
        })}
      </div>
    );
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
    if (!openAiApiKeyInput.trim()) {
      setError('Enter your OpenAI API key for translation.');
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
    setHasUnsavedEdits(false);
    setSaveStateMessage('');
    setLocalReadbackPath('');
    setLocalReadbackStatus('');
    setConfirmLocalReadbackReady(false);
    setElevenlabsReadbackPath('');
    setElevenlabsReadbackStatus('');
    setConfirmElevenlabsReadbackReady(false);
    setElevenlabsElapsedSec(0);
    setElevenlabsProgressPct(0);
    setElevenlabsPhaseIndex(0);
    setElevenlabsStatusText('Idle');
    setElevenlabsPlaybackRate(DEFAULT_ELEVENLABS_PLAYBACK_RATE);
    setElevenLabsVoiceOptions([]);
    setElevenLabsSelectedVoiceOption('');
    setLoadingElevenLabsVoices(false);
    setElevenLabsVoiceLoadError('');
    setElevenlabsError('');
    setWordEdit((prev) => ({ ...prev, open: false }));

    startOperation(
      mode,
      mode === 'preview' ? 'Running 5-minute translation preview...' : 'Running full translation...',
    );

    const endpoint = mode === 'preview' ? '/api/preview' : '/api/full';
    const payload = {
      source_path: sourcePath.trim(),
      book_title: bookTitle.trim() || undefined,
      skip_transcription: skipTranscription,
      openai_api_key: openAiApiKeyInput.trim(),
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
          <p className="status">Saved on this browser so you only enter them once.</p>
          <label>
            Username
            <input type="text" value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          <button className="tiny-button" type="button" onClick={clearSavedCredentials}>
            Clear Saved Login
          </button>
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
          <label>
            OpenAI API Key (used for Whisper + translation)
            <input
              type="password"
              value={openAiApiKeyInput}
              onChange={(event) => setOpenAiApiKeyInput(event.target.value)}
              placeholder="sk-..."
            />
          </label>

          <div className="button-row">
            <button className="action-button" disabled={loading || !sourcePath || !authHeader || !openAiApiKeyInput.trim()} onClick={() => runPipeline('preview')}>
              Run 5-Minute Translation Preview
            </button>
            <button className="action-button secondary" disabled={loading || !sourcePath || !authHeader || !openAiApiKeyInput.trim()} onClick={() => runPipeline('full')}>
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
        </section>

        <section className="panel wide">
          <h2>4) Translated Segments</h2>
          {translatedSegments.length === 0 ? (
            <p className="status">No translated segments loaded yet.</p>
          ) : (
            <>
              <div className="segment-summary">
                <span>Total: <strong>{translatedSegments.length}</strong></span>
                <span>Warnings: <strong>{warningSegmentsCount}</strong></span>
                <span>Filtered: <strong>{filteredSegments.length}</strong></span>
                <span>Page: <strong>{currentPage}/{totalPages}</strong></span>
              </div>

              <div className="edit-toolbar">
                <span>Click any Serbian or English word in the table to edit it.</span>
                <span className={hasUnsavedEdits ? 'dirty' : 'clean'}>
                  {hasUnsavedEdits ? 'Unsaved changes' : 'All changes saved'}
                </span>
                <button
                  className="tiny-button save-button"
                  type="button"
                  onClick={saveEditedSegments}
                  disabled={savingEdits || !translatedSegments.length || !hasUnsavedEdits}
                >
                  {savingEdits ? 'Saving...' : 'Save Edits to JSON'}
                </button>
              </div>

              {saveStateMessage ? <p className="save-message">{saveStateMessage}</p> : null}

              {wordEdit.open && (
                <div className="word-edit-card">
                  <h4>Word Edit</h4>
                  <p>
                    Selected word: <strong>{wordEdit.selectedWord}</strong>
                  </p>
                  <p>
                    Segment: <strong>#{wordEdit.segmentIndex}</strong> | Field:{' '}
                    <strong>{wordEdit.field === 'original_text' ? 'Original (SR)' : 'Translated (EN)'}</strong>
                  </p>
                  <label>
                    Replace with
                    <input
                      type="text"
                      value={wordEdit.replacement}
                      onChange={(event) =>
                        setWordEdit((prev) => ({ ...prev, replacement: event.target.value }))
                      }
                    />
                  </label>
                  <label>
                    Apply scope
                    <select
                      value={wordEdit.scope}
                      onChange={(event) =>
                        setWordEdit((prev) => ({ ...prev, scope: event.target.value }))
                      }
                    >
                      <option value="segment">Current segment only</option>
                      <option value="all">All loaded segments</option>
                    </select>
                  </label>
                  <div className="button-row">
                    <button className="tiny-button" type="button" onClick={applyWordEdit}>
                      Apply Replacement
                    </button>
                    <button className="tiny-button" type="button" onClick={closeWordEditor}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              <div className="segment-tools">
                <input
                  type="text"
                  value={searchQuery}
                  placeholder="Search original or translated text..."
                  onChange={(event) => setSearchQuery(event.target.value)}
                />
                <input
                  type="number"
                  min="0"
                  value={jumpSegmentInput}
                  placeholder="Jump to segment #"
                  onChange={(event) => setJumpSegmentInput(event.target.value)}
                />
                <button className="tiny-button" type="button" onClick={jumpToSegment}>
                  Jump
                </button>
                <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
                  <option value={25}>25 / page</option>
                  <option value={50}>50 / page</option>
                  <option value={100}>100 / page</option>
                </select>
                <button className="tiny-button" type="button" onClick={downloadTranslatedJson}>
                  Download JSON
                </button>
                <button className="tiny-button" type="button" onClick={downloadSerbianText}>
                  Download SR TXT
                </button>
                <button className="tiny-button" type="button" onClick={downloadEnglishText}>
                  Download EN TXT
                </button>
              </div>

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
                    {pagedSegments.map((segment) => (
                      <tr key={segment.segment_index}>
                        <td>{segment.segment_index}</td>
                        <td>{formatSeconds(segment.start)} - {formatSeconds(segment.end)}</td>
                        <td>{renderEditableText(segment, 'original_text')}</td>
                        <td>
                          <div>{renderEditableText(segment, 'translated_text')}</div>
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

              <div className="pager">
                <button
                  className="tiny-button"
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                >
                  Previous
                </button>
                <span>
                  Page {currentPage} of {totalPages}
                </span>
                <button
                  className="tiny-button"
                  type="button"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                >
                  Next
                </button>
              </div>

              <div className="reader-review-card">
                <label className="checkbox-row reader-confirm">
                  <input
                    type="checkbox"
                    checked={confirmLocalReadbackReady}
                    onChange={(event) => setConfirmLocalReadbackReady(event.target.checked)}
                  />
                  Confirm translation quality before generating local readback.
                </label>

                <div className="reader-tools">
                  <label>
                    Reader speed
                    <select
                      value={String(readbackPlaybackRate)}
                      onChange={(event) => setReadbackPlaybackRate(Number(event.target.value))}
                    >
                      <option value="0.6">0.60x</option>
                      <option value="0.75">0.75x</option>
                      <option value="0.9">0.90x</option>
                      <option value="1">1.00x</option>
                      <option value="1.5">1.50x</option>
                      <option value="2">2.00x</option>
                    </select>
                  </label>
                  <button
                    className="tiny-button"
                    type="button"
                    onClick={createLocalReadbackAudio}
                    disabled={creatingLocalReadback || !translatedPath || !confirmLocalReadbackReady}
                  >
                    {creatingLocalReadback ? 'Generating Local Reader...' : 'Read Whole Translation (Free Local)'}
                  </button>
                  {localReadbackStatus ? <span className="reader-status">{localReadbackStatus}</span> : null}
                </div>

                {localReadbackMediaUrl ? (
                  <div className="reader-player">
                    <audio ref={localReadbackAudioRef} controls src={localReadbackMediaUrl} preload="metadata" />
                  </div>
                ) : null}
              </div>
            </>
          )}

          <h3>Raw Translated JSON</h3>
          <pre>{translatedSegments.length ? JSON.stringify(translatedSegments, null, 2) : 'No translated artifact loaded yet.'}</pre>

          <h3>Last API Response</h3>
          <pre>{result ? JSON.stringify(result, null, 2) : 'No response yet.'}</pre>
        </section>

        <section className="panel wide">
          <h2>5) ElevenLabs TTS Trial</h2>
          {translatedSegments.length === 0 ? (
            <p className="status">Run translation first to enable ElevenLabs TTS estimation and generation.</p>
          ) : (
            <>
              <p className="status">
                Select model and review estimated cost before generating. Cost rates below are estimates per minute and may vary by plan.
              </p>

              {elevenlabsError && elevenlabsErrGuide ? (
                <div className="error-card">
                  <strong>{elevenlabsErrGuide.title}</strong>
                  <p>{elevenlabsError}</p>
                  <p className="error-fix">Fix: {elevenlabsErrGuide.fix}</p>
                </div>
              ) : null}

              <div className="elevenlabs-model-list">
                {ELEVENLABS_MODEL_OPTIONS.map((model) => (
                  <button
                    key={model.id}
                    type="button"
                    className={`elevenlabs-model-card ${model.id === elevenLabsModelIdInput ? 'active' : ''}`}
                    onClick={() => {
                      setElevenLabsModelIdInput(model.id);
                      setElevenlabsError('');
                    }}
                  >
                    <div>
                      <strong>{model.label}</strong>
                    </div>
                    <div>{formatUsd(model.costPerMinuteUsd)} / min</div>
                    <div className="model-note">{model.note}</div>
                  </button>
                ))}
              </div>

              <div className="reader-provider-grid">
                <label>
                  ElevenLabs API Key
                  <input
                    type="password"
                    value={elevenLabsApiKeyInput}
                    onChange={(event) => {
                      setElevenLabsApiKeyInput(event.target.value);
                      setElevenlabsError('');
                    }}
                    placeholder="YOUR_ELEVENLABS_API_KEY"
                  />
                </label>
                <label>
                  Voice ID (paste manually)
                  <input
                    type="text"
                    value={elevenLabsVoiceIdInput}
                    onChange={(event) => {
                      setElevenLabsVoiceIdInput(event.target.value);
                      setElevenLabsSelectedVoiceOption('');
                      setElevenlabsError('');
                    }}
                    placeholder="JBFqnCBsd6RMkjVDRZzb"
                  />
                </label>
              </div>

              <div className="reader-tools">
                <button
                  className="tiny-button"
                  type="button"
                  onClick={loadElevenLabsVoices}
                  disabled={loadingElevenLabsVoices || !elevenLabsApiKeyInput.trim()}
                >
                  {loadingElevenLabsVoices ? 'Loading Voices...' : 'Load Free/Premade Voices'}
                </button>
                {elevenLabsVoiceOptions.length > 0 ? (
                  <label>
                    Choose voice from list
                    <select
                      value={elevenLabsSelectedVoiceOption}
                      onChange={(event) => {
                        const nextVoiceId = event.target.value;
                        setElevenLabsSelectedVoiceOption(nextVoiceId);
                        setElevenLabsVoiceIdInput(nextVoiceId);
                        setElevenlabsError('');
                      }}
                    >
                      {elevenLabsVoiceOptions.map((voice) => (
                        <option key={voice.voice_id} value={voice.voice_id}>
                          {voice.name} ({voice.category})
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <span className="reader-status">Load voices to choose free/premade options for your plan.</span>
                )}
              </div>

              {elevenLabsVoiceLoadError ? (
                <div className="error-card">
                  <strong>Voice list load failed</strong>
                  <p>{elevenLabsVoiceLoadError}</p>
                </div>
              ) : null}

              <div className="cost-grid">
                <div className="cost-card">
                  <h3>Selected Model</h3>
                  <p>{selectedElevenlabsModel.label}</p>
                  <p>Rate: {formatUsd(elevenlabsEstimate.costPerMinute)} / min</p>
                  <p>Characters: {elevenlabsEstimate.charCount.toLocaleString()}</p>
                  <p>Words detected: {elevenlabsEstimate.wordCount.toLocaleString()}</p>
                </div>
                <div className="cost-card">
                  <h3>Before Generate</h3>
                  <p>Estimated speech length: {elevenlabsEstimate.estimatedMinutes.toFixed(2)} min</p>
                  <p>Estimated credits: <strong>{Math.max(0, Math.round(elevenlabsEstimate.estimatedCredits)).toLocaleString()}</strong></p>
                  <p>Estimated cost: <strong>{formatUsd(elevenlabsEstimate.estimatedCostUsd)}</strong></p>
                  <p>Estimated processing: ~{Math.max(1, Math.round(elevenlabsEstimate.estimatedProcessingSec / 60))} min</p>
                </div>
              </div>

              <label className="checkbox-row reader-confirm">
                <input
                  type="checkbox"
                  checked={confirmElevenlabsReadbackReady}
                  onChange={(event) => setConfirmElevenlabsReadbackReady(event.target.checked)}
                />
                I checked the translation and accept this estimated ElevenLabs cost.
              </label>

              <div className="reader-tools">
                <label>
                  Playback speed
                  <select
                    value={String(elevenlabsPlaybackRate)}
                    onChange={(event) => setElevenlabsPlaybackRate(Number(event.target.value))}
                  >
                    <option value="0.6">0.60x</option>
                    <option value="0.75">0.75x</option>
                    <option value="0.9">0.90x</option>
                    <option value="1">1.00x</option>
                    <option value="1.5">1.50x</option>
                    <option value="2">2.00x</option>
                  </select>
                </label>
                <button
                  className="tiny-button"
                  type="button"
                  onClick={createElevenlabsReadbackAudio}
                  disabled={
                    creatingElevenlabsReadback ||
                    !translatedPath ||
                    !confirmElevenlabsReadbackReady ||
                    !elevenLabsApiKeyInput.trim() ||
                    !elevenLabsVoiceIdInput.trim()
                  }
                >
                  {creatingElevenlabsReadback ? 'Generating ElevenLabs TTS...' : 'Generate ElevenLabs TTS'}
                </button>
                <button
                  className="tiny-button"
                  type="button"
                  onClick={downloadElevenlabsAudio}
                  disabled={!elevenlabsReadbackMediaUrl}
                >
                  Download ElevenLabs Audio
                </button>
                {elevenlabsReadbackStatus ? <span className="reader-status">{elevenlabsReadbackStatus}</span> : null}
              </div>

              <div className="progress-head">
                <span>ElevenLabs TTS Progress</span>
                <span>
                  {creatingElevenlabsReadback
                    ? `ElevenLabs TTS • ${elevenlabsElapsedSec}s`
                    : elevenlabsReadbackPath
                      ? 'Completed'
                      : 'Idle'}
                </span>
              </div>
              <div className={`progress-track ${creatingElevenlabsReadback ? 'active' : ''}`}>
                <div className="progress-fill" style={{ width: `${elevenlabsProgressPct}%` }} />
              </div>
              <div className="progress-meta">{elevenlabsProgressPct}%</div>

              {elevenlabsReadbackMediaUrl ? (
                <div className="reader-player">
                  <audio ref={elevenlabsReadbackAudioRef} controls src={elevenlabsReadbackMediaUrl} preload="metadata" />
                </div>
              ) : null}
            </>
          )}
        </section>
      </main>
    </div>
  );
}
