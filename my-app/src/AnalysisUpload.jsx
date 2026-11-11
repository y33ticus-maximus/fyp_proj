import { useEffect, useRef, useState } from 'react';
import VideoSampler from './VideoSampler';
import './MediaAnalysis.css';

const OVERALL_TEXT = {
  violation: '❌ PPE violation detected',
  compliant: '✅ No visible PPE violation found',
  unclear: '⚠️ PPE assessment requires review',
  boots_unverified: '⚠️ Footwear cannot be verified',
  no_workers: '👤 No workers detected',
};

function ppeText(value) {
  if (value === 'yes') return '❌ Violation';
  if (value === 'no') return '✅ No violation';
  return '⚠️ Unclear';
}

function ppeIcon(value) {
  if (value === 'yes') return '❌';
  if (value === 'no') return '✅';
  return '⚠️';
}

function statusText(value) {
  if (value === 'violation') return '❌ Violation';
  if (value === 'compliant') return '✅ Compliant';
  if (value === 'unclear') return '⚠️ Review';
  if (value === 'boots_unverified') return '⚠️ Unverified';
  if (value === 'no_workers') return '👤 No workers';
  return 'Completed';
}

function timecode(seconds) {
  const value = Math.floor(Number(seconds) || 0);
  return [Math.floor(value / 3600), Math.floor((value % 3600) / 60), value % 60]
    .map((part) => String(part).padStart(2, '0'))
    .join(':');
}

/** Browser-only preview for the current file. URLs are revoked on replacement/unmount. */
function useObjectUrl(file) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    if (!file) {
      setUrl('');
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return file ? url : '';
}

