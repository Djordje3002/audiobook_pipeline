import { useEffect, useMemo, useState } from 'react';

const initialResult = null;

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

export default function App() {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [sourcePath, setSourcePath] = useState('');
  const [bookTitle, setBookTitle] = useState('moja_knjiga');
  const [skipTranscription, setSkipTranscription] = useState(true);
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState('Ready. Upload audio and run preview first.');
  const [result, setResult] = useState(initialResult);
  const [error, setError] = useState('');
  const [previewBlobUrl, setPreviewBlobUrl] = useState('');

  const previewPath = useMemo(() => {
    if (!result || result.mode !== 'preview') return '';
    return result.preview_path || '';
  }, [result]);

  const previewMediaUrl = useMemo(() => {
    if (!previewPath) return '';
    return `/media/${encodeURI(previewPath)}`;
  }, [previewPath]);

  const authHeader = useMemo(() => {
    if (!username || !password) return '';
    return `Basic ${btoa(`${username}:${password}`)}`;
  }, [username, password]);

  useEffect(() => {
    let objectUrl = '';

    async function loadPreviewBlob() {
      if (!previewMediaUrl) {
        setPreviewBlobUrl('');
        return;
      }

      try {
        const response = await fetch(previewMediaUrl, {
          headers: authHeader ? { Authorization: authHeader } : {},
        });
        if (!response.ok) {
          throw new Error(`Preview fetch failed with status ${response.status}`);
        }
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        setPreviewBlobUrl(objectUrl);
      } catch (previewError) {
        setError(previewError.message);
        setPreviewBlobUrl('');
      }
    }

    loadPreviewBlob();
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [previewMediaUrl, authHeader]);

  async function uploadAudioFile() {
    if (!selectedFile) {
      setError('Select an audio file first.');
      return;
    }

    setLoading(true);
    setError('');
    setStatusText(`Uploading ${selectedFile.name}...`);

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
      setStatusText(`Uploaded: ${data.filename}`);
      setResult(data);
    } catch (uploadError) {
      setError(uploadError.message);
      setStatusText('Upload failed.');
    } finally {
      setLoading(false);
    }
  }

  async function runPipeline(mode) {
    if (!sourcePath.trim()) {
      setError('Provide source_path or upload a file first.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);
    setStatusText(mode === 'preview' ? 'Running 5-minute preview...' : 'Running full production...');

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
        setStatusText(mode === 'preview' ? 'Preview completed successfully.' : 'Full production completed successfully.');
      } else {
        setStatusText('Pipeline finished with errors.');
      }
    } catch (pipelineError) {
      setError(pipelineError.message);
      setStatusText('Pipeline request failed.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-shell">
      <header className="hero">
        <p className="eyebrow">Audiobook Pipeline</p>
        <h1>Serbian to English Voice Transformation</h1>
        <p>
          Upload your Serbian audiobook, run a low-cost 5-minute preview, then produce full ACX-ready English
          output with your cloned voice profile.
        </p>
      </header>

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
            onChange={(event) => setSelectedFile(event.target.files?.[0] || null)}
          />
          <button className="action-button" onClick={uploadAudioFile} disabled={loading || !selectedFile}>
            {loading ? 'Working...' : 'Upload File'}
          </button>
        </section>

        <section className="panel">
          <h2>2) Pipeline Settings</h2>
          <label>
            Source Path
            <input
              type="text"
              value={sourcePath}
              placeholder="input_audio/knjiga.mp3"
              onChange={(event) => setSourcePath(event.target.value)}
            />
          </label>

          <label>
            Book Title
            <input type="text" value={bookTitle} onChange={(event) => setBookTitle(event.target.value)} />
          </label>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={skipTranscription}
              onChange={(event) => setSkipTranscription(event.target.checked)}
            />
            Skip transcription on rerun (if transcript already exists)
          </label>

          <div className="button-row">
            <button className="action-button" disabled={loading} onClick={() => runPipeline('preview')}>
              Run 5-Minute Preview
            </button>
            <button className="action-button secondary" disabled={loading} onClick={() => runPipeline('full')}>
              Run Full Production
            </button>
          </div>
        </section>

        <section className="panel wide">
          <h2>3) Status</h2>
          <p className="status">{statusText}</p>
          {error && <p className="error">{error}</p>}

          {previewPath && (
            <div className="preview-box">
              <p>Preview ready: <code>{previewPath}</code></p>
              <audio controls src={previewBlobUrl || previewMediaUrl} preload="none" />
            </div>
          )}

          <h3>Last API Response</h3>
          <pre>{result ? JSON.stringify(result, null, 2) : 'No response yet.'}</pre>
        </section>
      </main>
    </div>
  );
}
