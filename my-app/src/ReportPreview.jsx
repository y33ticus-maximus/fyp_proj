import { useEffect, useState } from 'react';
import './ReportPreview.css';

const MAX_FRAMES = 6;

const findingLabels = {
  confirmed: 'Confirmed PPE concern',
  false_alert: 'False alert / PPE present',
  inconclusive: 'Inconclusive - more evidence required',
};

function videoTime(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map((n) => String(n).padStart(2, '0')).join(':');
}

function ppeLabel(value) {
  return { yes: 'Reported missing', no: 'No violation reported', unclear: 'Unclear' }[value] || 'Not recorded';
}

function recommendationReason(frame) {
  const missing = ['helmet', 'vest', 'boots'].filter((item) => frame[`${item}_violation`] === 'yes');
  if (missing.length > 1) return 'Multiple reported PPE concerns';
  if (missing.length === 1) return `Reported ${missing[0]} concern`;
  if (['helmet', 'vest', 'boots'].some((item) => frame[`${item}_violation`] === 'unclear')) {
    return 'Unclear PPE assessment';
  }
  if (frame.overall_status === 'compliant') return 'Compliant context';
  return 'Additional time coverage';
}

function displayTime(value) {
  if (!value || Number.isNaN(Date.parse(value))) return 'Not recorded';
  return new Intl.DateTimeFormat('en-SG', {
    timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(new Date(value));
}

function EvidenceThumbnail({ src, alt }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);
  if (!src || failed) return <div className="ppe-report-image-missing">Evidence unavailable</div>;
  return <img className="ppe-report-thumbnail" src={src} alt={alt} loading="eager"
    onError={() => setFailed(true)} />;
}

export default function ReportPreview({ incident, frames, review, onClose }) {
  const [selectedIds, setSelectedIds] = useState([]);
  const [availableIds, setAvailableIds] = useState([]);
  const [recommendedIds, setRecommendedIds] = useState([]);
  const [selectionMode, setSelectionMode] = useState('automatic');
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    fetch(`/api/incidents/${incident.id}/report-options`)
      .then(async (response) => {
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || `Could not load report options (${response.status}).`);
        return result;
      })
      .then((result) => {
        if (!active) return;
        const allowed = Array.isArray(result.availableIds) ? result.availableIds : [];
        const suggested = Array.isArray(result.recommendedIds) ? result.recommendedIds : [];
        setAvailableIds(allowed);
        setRecommendedIds(suggested);
        setSelectedIds(suggested);
        setSelectionMode('automatic');
      })
      .catch((err) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [incident.id]);

  const available = new Set(availableIds);
  const sortedFrames = frames.slice().sort((left, right) =>
    Number(left.video_seconds || 0) - Number(right.video_seconds || 0) || left.id - right.id);
  const shownFrames = sortedFrames.filter((frame) => selectedIds.includes(frame.id));
  const latestReview = review.history?.find((entry) => entry.action === 'review');
  const latestResolution = review.history?.find((entry) => entry.action === 'resolve');

  function toggleFrame(id) {
    setError('');
    setSelectionMode('manual');
    setSelectedIds((current) => current.includes(id)
      ? current.filter((candidate) => candidate !== id)
      : current.length < MAX_FRAMES ? [...current, id] : current);
  }

  function resetRecommendations() {
    setSelectedIds(recommendedIds);
    setSelectionMode('automatic');
    setError('');
  }

  async function downloadPdf() {
    setExporting(true);
    setError('');
    try {
      const response = await fetch(`/api/incidents/${incident.id}/summary-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis_ids: selectedIds }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.detail || `Report generation failed (${response.status}).`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const download = document.createElement('a');
      download.href = url;
      download.download = `PPE_Incident_${incident.id}_Summary.pdf`;
      document.body.appendChild(download);
      download.click();
      download.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      setError(err.message);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="ppe-report-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="ppe-report-dialog" role="dialog" aria-modal="true"
        aria-labelledby="ppe-report-title">
        <header className="ppe-report-header">
          <div>
            <span className="ppe-report-kicker">STAGE 6A · INCIDENT DOCUMENTATION</span>
            <h2 id="ppe-report-title">Summary Report Preview</h2>
            <p>Incident #{incident.id} · {incident.videoName ? 'Video analysis' : 'Image analysis'}</p>
          </div>
          <button type="button" className="outline-button" onClick={onClose}>✕ Close</button>
        </header>

        <div className="ppe-report-content">
          <div className="ppe-report-paper" aria-label="Report content preview">
            <div className="ppe-report-document-heading">
              <span>PPE SAFETY MONITORING</span>
              <h3>Incident Summary</h3>
              <small>AI assessments are not verified safety findings.</small>
            </div>
            <div className="ppe-report-metadata">
              <div><span>Incident</span><strong>#{incident.id} · {incident.status}</strong></div>
              <div><span>Location</span><strong>{incident.location}</strong></div>
              <div><span>Model</span><strong>{incident.model || 'Not recorded'}</strong></div>
              <div><span>Detected</span><strong>{displayTime(incident.createdAt)}</strong></div>
              <div><span>Source</span><strong>{incident.videoName || incident.camera || 'Manual upload'}</strong></div>
              <div><span>Saved analyses</span><strong>{frames.length}</strong></div>
            </div>
            <h4>AI-reported PPE concerns</h4>
            <div className="ppe-report-ppe">
              <span>Helmet: <strong>{ppeLabel(incident.helmetViolation)}</strong></span>
              <span>Vest: <strong>{ppeLabel(incident.vestViolation)}</strong></span>
              <span>Boots: <strong>{ppeLabel(incident.bootsViolation)}</strong></span>
            </div>
            <h4>Human verification</h4>
            <p><strong>{findingLabels[review.currentFinding] || 'Not human verified'}</strong></p>
            {latestReview && review.currentFinding && (
              <p className="ppe-report-secondary">{latestReview.reviewer}: {latestReview.notes}</p>
            )}
            {latestResolution?.notes && (
              <p className="ppe-report-secondary">Corrective action: {latestResolution.notes}</p>
            )}
            <p className="ppe-report-disclaimer">The downloaded PDF uses saved incident data and selected frames. It does not embed the original playable video.</p>
          </div>

          <section className="ppe-report-evidence-workspace" aria-label="Choose and preview report evidence">
            <div className="ppe-report-evidence-heading">
              <div>
                <h3>Evidence for this report</h3>
                <p>Select a frame on the left and immediately see it in the report on the right.</p>
              </div>
              <div className="ppe-report-evidence-actions">
                <span className="ppe-report-count">{selectedIds.length} / {MAX_FRAMES} selected</span>
                <button type="button" className="outline-button ppe-report-reset"
                  disabled={loading} onClick={resetRecommendations}>Reset to automatic</button>
              </div>
            </div>
            <div className="ppe-report-evidence-columns">
              <div className="ppe-report-controls">
                <h4>Available frames</h4>
                <p className="ppe-report-secondary">{selectionMode === 'automatic'
                  ? 'Automatically recommended frames are checked.'
                  : 'Manual selection applied. Reset to restore recommendations.'}</p>
                <div className="ppe-report-frame-options">
                  {loading ? <p>Loading available frames…</p> :
                    sortedFrames.filter((frame) => available.has(frame.id)).length ?
                      sortedFrames.filter((frame) => available.has(frame.id)).map((frame) => (
                        <label key={frame.id} className={`ppe-report-frame-option ${selectedIds.includes(frame.id) ? 'is-selected' : ''}`}>
                          <input type="checkbox" checked={selectedIds.includes(frame.id)}
                            disabled={!selectedIds.includes(frame.id) && selectedIds.length >= MAX_FRAMES}
                            onChange={() => toggleFrame(frame.id)} />
                          <div className="ppe-report-option-image">
                            <EvidenceThumbnail src={frame.evidence_url}
                              alt={`Available evidence at ${videoTime(frame.video_seconds)}`} />
                          </div>
                          <span>
                            <strong>{incident.videoName ? videoTime(frame.video_seconds) : 'Image evidence'}</strong>
                            <small>{frame.overall_status} · {['helmet', 'vest', 'boots']
                              .filter((ppe) => frame[`${ppe}_violation`] === 'yes').join(', ') || 'No definite missing PPE'}</small>
                            {recommendedIds.includes(frame.id) && (
                              <em className="ppe-report-recommendation">★ Suggested: {recommendationReason(frame)}</em>
                            )}
                          </span>
                        </label>
                      )) : <p className="ppe-report-secondary">No retrievable saved photographs are available for this incident.</p>}
                </div>
              </div>
              <div className="ppe-report-selected-panel">
                <div className="ppe-report-selected-heading">
                  <h4>Selected evidence preview</h4>
                  <span>{shownFrames.length} frame(s)</span>
                </div>
                <div className="ppe-report-selected-scroll">
                  {loading ? <p className="ppe-report-secondary">Checking saved evidence…</p> :
                    shownFrames.length ? (
                      <div className="ppe-report-selected-grid">
                        {shownFrames.map((frame) => (
                          <article className="ppe-report-frame-card" key={frame.id}>
                            <EvidenceThumbnail src={frame.evidence_url}
                              alt={`Selected evidence at ${videoTime(frame.video_seconds)}`} />
                            <div>
                              <strong>{incident.videoName ? videoTime(frame.video_seconds) : 'Saved photograph'}</strong>
                              <span>{frame.overall_status} · Helmet: {ppeLabel(frame.helmet_violation)}</span>
                              <span>Vest: {ppeLabel(frame.vest_violation)} · Boots: {ppeLabel(frame.boots_violation)}</span>
                              <button type="button" className="ppe-report-remove-frame"
                                onClick={() => toggleFrame(frame.id)}>Remove from PDF</button>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : <p className="ppe-report-secondary">No evidence selected. The PDF will still include the incident record.</p>}
                </div>
              </div>
            </div>
            <p className="ppe-report-evidence-note">The summary includes at most six saved frames. Automatic suggestions use reported PPE concerns and time coverage, not verified severity. Repeated frames may show the same worker.</p>
          </section>
        </div>

        <footer className="ppe-report-footer">
          {error && <p role="alert" className="ppe-report-error">{error}</p>}
          <span>Detailed Reports and bulk CSV exports will follow in later stages.</span>
          <div>
            <button type="button" className="outline-button" onClick={onClose}>Cancel</button>
            <button type="button" disabled={loading || exporting}
              onClick={downloadPdf}>{exporting ? 'Generating PDF…' : 'Download Summary PDF'}</button>
          </div>
        </footer>
      </section>
    </div>
  );
}
