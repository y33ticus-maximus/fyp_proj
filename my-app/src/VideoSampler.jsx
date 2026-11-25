import { useEffect, useRef, useState } from 'react';
import { buildFrameTimestamps, estimateFrameCount, LARGE_JOB_FRAME_THRESHOLD,
  validSamplingInterval } from './videoSampling';

/**
 * Extracts frames from a locally selected video. The whole video stays in the
 * browser: only individual sampled JPEG frames are sent to FastAPI by the parent.
 */
export default function VideoSampler({
  onAnalyzeFrame,
  onVideoSelected,
  onFrameExtracted,
  onStart,
  onFinish,
  disabled = false,
  externalFile = null,
  externalIntervalSeconds = null,
  externalDurationSeconds = null,
  allowLargeWorkload = true,
  controlsHidden = false,
  startRef = null,
}) {
  const [file, setFile] = useState(null);
  const [intervalSeconds, setIntervalSeconds] = useState(60);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');
  const [runStats, setRunStats] = useState({
    phase: 'idle', total: 0, completed: 0, success: 0, errors: 0,
    currentFrame: 0, estimatedRemaining: null,
  });
  const stopRequested = useRef(false);
  const runningLock = useRef(false);
  const chosenVideo = controlsHidden ? externalFile : file;
  const chosenInterval = controlsHidden ? externalIntervalSeconds : intervalSeconds;
  const plannedFrames = estimateFrameCount(externalDurationSeconds, chosenInterval);
  const percent = runStats.total
    ? Math.round(100 * runStats.completed / runStats.total) : 0;

  useEffect(() => {
    if (!runningLock.current) {
      setRunStats({ phase: 'idle', total: 0, completed: 0, success: 0,
        errors: 0, currentFrame: 0, estimatedRemaining: null });
      setProgress('');
      setError('');
    }
  }, [externalFile]);

  function formatDuration(seconds) {
    const amount = Math.max(0, Math.round(Number(seconds) || 0));
    if (amount < 60) return `${amount}s`;
    return `${Math.floor(amount / 60)}m ${String(amount % 60).padStart(2, '0')}s`;
  }


  async function startAnalysis() {
    if (!chosenVideo || disabled || runningLock.current) return;
    runningLock.current = true;
    setRunning(true);
    setError('');
    setProgress('Loading video…');
    setRunStats({ phase: 'loading', total: 0, completed: 0, success: 0,
      errors: 0, currentFrame: 0, estimatedRemaining: null });
    stopRequested.current = false;
    const sessionId = crypto.randomUUID();

    const video = document.createElement('video');
    video.preload = 'auto';
    video.muted = true;
    video.playsInline = true;
    const url = URL.createObjectURL(chosenVideo);
    let started = false;

    try {
      // Lock the parent's file/model controls while video metadata is loading.
      onStart?.();
      started = true;
      await new Promise((resolve, reject) => {
        video.onloadeddata = resolve;
        video.onerror = () => reject(new Error('This browser could not decode the video. Try an MP4 (H.264).'));
        video.src = url;
        video.load();
      });
      const duration = video.duration;
      if (!Number.isFinite(duration) || duration <= 0) {
        throw new Error('Video duration could not be determined.');
      }
      if (!video.videoWidth || !video.videoHeight) {
        throw new Error('No usable video frames were found.');
      }
      if (stopRequested.current) {
        setProgress('Stopped before processing any frames.');
        setRunStats((previous) => ({ ...previous, phase: 'stopped' }));
        return;
      }

      if (!validSamplingInterval(chosenInterval)) {
        throw new Error('Choose a valid whole-number sample interval between 1 and 300 seconds.');
      }
      const frameCount = estimateFrameCount(duration, chosenInterval);
      if (frameCount > LARGE_JOB_FRAME_THRESHOLD && controlsHidden && !allowLargeWorkload) {
        throw new Error(`This video would analyse ${frameCount} frames. Confirm the large workload before starting.`);
      }
      // Keep the existing standalone confirmation when the sampler is used without the upload form.
      if (frameCount > 100 && !controlsHidden && !window.confirm(
        `This video will require ${frameCount.toLocaleString()} model requests. ` +
        'The analysis may take a long time. Continue?'
      )) {
        setProgress('Analysis cancelled before processing any frames.');
        setRunStats((previous) => ({ ...previous, phase: 'cancelled' }));
        return;
      }
      const timestamps = buildFrameTimestamps(duration, chosenInterval);

      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('This browser does not support video frame capture.');

      let success = 0;
      let errors = 0;
      const runStartedAt = performance.now();
      setRunStats({ phase: 'running', total: timestamps.length, completed: 0,
        success: 0, errors: 0, currentFrame: 0, estimatedRemaining: null });

      for (let i = 0; i < timestamps.length; i++) {
        if (stopRequested.current) break;
        const seconds = timestamps[i];

        if (seconds > 0) {
          await new Promise((resolve, reject) => {
            video.onseeked = resolve;
            video.onerror = () => reject(new Error(`Cannot seek to ${seconds}s in this video.`));
            video.currentTime = Math.min(seconds, Math.max(0, duration - 0.05));
          });
        }

        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise((resolve, reject) => {
          canvas.toBlob((value) => value ? resolve(value) : reject(new Error('Frame capture failed.')),
            'image/jpeg', 0.85);
        });
        const frameFile = new File([blob], `video_frame_${seconds}s.jpg`, { type: 'image/jpeg' });
        const metadata = { timestampSeconds: seconds, videoName: chosenVideo.name, sessionId };
        onFrameExtracted?.(frameFile, metadata);

        setProgress(`Analysing frame ${i + 1}/${timestamps.length} · ${seconds}s of footage`);
        setRunStats((previous) => ({ ...previous, currentFrame: i + 1 }));
        try {
          // Awaiting each request ensures only one Ollama request at a time.
          await onAnalyzeFrame(frameFile, metadata);
          success += 1;
        } catch (err) {
          errors += 1;
          // Individual frame errors are recorded in the parent panel. Continue.
          setError(`A frame could not be analysed: ${err instanceof Error ? err.message : 'Unknown error'}`);
        }
        const completed = i + 1;
        const elapsedSeconds = (performance.now() - runStartedAt) / 1000;
        const estimate = elapsedSeconds / completed * (timestamps.length - completed);
        setRunStats((previous) => ({ ...previous, completed, success, errors,
          estimatedRemaining: Math.round(estimate) }));
      }
      setRunStats((previous) => ({ ...previous,
        phase: stopRequested.current ? 'stopped' : 'complete', estimatedRemaining: 0 }));
      setProgress(stopRequested.current
        ? `Stopped · ${success} analysed, ${errors} errors.`
        : `Completed · ${success} analysed, ${errors} errors.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Video processing failed.');
      setProgress('Video analysis stopped.');
      setRunStats((previous) => ({ ...previous, phase: 'failed' }));
    } finally {
      if (started) onFinish?.();
      video.pause();
      video.removeAttribute('src');
      video.load();
      URL.revokeObjectURL(url);
      setRunning(false);
      runningLock.current = false;
    }
  }

  useEffect(() => {
    if (startRef) startRef.current = startAnalysis;
    return () => {
      if (startRef && startRef.current === startAnalysis) {
        startRef.current = null;
      }
    };
  }, [startRef, startAnalysis]);

  if (controlsHidden) {
    if (!chosenVideo) return null;
    const activeRun = ['loading', 'running', 'stopped', 'complete', 'failed'].includes(runStats.phase);
    return (
      <div className="ppe-video-run-panel" aria-live="polite">
        <div className="ppe-video-run-header">
          <div>
            <strong>Video analysis progress</strong>
            <p className="muted">Frames are sent to Ollama one at a time.</p>
          </div>
          <span className="ppe-video-run-phase">
            {running ? '● In progress' : runStats.phase === 'complete' ? '✓ Complete'
              : runStats.phase === 'stopped' ? '■ Stopped'
              : runStats.phase === 'failed' ? '⚠ Error' : 'Ready'}
          </span>
        </div>
        <div className="ppe-video-run-stats">
          <span>Sample interval: <strong>{chosenInterval}s</strong></span>
          <span>Estimated frames: <strong>{plannedFrames?.toLocaleString() ?? 'Reading duration…'}</strong></span>
          {activeRun && <span>Processed: <strong>{runStats.completed} / {runStats.total || '—'}</strong></span>}
        </div>
        {plannedFrames > LARGE_JOB_FRAME_THRESHOLD && !running && runStats.phase === 'idle' && (
          <p className="ppe-video-run-warning">
            This will send {plannedFrames.toLocaleString()} requests. Consider a longer
            sample interval; confirm the large workload above before starting.
          </p>
        )}
        {activeRun && (
          <>
            <div className="ppe-video-progress-top">
              <span>{progress || 'Preparing video…'}</span>
              <strong>{percent}%</strong>
            </div>
            <div className="ppe-video-progress-bar" role="progressbar"
              aria-label="Video analysis progress" aria-valuemin={0}
              aria-valuemax={100} aria-valuenow={percent}>
              <span style={{ width: `${percent}%` }} />
            </div>
            <div className="ppe-video-run-stats">
              <span>Successful: <strong>{runStats.success}</strong></span>
              <span>Failed: <strong>{runStats.errors}</strong></span>
              <span>Estimated remaining: <strong>
                {runStats.estimatedRemaining == null ? 'Waiting for first frame…'
                  : formatDuration(runStats.estimatedRemaining)}
              </strong></span>
            </div>
          </>
        )}
        {running && <button className="ppe-video-stop-button" type="button"
          disabled={stopRequested.current}
          onClick={() => {
            stopRequested.current = true;
            setProgress('Stopping after the current frame…');
          }}>
          {stopRequested.current ? 'Stopping…' : '■ Stop after current frame'}
        </button>}
        {error && <p className="analysis-error" role="alert">{error}</p>}
      </div>
    );
  }

  return (
    <div className="ppe-video-controls">
      <div>
        <h3>Video PPE Analysis</h3>
        <p className="muted">Upload a video, sample JPEG frames, and analyse them with the currently selected Ollama model. The video is not uploaded in full.</p>
      </div>
      <label className="ppe-video-input">
        <span>Video file</span>
        <input type="file" accept="video/mp4,video/webm,video/ogg" disabled={running || disabled}
          onChange={(event) => {
            const next = event.target.files?.[0] || null;
            setFile(next);
            setProgress('');
            setError('');
            onVideoSelected?.(next);
          }} />
      </label>
      <label className="ppe-video-interval">
        <span>Sample interval</span>
        <select value={intervalSeconds} disabled={running || disabled}
          onChange={(event) => setIntervalSeconds(Number(event.target.value))}>
          <option value={5}>Every 5 seconds (short tests)</option>
          <option value={10}>Every 10 seconds</option>
          <option value={30}>Every 30 seconds</option>
          <option value={60}>Every 60 seconds (normal)</option>
        </select>
      </label>
      <div className="ppe-video-buttons">
        <button type="button" disabled={!file || running || disabled} onClick={startAnalysis}>
          {running ? 'Analysing video…' : 'Analyse video'}
        </button>
        {running && <button type="button" className="outline-button"
          onClick={() => { stopRequested.current = true; }}>
          Stop after this frame
        </button>}
      </div>
      {progress && <p className="ppe-video-progress" role="status">{progress}</p>}
      {error && <p className="analysis-error" role="alert">{error}</p>}
    </div>
  );
}
