import { useCallback, useEffect, useState } from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import "./App.css";
import AnalysisUpload from "./AnalysisUpload";

// The previous browser data is read only for one-way migration into SQLite.
// It is not deleted or overwritten, so you can recover it if needed.
const LEGACY_STORAGE_KEY = "ppe-manager-demo-v1";
const CLIENT_KEY = "ppe-manager-migration-client-id";
const activeStatus = (status) => status === "Open" || status === "Review";
const blankStats = {
  complianceRate: null, decisive: 0, compliant: 0, violations: 0,
  unclear: 0, bootsUnverified: 0, noWorkers: 0, failed: 0,
  analyses: 0, workerObservations: 0, incidents: 0, activeIncidents: 0,
};

async function apiJson(path, init = undefined) {
  const response = await fetch(path, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `API request failed (${response.status})`);
  return body;
}

function videoTime(seconds) {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  return [Math.floor(n / 3600), Math.floor(n % 3600 / 60), n % 60]
    .map((value) => String(value).padStart(2, "0")).join(":");
}

function App() {
  const [data, setData] = useState({ items: [], notifications: [], statistics: blankStats, trend: [] });
  const [filter, setFilter] = useState("All");
  const [selectedId, setSelectedId] = useState(null);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notificationFilter, setNotificationFilter] = useState("All");
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");
  const [message, setMessage] = useState("");
  const [storageError, setStorageError] = useState("");
  const [detailFrames, setDetailFrames] = useState([]);
  const [selectedEvidenceUrl, setSelectedEvidenceUrl] = useState("");
  const { items, notifications } = data;
  const stats = data.statistics || blankStats;
  const trend = data.trend || [];

  const refreshData = useCallback(async () => {
    const fresh = await apiJson('/api/state');
    setData(fresh);
    setStorageError('');
    return fresh;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Migrate the old browser incidents at startup, using a stable unique client ID.
        // The backend automatically ignores empty, example and simulation records.
        const legacy = JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY) || 'null');
        if (legacy && Array.isArray(legacy.items) && legacy.items.some(i => i?.model && i?.issue && i?.source !== 'Simulation')) {
          let clientId = localStorage.getItem(CLIENT_KEY);
          if (!clientId) {
            clientId = crypto.randomUUID();
            localStorage.setItem(CLIENT_KEY, clientId);
          }
          const result = await apiJson('/api/migrate-browser-state', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: clientId, items: legacy.items, notifications: legacy.notifications || [] }),
          });
          if (result.imported && !cancelled) {
            setMessage(`${result.imported} earlier real incident(s) imported into SQLite. Browser backup retained.`);
          }
        }
      } catch (err) {
        if (!cancelled) setStorageError(`Earlier browser incidents could not be imported: ${err.message}`);
      }
      try {
        const fresh = await apiJson('/api/state');
        if (!cancelled) setData(fresh);
      } catch (err) {
        if (!cancelled) setStorageError(`Database unavailable: ${err.message}`);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => { localStorage.setItem('theme', theme); }, [theme]);

  useEffect(() => {
    if (selectedId == null) { setDetailFrames([]); setSelectedEvidenceUrl(''); return; }
    let cancelled = false;
    setDetailFrames([]);
    setSelectedEvidenceUrl('');
    apiJson(`/api/incidents/${selectedId}/analyses`)
      .then(result => { if (!cancelled) setDetailFrames(result.analyses || []); })
      .catch(() => { if (!cancelled) setDetailFrames([]); });
    return () => { cancelled = true; };
  }, [selectedId]);

  const unread = notifications.filter((n) => !n.read).length;
  const visibleItems = items.filter((item) => filter === 'All' || item.status === filter);
  const selected = items.find((item) => item.id === selectedId);
  const visibleNotifications = notifications.filter((n) => notificationFilter === 'All' || !n.read);

  async function handleAnalysisResult(result) {
    try {
      await refreshData();
    } catch (err) {
      setStorageError(`Analysis was saved, but refreshing the dashboard failed: ${err.message}`);
    }
    setFilter('All');
    if (result.incident_action === 'grouped') {
      setMessage(`Repeated ${result.overall_status} grouped into incident #${result.incident_id}. Frame still saved; no duplicate notification.`);
    } else if (result.incident_action === 'created') {
      setMessage(`New incident #${result.incident_id} and notification saved. Please review the evidence.`);
    } else if (result.overall_status === 'compliant') {
      setMessage('Analysis saved: PPE compliant according to the model; no incident created.');
    } else if (result.overall_status === 'boots_unverified') {
      setMessage('Analysis saved: boots unverified; not counted as compliant and no alert by default.');
    } else if (result.overall_status === 'no_workers') {
      setMessage('Analysis saved: no workers detected; no incident created.');
    } else {
      setMessage('Analysis saved.');
    }
  }

  async function changeStatus(id, status) {
    try {
      await apiJson(`/api/incidents/${id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      await refreshData();
      setMessage(`Incident #${id} marked ${status}.`);
    } catch (err) { setStorageError(`Could not change status: ${err.message}`); }
  }

  async function markRead(notificationId) {
    try {
      await apiJson(`/api/notifications/${notificationId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ read: true }),
      });
      await refreshData();
    } catch (err) { setStorageError(`Could not mark notification read: ${err.message}`); }
  }

  function openNotification(n) {
    setSelectedId(n.incidentId);
    setNotificationsOpen(false);
    if (!n.read) void markRead(n.id);
  }

  async function markAllRead() {
    try {
      await apiJson('/api/notifications/mark-all-read', { method: 'POST' });
      await refreshData();
    } catch (err) { setStorageError(`Could not mark notifications read: ${err.message}`); }
  }

  return (
    <main className={`dashboard ${theme}-theme`}>
      <header className="topbar">
        <div>
          <p className="eyebrow">SAFETY MONITORING · MANAGER PORTAL</p>
          <h1>PPE Dashboard</h1>
          <p className="muted">Site overview · Incident management</p>
        </div>
        <div className="header-actions">
          <span className="demo-badge">PROTOTYPE · OLLAMA</span>
          <div className="notification-anchor">
            <button className="toolbar-button" onClick={() => setNotificationsOpen((open) => !open)} aria-label={`Notifications, ${unread} unread`} aria-expanded={notificationsOpen}>
              🔔 Notifications {unread > 0 && <span className="unread-count">{unread}</span>}
            </button>
            {notificationsOpen && (
              <div className="notification-panel">
                <div className="notification-heading"><strong>Notifications</strong><button className="text-button" onClick={() => setNotificationsOpen(false)}>Close</button></div>
                <div className="notification-tools">
                  <select aria-label="Filter notifications" value={notificationFilter} onChange={(e) => setNotificationFilter(e.target.value)}><option>All</option><option>Unread</option></select>
                  <button className="text-button" disabled={unread === 0} onClick={markAllRead}>Mark all read</button>
                </div>
                <div className="notification-list">
                  {visibleNotifications.map((n) => {
                    const incident = items.find((item) => item.id === n.incidentId);
                    if (!incident) return null;
                    return <button key={n.id} className={`notification-entry ${n.read ? "" : "unread"}`} onClick={() => openNotification(n)}>
                      <span><strong>{incident.issue}</strong>{!n.read && <span className="unread-dot" />}</span>
                      <small>{incident.location} · {incident.time} · {incident.severity}</small>
                      <small>Incident #{incident.id} · {incident.status}</small>
                    </button>;
                  })}
                  {visibleNotifications.length === 0 && <p className="muted empty-state">No notifications to show.</p>}
                </div>
              </div>
            )}
          </div>
          <button className="toolbar-button" onClick={() => setTheme((current) => current === "light" ? "dark" : "light")}>{theme === "light" ? "🌙 Dark mode" : "☀️ Light mode"}</button>
        </div>
      </header>

      <AnalysisUpload onResult={handleAnalysisResult} />

      {storageError && <div className="feedback" role="alert">{storageError}<button className="text-button" onClick={() => setStorageError("")}>Dismiss</button></div>}
      {message && <div className="feedback" role="status">{message}<button className="text-button" onClick={() => setMessage("")}>Dismiss</button></div>}

       <section className="metrics">
         <Metric title="Model-reported PPE compliance" value={stats.complianceRate == null ? "—" : `${stats.complianceRate}%`} note={`${stats.compliant} compliant / ${stats.violations} violations · decisive predictions only`} />
         <Metric title="Worker observations" value={stats.workerObservations} note={`${stats.analyses} analysed attempts · not unique people`} />
         <Metric title="Recorded incidents" value={stats.incidents} note="Persistent SQLite records (including earlier imports)" />
         <Metric title="Active incidents" value={stats.activeIncidents} note="Open + under review" />
       </section>
       <p className="metrics-explanation">Unverified boots: {stats.bootsUnverified} · Unclear: {stats.unclear} · No workers: {stats.noWorkers} · Failed analyses: {stats.failed}. These statistics combine all models and are not ground-truth performance scores. Unclear and failed results do not count as compliant. Earlier browser incidents appear in incident totals, but not in historical compliance rates because their full analysis history was not saved.</p>

       <section className="panel">
         <h2>Model-reported PPE compliance trend</h2>
         <p className="muted">Last 7 days · Singapore time · compliant / (compliant + violation). These are predictions, not verified safety audit findings. Days without decisive results are blank.</p>
         {trend.some(day => day.decisive > 0) ? (
           <div className="chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={trend}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" /><YAxis domain={[0, 100]} unit="%" /><Tooltip labelFormatter={(_, payload) => payload?.[0]?.payload?.date || ''} formatter={(value) => value == null ? 'No decisive results' : `${value}%`} /><Line type="monotone" dataKey="rate" stroke="#16a34a" strokeWidth={3} dot={{ r: 4 }} connectNulls={false} /></LineChart></ResponsiveContainer></div>
         ) : <p className="muted empty-state">No decisive compliance predictions recorded yet. This chart will populate automatically after analyses.</p>}
       </section>

      <section className="panel"><div className="table-heading"><div><h2>Incident management</h2><p className="muted">Open → Review → Resolved or Dismissed. Consecutive video detections are grouped; each frame is still recorded.</p></div><select aria-label="Filter incidents" value={filter} onChange={(e) => setFilter(e.target.value)}>{["All", "Open", "Review", "Resolved", "Dismissed"].map((status) => <option key={status}>{status}</option>)}</select></div>
        <div className="table-scroll"><table><thead><tr><th>ID / Time</th><th>Location</th><th>Violation</th><th>Severity</th><th>Status</th><th>Action</th></tr></thead><tbody>
          {visibleItems.map((item) => <tr key={item.id}><td>#{item.id}<br/><span className="muted">{item.time}</span></td><td>{item.location}</td><td>{item.issue}{item.detectionCount > 1 && <span className="grouped-count"> · {item.detectionCount} detections</span>}</td><td><span className={`severity ${item.severity.toLowerCase()}`}>{item.severity}</span></td><td><span className={`status ${item.status.toLowerCase()}`}>{item.status === "Review" ? "Under Review" : item.status}</span></td><td><button className="outline-button" onClick={() => setSelectedId(item.id)}>Details</button></td></tr>)}
          {visibleItems.length === 0 && <tr><td colSpan="6">No incidents match this filter.</td></tr>}
        </tbody></table></div>
      </section>

      {selected && <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setSelectedId(null); }}><section className="detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-heading"><div className="modal-heading"><div><p className="eyebrow">INCIDENT #{selected.id}</p><h2 id="detail-heading">{selected.issue}</h2></div><button className="outline-button" onClick={() => setSelectedId(null)} aria-label="Close incident details">✕</button></div>
        <dl className="detail-grid"><div><dt>Location</dt><dd>{selected.location}</dd></div><div><dt>Camera</dt><dd>{selected.camera}</dd></div><div><dt>Time</dt><dd>{selected.time}</dd></div><div><dt>Source</dt><dd>{selected.source}</dd></div><div><dt>Model</dt><dd>{selected.model || "Not available"}</dd></div><div><dt>Confidence</dt><dd>{typeof selected.confidence === "number" ? `${Math.round(selected.confidence * 100)}% (sample)` : "Not provided by model"}</dd></div><div><dt>Severity</dt><dd>{selected.severity}</dd></div><div><dt>Status</dt><dd>{selected.status === "Review" ? "Under Review" : selected.status}</dd></div>{selected.model && <><div><dt>Helmet violation</dt><dd>{selected.helmetViolation}</dd></div><div><dt>Vest violation</dt><dd>{selected.vestViolation}</dd></div><div><dt>Boots violation</dt><dd>{selected.bootsViolation ?? "Not assessed (older incident)"}</dd></div><div><dt>Workers identified</dt><dd>{selected.workerCount ?? "Not available"}</dd></div><div><dt>Inference time</dt><dd>{selected.processingSeconds ?? "—"}s</dd></div><div><dt>Recorded detections</dt><dd>{selected.detectionCount ?? 1}</dd></div><div><dt>Last detected</dt><dd>{selected.lastSeenAt ? new Date(selected.lastSeenAt).toLocaleString() : "—"}</dd></div>{selected.videoName && <><div><dt>Video</dt><dd>{selected.videoName}</dd></div><div><dt>Frame range</dt><dd>{videoTime(selected.firstVideoSecond)} – {videoTime(selected.lastVideoSecond)}</dd></div></>}</>}</dl>
        {selected.evidenceUrl ? (
          <div className="evidence-section"><h3>Image evidence</h3><p className="muted">Model-generated assessment — verify the photograph before acting. Boot appearance cannot confirm certified safety footwear.</p><img src={selectedEvidenceUrl || selected.evidenceUrl} alt={`Evidence photo for incident ${selected.id}`} loading="lazy" /></div>
        ) : <p className="muted">No evidence photo was saved for this incident.</p>}
        {detailFrames.length > 1 && (
          <div className="saved-frame-history"><h3>Saved detection frames ({detailFrames.length})</h3>
            <p className="muted">Each frame is recorded; select its timestamp to inspect its stored evidence image.</p>
            <div className="saved-frame-list">{detailFrames.filter(frame => frame.evidence_url).map(frame =>
              <button type="button" key={frame.id} className="outline-button" onClick={() => setSelectedEvidenceUrl(frame.evidence_url)}>
                {frame.video_seconds == null ? `Analysis #${frame.id}` : videoTime(frame.video_seconds)}
              </button>
            )}</div>
          </div>
        )}
        <p className="muted">This is a prototype. A VLM prediction is not a verified safety violation; review all evidence before taking action.</p>
        <div className="modal-actions">{selected.status === "Open" && <button onClick={() => changeStatus(selected.id, "Review")}>Start review</button>}{activeStatus(selected.status) && <><button onClick={() => changeStatus(selected.id, "Resolved")}>Mark resolved</button><button className="outline-button" onClick={() => changeStatus(selected.id, "Dismissed")}>Dismiss false alert</button></>}{!activeStatus(selected.status) && <button className="outline-button" onClick={() => changeStatus(selected.id, "Review")}>Reopen for review</button>}</div>
      </section></div>}
      <footer>School project prototype · Image/video → FastAPI → configured Ollama · SQLite records · No live camera or Telegram integration</footer>
    </main>
  );
}

function Metric({ title, value, note }) {
  return <article className="metric-card"><p className="muted">{title}</p><strong>{value}</strong><p className="metric-note">{note}</p></article>;
}
export default App;