/** Upload a single image OR analyse frames from a video using the same FastAPI endpoint. */
export default function AnalysisUpload({ onResult }) {
  const [file, setFile] = useState(null);
  const [videoFile, setVideoFile] = useState(null);
  const [activeMedia, setActiveMedia] = useState('image');
  const [location, setLocation] = useState('Construction site');
  const [camera, setCamera] = useState('UPLOAD');
  const [reviewUnclearBoots, setReviewUnclearBoots] = useState(false);
  const [model, setModel] = useState('qwen3.8:27b');
  const [models, setModels] = useState(['qwen3.8:27b']);
  const [available, setAvailable] = useState([]);
  const [connected, setConnected] = useState(false);
  const [connectionMessage, setConnectionMessage] = useState('Checking backend...');
  const [busy, setBusy] = useState(false);
  const [videoRunning, setVideoRunning] = useState(false);
  const [intervalSeconds, setIntervalSeconds] = useState(60);
  const [error, setError] = useState('');
  const [imageResult, setImageResult] = useState(null);
  const [frameHistory, setFrameHistory] = useState([]);
  const [selectedFrameTime, setSelectedFrameTime] = useState(null);
  const analysisLock = useRef(false);
  const videoStartRef = useRef(null);

  const imageUrl = useObjectUrl(file);
  const videoUrl = useObjectUrl(videoFile);
  const selectedFrame = frameHistory.find((frame) => frame.timestampSeconds === selectedFrameTime)
    || frameHistory[frameHistory.length - 1];
  const frameUrl = useObjectUrl(selectedFrame?.file);
  const currentResult = activeMedia === 'video' ? selectedFrame?.result : imageResult;
  const currentError = activeMedia === 'video' ? selectedFrame?.error : error;
  const currentWorking = activeMedia === 'video'
    ? selectedFrame?.status === 'analysing'
    : busy && !videoRunning;

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/models', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Backend is not running.');
        return response.json();
      })
      .then((data) => {
        const choices = Array.isArray(data.models) && data.models.length
          ? data.models : ['qwen3.8:27b'];
        setModels(choices);
        setModel((previous) => choices.includes(previous) ? previous : choices[0]);
        setAvailable(Array.isArray(data.available) ? data.available : []);
        setConnected(Boolean(data.connected));
        setConnectionMessage(data.connected
          ? (data.available?.length ? `${data.deployment === 'local' ? 'Local' : 'Remote'} Ollama connected` : 'Ollama connected, but allowed models were not found')
          : (data.error || 'Ollama unavailable'));
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setConnected(false);
        setConnectionMessage('Backend unavailable — start FastAPI on port 8000.');
      });
    return () => controller.abort();
  }, []);

  function updateFrame(seconds, change) {
    setFrameHistory((previous) => previous.map((frame) =>
      frame.timestampSeconds === seconds ? { ...frame, ...change } : frame
    ));
  }

  async function analyzeImageFile(imageFile, metadata = {}) {
    if (!imageFile) throw new Error('No image was selected.');
    if (analysisLock.current) throw new Error('Another image is already being analysed.');

    const fromVideo = Boolean(metadata.videoName);
    analysisLock.current = true;
    setBusy(true);
    setError('');
    if (!fromVideo) setImageResult(null);

    try {
      const form = new FormData();
      form.append('file', imageFile);
      form.append('model', model);
      form.append('location', location);
      form.append('review_unclear_boots', String(reviewUnclearBoots));

      let source = camera;
      if (fromVideo && Number.isFinite(metadata.timestampSeconds)) {
        // Keep within the existing backend's 50-character camera/source limit.
        source = `VIDEO ${timecode(metadata.timestampSeconds)} | ${metadata.videoName}`;
      }
      form.append('camera', source.slice(0, 50));
      if (fromVideo) {
        form.append('video_session_id', metadata.sessionId || '');
        form.append('video_name', metadata.videoName);
        form.append('video_timestamp_seconds', String(metadata.timestampSeconds));
      }

      const response = await fetch('/api/analyze', { method: 'POST', body: form });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Analysis failed (HTTP ${response.status}).`);

      if (fromVideo) {
        updateFrame(metadata.timestampSeconds, { status: 'completed', result: data, error: '' });
          // Switch the displayed frame only after analysis finishes.
          setSelectedFrameTime(metadata.timestampSeconds); 
      } else {
        setImageResult(data);
      }
      // FastAPI has already stored the analysis and incident in SQLite.
      await onResult?.(data);
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to analyse the image.';
      if (fromVideo) {
        updateFrame(metadata.timestampSeconds, { status: 'error', error: message });
      } else {
        setError(message);
      }
      throw err;
    } finally {
      analysisLock.current = false;
      setBusy(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (busy || videoRunning || analysisLock.current) return;

    if (activeMedia === 'video') {
      if (videoFile) videoStartRef.current?.();
      return;
    }

    if (!file) return;
    try {
      await analyzeImageFile(file);
    } catch {
      // Existing results panel displays analysis errors.
    }
  }

  function handleMediaSelection(next) {
    if (busy || videoRunning) return;

    setError('');
    setImageResult(null);
    setFrameHistory([]);
    setSelectedFrameTime(null);

    if (!next) {
      setFile(null);
      setVideoFile(null);
      setActiveMedia('image');
      return;
    }

    const video = next.type.startsWith('video/') ||
      /\.(mp4|webm|ogg)$/i.test(next.name);
    const image = next.type.startsWith('image/') ||
      /\.(jpg|jpeg|png|webp)$/i.test(next.name);

    if (video) {
      setVideoFile(next);
      setFile(null);
      setActiveMedia('video');
    } else if (image) {
      setFile(next);
      setVideoFile(null);
      setActiveMedia('image');
    } else {
      setFile(null);
      setVideoFile(null);
      setError('Unsupported file type. Please select an image or video.');
    }
  }

  function handleVideoSelection(nextFile) {
    if (videoRunning) return;
    setVideoFile(nextFile);
    setActiveMedia('video');
    setError('');
    setFrameHistory([]);
    setSelectedFrameTime(null);
  }

  function handleFrameExtracted(frameFile, metadata) {
    setActiveMedia('video');
    setFrameHistory((previous) => [
      ...previous,
      { timestampSeconds: metadata.timestampSeconds, file: frameFile,
        status: 'analysing', result: null, error: '' },
    ]);
  }

  return (
    <section className="panel analysis-panel" aria-label="Ollama media analysis">
      <div className="analysis-heading">
        <div>
          <h2>AI PPE analysis</h2>
          <p className="muted">Analyse a photograph or sample video frames using the configured local or remote Ollama vision-language model. Results appear beside the media.</p>
        </div>
        <span className={`connection-indicator ${connected && available.length ? 'connected' : 'disconnected'}`}>
          {connectionMessage}
        </span>
      </div>

      <form onSubmit={submit} className="analysis-form analysis-compact-form">
        <div className="analysis-settings-row">
          <label className="analysis-field">
            <span>AI model</span>
            <select value={model} disabled={videoRunning || busy}
              onChange={(event) => setModel(event.target.value)}>
              {models.map((name) => (
                <option key={name} value={name}>
                  {name}{connected && !available.includes(name) ? ' (not found)' : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="analysis-field">
            <span>Location</span>
            <input type="text" maxLength="100"
              disabled={videoRunning || busy}
              value={location}
              onChange={(event) => setLocation(event.target.value)} />
          </label>
          <label className="analysis-field">
            <span>Camera / source</span>
            <input type="text" maxLength="50"
              disabled={videoRunning || busy}
              value={camera}
              onChange={(event) => setCamera(event.target.value)} />
          </label>
        </div>

        <div className="analysis-upload-row">
          <div className="analysis-upload-group">
            <span className="analysis-small-label">Media</span>
            <label className="analysis-upload-button"
              htmlFor="ppe-unified-media">
              ? Upload media
            </label>
            <input id="ppe-unified-media" type="file"
              className="analysis-hidden-file"
              accept="image/jpeg,image/png,image/webp,video/mp4,video/webm,video/ogg"
              disabled={videoRunning || busy}
              onChange={(event) =>
                handleMediaSelection(event.target.files?.[0] ?? null)
              } />
          </div>

          <div className="analysis-selected-media">
            <span className="analysis-small-label">Selected file</span>
            <span className="analysis-selected-name">
              {activeMedia === 'video'
                ? (videoFile?.name || 'No file selected')
                : (file?.name || 'No file selected')}
            </span>
          </div>

          {activeMedia === 'video' && videoFile && (
            <label className="analysis-field analysis-interval-field">
              <span>Sample interval</span>
              <select value={intervalSeconds}
                disabled={videoRunning || busy}
                onChange={(event) =>
                  setIntervalSeconds(Number(event.target.value))
                }>
                 <option value={1}>Every 1 second</option>
                <option value={2}>Every 2 seconds</option>
                <option value={3}>Every 3 seconds</option>
                <option value={5}>Every 5 seconds</option>
                <option value={10}>Every 10 seconds</option>
                <option value={15}>Every 15 seconds</option>
                <option value={30}>Every 30 seconds</option>
                <option value={60}>Every 60 seconds</option>
              </select>
            </label>
          )}

          <button type="submit" className="analyse-button"
            disabled={!(activeMedia === 'video' ? videoFile : file)
              || videoRunning || busy}>
            {videoRunning || busy ? 'Analysing?' : 'Analyse media'}
          </button>
        </div>

        <details className="analysis-advanced-settings">
          <summary>? Advanced settings</summary>
          <label className="boot-review-setting">
            <input type="checkbox"
              disabled={videoRunning || busy}
              checked={reviewUnclearBoots}
              onChange={(event) =>
                setReviewUnclearBoots(event.target.checked)
              } />
            <span>
              Notify for unclear boots (manual review).
              Off by default to avoid alerts when feet are out of view.
            </span>
          </label>
        </details>
      </form>

      <VideoSampler
        externalFile={videoFile}
        externalIntervalSeconds={intervalSeconds}
        controlsHidden
        startRef={videoStartRef}
        onAnalyzeFrame={analyzeImageFile}
        onVideoSelected={handleVideoSelection}
        onFrameExtracted={handleFrameExtracted}
        onStart={() => {
          setVideoRunning(true);
          setActiveMedia('video');
          setFrameHistory([]);
          setSelectedFrameTime(null);
          setError('');
        }}
        onFinish={() => setVideoRunning(false)}
        disabled={busy && !videoRunning}
      />


      <div className="ppe-media-results-grid">
        <div className="ppe-media-card">
          <h3>Media preview</h3>
          {activeMedia === 'image' && imageUrl && (
            <>
              <img className="ppe-media-photo" src={imageUrl} alt="Uploaded image being assessed for PPE" />
              <p className="ppe-media-caption">{file?.name}</p>
            </>
          )}
          {activeMedia === 'video' && videoUrl && (
            <>
              <video className="ppe-media-video" src={videoUrl} controls preload="metadata" playsInline />
              <p className="ppe-media-caption">{videoFile?.name} · playback independent of AI analysis</p>
              {selectedFrame && frameUrl && (
                <div className="ppe-current-frame">
                  <h4>Sampled frame · {timecode(selectedFrame.timestampSeconds)}</h4>
                  <img className="ppe-frame-photo" src={frameUrl}
                    alt={`Frame captured at ${timecode(selectedFrame.timestampSeconds)}`} />
                </div>
              )}
            </>
          )}
          {((activeMedia === 'image' && !imageUrl) || (activeMedia === 'video' && !videoUrl)) && (
            <div className="ppe-empty-preview">Select an image or video to preview it here.</div>
          )}
        </div>

        <div className="ppe-results-column">
        <div className="ppe-media-card ppe-ai-output" aria-live="polite">
          <div className="ppe-output-title">
            <h3>AI analysis results</h3>
            {currentResult && <span className={`ppe-overall-chip ppe-overall-${currentResult.overall_status}`}>
              {statusText(currentResult.overall_status)}
            </span>}
          </div>
          {activeMedia === 'video' && selectedFrame && (
            <p className="ppe-media-caption">Video timestamp: {timecode(selectedFrame.timestampSeconds)}</p>
          )}
          {currentWorking && <p className="ppe-status-message" role="status">Analysing with {model}…</p>}
          {currentError && <p className="analysis-error" role="alert">Analysis error: {currentError}. No incident created for this frame.</p>}
          {!currentResult && !currentWorking && !currentError && (
            <p className="ppe-no-result">No results yet. Choose media and start an analysis.</p>
          )}
          {currentResult && (
            <>
              <p className="ppe-overall-heading">{OVERALL_TEXT[currentResult.overall_status] || 'Analysis complete'}</p>
              <div className="ppe-category-list">
                {[
                  ['Helmet', currentResult.helmet_violation],
                  ['Safety vest', currentResult.vest_violation],
                  ['Boots (visual)', currentResult.boots_violation],
                ].map(([name, value]) => (
                  <div className="ppe-category-row" key={name}>
                    <span>{name}</span>
                    <span className={`ppe-item-pill ppe-item-${value}`}>{ppeText(value)}</span>
                  </div>
                ))}
              </div>
              <div className="ppe-result-meta">
                <span><strong>Workers:</strong> {currentResult.worker_count ?? '—'}</span>
                <span><strong>Model:</strong> {currentResult.model || '—'}</span>
                <span><strong>Processing:</strong> {currentResult.processing_seconds ?? '—'}s</span>
              </div>
              {Array.isArray(currentResult.workers) && currentResult.workers.length > 0 && (
                <details className="ppe-workers-breakdown">
                  <summary>Per-worker assessments ({currentResult.workers.length})</summary>
                  <div className="ppe-workers-scroll">
                    <table>
                      <thead><tr><th>Position</th><th>Helmet</th><th>Vest</th><th>Boots</th></tr></thead>
                      <tbody>
                        {currentResult.workers.map((worker, index) => (
                          <tr key={`${index}-${worker.position || 'worker'}`}>
                            <td>{worker.position || `Worker ${index + 1}`}</td>
                            <td>{worker.helmet || 'unclear'}</td>
                            <td>{worker.vest || 'unclear'}</td>
                            <td>{worker.boots || 'unclear'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
              <p className="ppe-incident-note">
                {['violation', 'unclear'].includes(currentResult.overall_status)
                  ? currentResult.incident_action === 'grouped'
                    ? `Grouped with existing incident #${currentResult.incident_id}; no duplicate notification.`
                    : `Incident #${currentResult.incident_id} created. Evidence is available under Details.`
                  : 'No incident was created for this result.'}
              </p>
              <p className="ppe-media-caption">These are model-reported classifications, not verified bounding boxes. Visual appearance alone cannot confirm certified safety footwear.</p>
            </>
          )}
        </div>

      {activeMedia === 'video' && frameHistory.length > 0 && (
        <details className="ppe-video-history" open>
          <summary>Video frame analysis history ({frameHistory.length} frames)</summary>
          <div className="ppe-history-scroll">
            <table>
              <thead>
                <tr><th>Frame</th><th>Helmet</th><th>Vest</th><th>Boots</th><th>Overall</th></tr>
              </thead>
              <tbody>
                {frameHistory.map((frame) => (
                  <tr key={frame.timestampSeconds}
                    className={selectedFrame?.timestampSeconds === frame.timestampSeconds ? 'ppe-history-selected' : ''}>
                    <td>
                      <button type="button" className="ppe-frame-link"
                        onClick={() => setSelectedFrameTime(frame.timestampSeconds)}
                        aria-label={`Inspect frame at ${timecode(frame.timestampSeconds)}`}>
                        {timecode(frame.timestampSeconds)}
                      </button>
                    </td>
                    <td>{frame.result ? ppeText(frame.result.helmet_violation) : '—'}</td>
                    <td>{frame.result ? ppeText(frame.result.vest_violation) : '—'}</td>
                    <td>{frame.result ? ppeText(frame.result.boots_violation) : '—'}</td>
                    <td>{frame.status === 'error' ? 'Error'
                      : frame.status === 'analysing' ? 'Analysing…'
                      : statusText(frame.result?.overall_status)}</td>
                    <td>{frame.result?.processing_seconds != null ? `${frame.result.processing_seconds}s` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="ppe-media-caption">Click a timestamp to view that exact frame and its saved model results without running inference again. These browser previews reset when the page is refreshed.</p>
        </details>
      )}
        </div>
      </div>
    </section>
  );
}
