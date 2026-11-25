import { useCallback, useEffect, useRef, useState } from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar } from "recharts";
import "./App.css";
import AnalysisUpload from "./AnalysisUpload";
import ReportPreview from "./ReportPreview";

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
const emptyReview = { currentFinding: null, history: [] };
const humanFindingLabel = (finding) => ({
  confirmed: 'Confirmed PPE concern',
  false_alert: 'False alert / PPE present',
  inconclusive: 'Inconclusive — needs evidence',
}[finding] || 'Not verified');
const reviewEventLabel = (event) => ({
  review: humanFindingLabel(event.finding),
  start: 'Review started',
  resolve: 'Incident resolved',
  dismiss: 'False alert dismissed',
  reopen: 'Incident reopened',
  archived: 'Incident archived',
  status_changed: 'Legacy status change (reviewer unverified)',
}[event.action] || event.action);

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

function incidentDisplayTime(value, fallback = "—") {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat('en-SG', {
    timeZone: 'Asia/Singapore',
    day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(date);
}

function matchesPpeCategory(item, category) {
  if (category === 'All') return true;
  const issue = String(item.issue || '').toLowerCase();
  const flags = [item.helmetViolation, item.vestViolation, item.bootsViolation];
  const hasStructuredFlags = flags.some((value) => ['yes', 'no', 'unclear'].includes(value));
  // Prefer the structured PPE flags. Legacy records can fall back to issue text.
  if (category === 'Helmet') {
    return item.helmetViolation === 'yes' || (!hasStructuredFlags && /helmet|hard hat/.test(issue));
  }
  if (category === 'Safety vest') {
    return item.vestViolation === 'yes' || (!hasStructuredFlags && /vest/.test(issue));
  }
  if (category === 'Boots') {
    return item.bootsViolation === 'yes' || (!hasStructuredFlags && /boot|footwear/.test(issue));
  }
  // An incident can contain both a definite violation and an unclear PPE item.
  return flags.some((value) => value === 'unclear') || /unclear|unverified/.test(issue);
}

function filterAndSortIncidents(incidents, { search, severity, ppe, sort }) {
  const query = search.trim().toLowerCase();
  const matching = incidents.filter((item) => {
    if (severity !== 'All' && item.severity !== severity) return false;
    if (!matchesPpeCategory(item, ppe)) return false;
    if (!query) return true;
    return [item.id, `#${item.id}`, item.location, item.camera,
      item.source, item.model, item.issue, item.status]
      .some((value) => String(value ?? '').toLowerCase().includes(query));
  });
  const timestamp = (item) => Date.parse(item.createdAt || '') || 0;
  return matching.sort((left, right) => {
    const newestFirst = timestamp(right) - timestamp(left) || right.id - left.id;
    if (sort === 'oldest') return -newestFirst;
    if (sort === 'severity') {
      const highFirst = Number(right.severity === 'High') - Number(left.severity === 'High');
      return highFirst || newestFirst;
    }
    return newestFirst;
  });
}

function App() {
  const [data, setData] = useState({ items: [], notifications: [], statistics: blankStats, trend: [] });
  // PPE_SIDEBAR_HISTORY_V2
  const [filter, setFilter] = useState("All");
  const [historyFilter, setHistoryFilter] = useState("All");
  const [incidentSearch, setIncidentSearch] = useState('');
  const [severityFilter, setSeverityFilter] = useState('All');
  const [ppeFilter, setPpeFilter] = useState('All');
  const [incidentSort, setIncidentSort] = useState('newest');
  const [activePage, setActivePage] = useState("dashboard");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedNotificationRowId, setSelectedNotificationRowId] = useState(null);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notificationFilter, setNotificationFilter] = useState("All");
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "light");
  const [message, setMessage] = useState("");
  const [storageError, setStorageError] = useState("");
  const [detailFrames, setDetailFrames] = useState([]);
  const [selectedEvidenceUrl, setSelectedEvidenceUrl] = useState("");
  const [zoomEvidenceUrl, setZoomEvidenceUrl] = useState("");
  const [reportOpen, setReportOpen] = useState(false);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState("");
  const [selectedFrameIndex, setSelectedFrameIndex] = useState(0);
  const [reviewData, setReviewData] = useState(emptyReview);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const [reviewFeedback, setReviewFeedback] = useState('');
  const [reviewerName, setReviewerName] = useState('');
  const [manualFinding, setManualFinding] = useState('');
  const [reviewNotes, setReviewNotes] = useState('');
  const [correctiveAction, setCorrectiveAction] = useState('');
  const frameHistoryRef = useRef(null);
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
  let refreshing = false;

  const interval = setInterval(async () => {
    // Avoid unnecessary requests when the tab is hidden.
    if (document.hidden || refreshing) return;

    refreshing = true;

    try {
      const fresh = await apiJson('/api/state');

      if (!cancelled) {
        setData(fresh);
      }
    } catch (error) {
      // Keep existing records visible if a refresh fails.
      console.warn('Automatic dashboard refresh failed:', error);
    } finally {
      refreshing = false;
    }
  }, 5000);

  return () => {
    cancelled = true;
    clearInterval(interval);
  };
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
    if (selectedId == null) {
      setReportOpen(false);
      setDetailFrames([]);
      setSelectedEvidenceUrl('');
      setZoomEvidenceUrl('');
      setDetailsLoading(false);
      setDetailsError('');
      return;
    }
    let cancelled = false;
    setDetailFrames([]);
    setReportOpen(false);
    setSelectedEvidenceUrl('');
    setZoomEvidenceUrl('');
    setDetailsLoading(true);
    setDetailsError('');
    setSelectedFrameIndex(0);
    apiJson(`/api/incidents/${selectedId}/analyses`)
      .then(result => { if (!cancelled) setDetailFrames(result.analyses || []); })
      .catch(() => {
        if (!cancelled) {
          setDetailFrames([]);
          setDetailsError('Saved worker assessments could not be loaded. Please try opening Details again.');
        }
      })
      .finally(() => { if (!cancelled) setDetailsLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId]);

  useEffect(() => {
    setReviewData(emptyReview);
    setReviewerName('');
    setManualFinding('');
    setReviewNotes('');
    setCorrectiveAction('');
    setReviewError('');
    setReviewFeedback('');
    setReviewLoading(selectedId != null);
    if (selectedId == null) return;
    let cancelled = false;
    apiJson(`/api/incidents/${selectedId}/reviews`)
      .then((result) => { if (!cancelled) setReviewData(result); })
      .catch((error) => {
        if (!cancelled) setReviewError(`Could not load review history: ${error.message}`);
      })
      .finally(() => { if (!cancelled) setReviewLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId]);

  const unread = notifications.filter((n) => !n.read).length;
  const activeItems = items.filter((item) => activeStatus(item.status));
  const historyItems = items.filter((item) => ['Resolved', 'Dismissed', 'Archived'].includes(item.status));
  // The homepage uses the same saved incident records as the management page.
  // No additional requests or independent dashboard counters are introduced.
  const recentActiveItems = [...activeItems]
    .sort((left, right) =>
      (Date.parse(right.createdAt || '') || 0) - (Date.parse(left.createdAt || '') || 0)
      || Number(right.id) - Number(left.id))
    .slice(0, 5);
  const highPriorityCount = activeItems.filter((item) => item.severity === 'High').length;
  const underReviewCount = activeItems.filter((item) => item.status === 'Review').length;
  const openCount = activeItems.filter((item) => item.status === 'Open').length;
  const activePpeSignals = [
    { name: 'Helmet', filter: 'Helmet', tone: 'helmet' },
    { name: 'Safety vest', filter: 'Safety vest', tone: 'vest' },
    { name: 'Boots', filter: 'Boots', tone: 'boots' },
    { name: 'Unclear / unverified', filter: 'Unclear', tone: 'unclear' },
  ].map((signal) => ({
    ...signal,
    count: activeItems.filter((item) => matchesPpeCategory(item, signal.filter)).length,
  }));
  const incidentOptions = {
    search: incidentSearch, severity: severityFilter,
    ppe: ppeFilter, sort: incidentSort,
  };
  const visibleItems = filterAndSortIncidents(
    activeItems.filter((item) => filter === 'All' || item.status === filter),
    incidentOptions
  );
  const visibleHistory = filterAndSortIncidents(
    historyItems.filter((item) => historyFilter === 'All' || item.status === historyFilter),
    incidentOptions
  );
  const selected = items.find((item) => item.id === selectedId);

  function clearIncidentFilters() {
    setIncidentSearch('');
    setSeverityFilter('All');
    setPpeFilter('All');
    setIncidentSort('newest');
    setFilter('All');
    setHistoryFilter('All');
  }

  // Dashboard shortcuts always open the intended queue, even if the user
  // previously applied search/category filters on Incident management.
  function openIncidentQueue({ status = 'All', severity = 'All', ppe = 'All' } = {}) {
    setIncidentSearch('');
    setIncidentSort('newest');
    setFilter(status);
    setSeverityFilter(severity);
    setPpeFilter(ppe);
    setActivePage('incidents');
  }

const videoDetailFrames = detailFrames
  .filter((frame) => frame.video_seconds != null)
  .slice()
  .sort((a, b) => Number(a.video_seconds) - Number(b.video_seconds));

const selectedDetailFrame = videoDetailFrames[selectedFrameIndex] || null;
const selectedWorkerAnalysis = selected?.videoName ? selectedDetailFrame : (detailFrames[0] || null);
const workerAssessments = Array.isArray(selectedWorkerAnalysis?.workers)
  ? selectedWorkerAnalysis.workers : [];
const workerCountMismatch = selectedWorkerAnalysis?.worker_count != null &&
  Number(selectedWorkerAnalysis.worker_count) !== workerAssessments.length;
const hasUnclearWorkerPpe = workerAssessments.some((worker) =>
  ['helmet', 'vest', 'boots'].some((item) => worker[item] === 'unclear')
);
const detailWarnings = [...new Set(detailFrames.flatMap((frame) =>
  Array.isArray(frame.validation_warnings) ? frame.validation_warnings : []
))];

useEffect(() => {
  if (selectedId == null) return;

  function handleDetailKeys(event) {
    if (event.key === "Escape") {
      if (reportOpen) {
        setReportOpen(false);
        return;
      }
      if (zoomEvidenceUrl) {
        setZoomEvidenceUrl('');
        return;
      }
      setSelectedId(null);
      return;
    }

    if (zoomEvidenceUrl || reportOpen) return;
    const tag = event.target?.tagName;
    if (
      ["INPUT", "TEXTAREA", "SELECT"].includes(tag) ||
      event.target?.isContentEditable ||
      !videoDetailFrames.length
    ) return;

    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;

      setSelectedFrameIndex((current) =>
        Math.max(0, Math.min(videoDetailFrames.length - 1, current + direction))
      );
    }
  }

  window.addEventListener("keydown", handleDetailKeys);
  return () => window.removeEventListener("keydown", handleDetailKeys);
}, [selectedId, videoDetailFrames.length, zoomEvidenceUrl, reportOpen]);

useEffect(() => {
  frameHistoryRef.current
    ?.querySelector(`[data-frame-index="${selectedFrameIndex}"]`)
    ?.scrollIntoView({ block: "nearest" });
}, [selectedFrameIndex]);

function reviewLabel(value) {
  if (value === "yes") return "❌ Violation";
  if (value === "no") return "✅ No violation";
  if (value === "unclear") return "⚠️ Unclear";
  return "—";
}

function reviewIcon(value) {
  if (value === "yes") return "❌";
  if (value === "no") return "✅";
  if (value === "unclear") return "⚠️";
  return "—";
}

function workerPpeLabel(value) {
  if (value === 'worn') return 'Worn';
  if (value === 'missing') return 'Missing';
  if (value === 'unclear') return 'Unclear';
  return 'Not recorded';
}

function workerPpeClass(value) {
  return ['worn', 'missing', 'unclear'].includes(value) ? value : 'not-recorded';
}

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


  async function archiveIncident(id) {
    try {
      await apiJson(`/api/incidents/${id}/archive`, {
        method: 'POST'
      });
      await refreshData();
      setSelectedNotificationRowId(null);
      setMessage(
        `Incident #${id} archived; notification cleared. Find it in Incident history.`
      );
    } catch (err) {
      setStorageError(
        `Could not archive incident: ${err.message}`
      );
    }
  }

  async function saveHumanReview(event) {
    event.preventDefault();
    const reviewer = reviewerName.trim();
    const notes = reviewNotes.trim();
    setReviewError('');
    setReviewFeedback('');
    if (!reviewer || !manualFinding || notes.length < 8) {
      setReviewError('Enter your name or initials, select a finding, and write at least 8 characters of review notes.');
      return;
    }
    setReviewBusy(true);
    try {
      const result = await apiJson(`/api/incidents/${selectedId}/reviews`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer, finding: manualFinding, notes }),
      });
      setReviewData(result);
      setCorrectiveAction('');
      const nextStep = {
        confirmed: 'Add the corrective action below, then select Mark resolved.',
        false_alert: 'Dismiss false alert is now available below.',
        inconclusive: 'Keep this incident Under Review until more evidence is available.',
      }[manualFinding];
      try {
        await refreshData();
        setReviewFeedback(`Human finding saved. ${nextStep} The original AI assessment has not changed.`);
      } catch {
        setReviewFeedback('Human finding was saved, but dashboard totals could not refresh. Please reload the page.');
      }
    } catch (error) {
      setReviewError(`Review could not be saved: ${error.message}`);
    } finally {
      setReviewBusy(false);
    }
  }

  async function submitReviewAction(action) {
    const reviewer = reviewerName.trim();
    const notes = action === 'resolve' ? correctiveAction.trim()
      : action === 'dismiss' ? 'Dismissed after the saved false-alert finding.'
      : action === 'reopen' ? 'Reopened for another manual review.'
      : 'Manual review started.';
    setReviewError('');
    setReviewFeedback('');
    if (!reviewer) {
      setReviewError('Enter your name or initials to record this action.');
      return;
    }
    if (action === 'resolve' && notes.length < 8) {
      setReviewError('Describe the corrective action (at least 8 characters) before marking this incident resolved.');
      return;
    }
    setReviewBusy(true);
    try {
      const result = await apiJson(`/api/incidents/${selectedId}/review-actions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, reviewer, notes }),
      });
      setReviewData(result);
      let refreshed = true;
      try {
        await refreshData();
      } catch {
        refreshed = false;
      }
      if (action === 'reopen') {
        setManualFinding('');
        setReviewNotes('');
        setCorrectiveAction('');
      }
      setReviewFeedback({
        start: 'Review started. Record your finding when ready.',
        resolve: 'Incident resolved. Corrective action was added to review history.',
        dismiss: 'False alert dismissed. The review decision remains in history.',
        reopen: 'Incident reopened. Save a fresh finding before closing it again.',
      }[action] + (refreshed ? '' : ' Dashboard status did not refresh; please reload the page.'));
    } catch (error) {
      setReviewError(`Action could not be completed: ${error.message}`);
    } finally {
      setReviewBusy(false);
    }
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
    <div className={`ppe-app-shell ${theme}-theme`}>
      {sidebarOpen && (
        <button
          type="button"
          className="ppe-nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside className={`ppe-sidebar ${sidebarOpen ? 'ppe-sidebar-open' : ''}`}>
        <div className="ppe-sidebar-title">
          <div className="ppe-sidebar-brand">
            <span className="ppe-brand-mark" aria-hidden="true">✓</span>
            <span><strong>PPE Manager</strong><small>Safety intelligence</small></span>
          </div>
          <button type="button" className="ppe-close-sidebar"
            aria-label="Close menu"
            onClick={() => setSidebarOpen(false)}>
            &times;
          </button>
        </div>

        <nav className="ppe-side-nav" aria-label="Main navigation">
          <span className="ppe-nav-caption">WORKSPACE</span>
          {[
            ['dashboard', 'Overview', '▦'],
            ['analysis', 'AI analysis', '◈'],
            ['incidents', 'Incident management', '▤'],
            ['history', 'Incident history', '◷'],
            ['analytics', 'Monitoring analytics', '▥'],
          ].map(([id, label, glyph]) => (
            <button
              key={id}
              type="button"
              className={`ppe-nav-item ${activePage === id ? 'ppe-nav-active' : ''}`}
              aria-current={activePage === id ? 'page' : undefined}
              onClick={() => {
                setActivePage(id);
                setSidebarOpen(false);
              }}
            >
              <span className="ppe-nav-label"><span className="ppe-nav-glyph" aria-hidden="true">{glyph}</span>{label}</span>
              {(id === 'incidents' || id === 'history') && (
                <small>
                  {id === 'incidents' ? activeItems.length : historyItems.length}
                </small>
              )}
            </button>
          ))}
        </nav>
        <div className="ppe-sidebar-foot">
          <span className="ppe-prototype-indicator"><i aria-hidden="true" /> Prototype workspace</span>
          <p>AI assessments support human safety reviews; they do not replace them.</p>
        </div>
      </aside>

      <main className={`dashboard ${theme}-theme`}>
      <header className="topbar">
        <button type="button" className="ppe-open-sidebar"
          onClick={() => setSidebarOpen(true)}>
          Menu
        </button>
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

      <div className={activePage === 'analysis' ? '' : 'ppe-hidden-panel'}>
        <AnalysisUpload onResult={handleAnalysisResult} />
      </div>

      {storageError && <div className="feedback" role="alert">{storageError}<button className="text-button" onClick={() => setStorageError("")}>Dismiss</button></div>}
      {message && <div className="feedback" role="status">{message}<button className="text-button" onClick={() => setMessage("")}>Dismiss</button></div>}

      {activePage === 'dashboard' && (
        <>
          <section className="ppe-command-hero" aria-labelledby="ppe-hero-heading">
            <div className="ppe-hero-content">
              <span className="ppe-hero-kicker"><i aria-hidden="true" /> SITE OPERATIONS OVERVIEW</span>
              <h2 id="ppe-hero-heading">Monitor. Review. Improve.</h2>
              <p>One place to follow PPE analysis trends and act on incidents that need a closer look.</p>
              <div className="ppe-hero-context">
                <span>{activeItems.length} active incident{activeItems.length === 1 ? '' : 's'}</span>
                <span>{underReviewCount} under review</span>
                <span>Singapore time</span>
              </div>
            </div>
            <div className="ppe-hero-actions">
              <button type="button" className="ppe-hero-primary" onClick={() => setActivePage('analysis')}>＋ Analyse media</button>
              <button type="button" className="ppe-hero-secondary" onClick={() => openIncidentQueue()}>Open incident queue <span aria-hidden="true">→</span></button>
            </div>
          </section>

          <section className="metrics ppe-command-metrics" aria-label="Safety monitoring summary">
            <Metric title="Model-reported compliance" value={stats.complianceRate == null ? '—' : `${stats.complianceRate}%`}
              note={`${stats.compliant} compliant · ${stats.violations} violation predictions`} symbol="◎" tone="green" />
            <Metric title="Active incidents" value={activeItems.length}
              note={`${openCount} open · ${underReviewCount} under review`} symbol="!" tone="red" />
            <Metric title="Worker observations" value={stats.workerObservations}
              note="Observations, not unique workers" symbol="♙" tone="blue" />
            <Metric title="Recorded incidents" value={stats.incidents}
              note={`${stats.analyses} saved analysis attempts`} symbol="▤" tone="violet" />
          </section>

          <div className="ppe-command-upper-grid">
            <section className="panel ppe-command-trend" aria-labelledby="ppe-overview-trend-heading">
              <div className="ppe-command-panel-heading">
                <div><span className="ppe-section-kicker">COMPLIANCE TREND</span><h2 id="ppe-overview-trend-heading">Model-reported compliance</h2></div>
                <span className="ppe-command-period">Last 7 days</span>
              </div>
              <p className="muted">Decisive AI predictions only · Singapore time. Empty days have no decisive result.</p>
              {trend.some((day) => day.decisive > 0) ? (
                <div className="chart ppe-command-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={trend} margin={{ top: 12, right: 12, left: -15, bottom: 2 }}>
                      <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#dbe6e5" />
                      <XAxis dataKey="day" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                      <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                      <Tooltip labelFormatter={(_, payload) => payload?.[0]?.payload?.date || ''}
                        formatter={(value) => value == null ? 'No decisive results' : `${value}%`} />
                      <Line type="monotone" dataKey="rate" stroke="#15976a" strokeWidth={3}
                        dot={{ r: 4, fill: '#15976a', stroke: '#fff', strokeWidth: 2 }}
                        activeDot={{ r: 6 }} connectNulls={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <div className="ppe-command-empty-chart">No decisive compliance predictions yet. This chart will update after analyses are saved.</div>}
              <div className="ppe-command-panel-foot"><span>Compliant / (compliant + violation)</span>
                <button type="button" className="ppe-text-link" onClick={() => setActivePage('analytics')}>Explore analytics →</button>
              </div>
            </section>

            <section className="panel ppe-command-attention" aria-labelledby="ppe-attention-heading">
              <div className="ppe-command-panel-heading">
                <div><span className="ppe-section-kicker">REVIEW QUEUE</span><h2 id="ppe-attention-heading">Needs attention</h2></div>
                <span className="ppe-attention-count">{activeItems.length}</span>
              </div>
              <p className="muted">Prioritise incident records awaiting human review.</p>
              <div className="ppe-attention-breakdown">
                <button type="button" onClick={() => openIncidentQueue({ severity: 'High' })}>
                  <span className="ppe-attention-icon critical" aria-hidden="true">!</span>
                  <span><strong>High severity</strong><small>Open or under-review incidents</small></span>
                  <strong className="ppe-attention-value">{highPriorityCount}</strong>
                </button>
                <button type="button" onClick={() => openIncidentQueue({ status: 'Review' })}>
                  <span className="ppe-attention-icon review" aria-hidden="true">◷</span>
                  <span><strong>Under review</strong><small>Human review in progress</small></span>
                  <strong className="ppe-attention-value">{underReviewCount}</strong>
                </button>
                <button type="button" onClick={() => openIncidentQueue({ status: 'Open' })}>
                  <span className="ppe-attention-icon open" aria-hidden="true">▤</span>
                  <span><strong>Open incidents</strong><small>Not yet marked under review</small></span>
                  <strong className="ppe-attention-value">{openCount}</strong>
                </button>
              </div>
              <p className="ppe-attention-disclaimer">Confirm findings against the saved evidence before taking action.</p>
            </section>
          </div>

          <div className="ppe-command-lower-grid">
            <section className="panel ppe-command-recent" aria-labelledby="ppe-recent-heading">
              <div className="ppe-command-panel-heading">
                <div><span className="ppe-section-kicker">LATEST ACTIVITY</span><h2 id="ppe-recent-heading">Recent active incidents</h2></div>
                <button type="button" className="ppe-text-link" onClick={() => openIncidentQueue()}>View all →</button>
              </div>
              <div className="ppe-command-incident-list">
                {recentActiveItems.map((item) => (
                  <button type="button" key={item.id} className="ppe-command-incident"
                    onClick={() => setSelectedId(item.id)} aria-label={`Open details for incident ${item.id}`}>
                    <span className={`ppe-command-severity-marker ${String(item.severity || '').toLowerCase()}`} aria-hidden="true" />
                    <span className="ppe-command-incident-main"><strong>{item.issue || 'PPE concern'}</strong>
                      <small>#{item.id} · {item.location || 'Unknown location'} · {incidentDisplayTime(item.createdAt, item.time || '—')}</small></span>
                    <span className="ppe-command-incident-end"><span className={`status ${String(item.status || '').toLowerCase()}`}>{item.status === 'Review' ? 'Under Review' : item.status}</span><span aria-hidden="true">›</span></span>
                  </button>
                ))}
                {recentActiveItems.length === 0 && <div className="ppe-command-incident-empty">There are no active incidents in the queue. Saved records will appear here when available.</div>}
              </div>
            </section>

            <section className="panel ppe-command-signals" aria-labelledby="ppe-signals-heading">
              <div className="ppe-command-panel-heading">
                <div><span className="ppe-section-kicker">ACTIVE INCIDENTS</span><h2 id="ppe-signals-heading">PPE concern signals</h2></div>
              </div>
              <p className="muted">Number of active incidents referencing each PPE concern.</p>
              <div className="ppe-command-signal-list">
                {activePpeSignals.map((signal) => (
                  <button type="button" className="ppe-command-signal" key={signal.filter}
                    onClick={() => openIncidentQueue({ ppe: signal.filter })}>
                    <span className="ppe-command-signal-label"><span>{signal.name}</span><strong>{signal.count}</strong></span>
                    <span className="ppe-command-signal-track"><span className={signal.tone}
                      style={{ width: `${activeItems.length ? (100 * signal.count / activeItems.length) : 0}%` }} /></span>
                  </button>
                ))}
              </div>
              <p className="ppe-command-signals-note">Categories may overlap. These are model-reported or legacy incident labels, not verified violations.</p>
            </section>
          </div>

          <div className="ppe-command-method-note" role="note">
            <span aria-hidden="true">ⓘ</span>
            <p><strong>How to read these numbers:</strong> Unverified boots: {stats.bootsUnverified} · Unclear: {stats.unclear} · No workers: {stats.noWorkers} · Failed analyses: {stats.failed}. Results span all configured AI models and are not accuracy scores. Unclear and failed assessments do not count as compliant. Earlier imported incidents count towards incidents, but not compliance trends without saved analysis history.</p>
          </div>
        </>
      )}

      {activePage === 'analytics' && <MonitoringAnalytics />}

      {activePage === 'incidents' && (
      <section className="panel"><div className="table-heading"><div><h2>Incident management</h2><p className="muted">Open and under-review incidents only. Archive using X to preserve records in history.</p></div><select aria-label="Filter incidents" value={filter} onChange={(e) => setFilter(e.target.value)}>{["All", "Open", "Review"].map((status) => <option key={status}>{status}</option>)}</select></div>
        <IncidentFilters
          search={incidentSearch} onSearch={setIncidentSearch}
          severity={severityFilter} onSeverity={setSeverityFilter}
          ppe={ppeFilter} onPpe={setPpeFilter}
          sort={incidentSort} onSort={setIncidentSort}
          onReset={clearIncidentFilters}
        />
        <p className="muted ppe-history-count">{visibleItems.length} of {activeItems.length} active incidents</p>
        <div className="table-scroll incident-table-scroll"><table className="incident-management-table"><thead><tr><th>ID / Time</th><th>Location</th><th>Violation</th><th>Severity</th><th>Status</th><th>Actions</th></tr></thead><tbody>
          {visibleItems.map((item) => <tr
      key={item.id}
      className={
        selectedNotificationRowId === item.id
          ? 'incident-notification-selected'
          : ''
      }
      onPointerDown={(event) => {
        if (event.pointerType === 'touch') {
          setSelectedNotificationRowId(item.id);
        }
      }}
    ><td>#{item.id}<br/><span className="muted ppe-incident-table-date">{incidentDisplayTime(item.createdAt, item.time || '—')}</span></td><td>{item.location}</td><td>{item.issue}{item.detectionCount > 1 && <span className="grouped-count"> · {item.detectionCount} detections</span>}</td><td><span className={`severity ${item.severity.toLowerCase()}`}>{item.severity}</span></td><td><span className={`status ${item.status.toLowerCase()}`}>{item.status === "Review" ? "Under Review" : item.status}</span></td><td className="incident-actions-cell">
      <div className="incident-row-actions">
        <button
          type="button"
          className="outline-button"
          onClick={() => setSelectedId(item.id)}
        >
          Details
        </button>

        {activeStatus(item.status) && (
          <button
            type="button"
            className="incident-notification-delete"
            title="Archive incident and clear notification"
            aria-label={`Archive incident #${item.id} and clear notification`}
            onClick={() => archiveIncident(item.id)}
          >
            &times;
          </button>
        )}
      </div>
    </td></tr>)}
          {visibleItems.length === 0 && <tr><td colSpan="6">No incidents match this filter.</td></tr>}
        </tbody></table></div>
      </section>
      )}

      {activePage === 'history' && (
        <section className="panel">
          <div className="table-heading">
            <div>
              <h2>Incident history</h2>
              <p className="muted">Resolved, dismissed and archived records. Evidence remains available in Details.</p>
            </div>
            <select
              aria-label="Filter incident history"
              value={historyFilter}
              onChange={(e) => setHistoryFilter(e.target.value)}
            >
              {['All', 'Resolved', 'Dismissed', 'Archived'].map(
                (status) => <option key={status}>{status}</option>
              )}
            </select>
          </div>

          <IncidentFilters
            search={incidentSearch} onSearch={setIncidentSearch}
            severity={severityFilter} onSeverity={setSeverityFilter}
            ppe={ppeFilter} onPpe={setPpeFilter}
            sort={incidentSort} onSort={setIncidentSort}
            onReset={clearIncidentFilters}
          />
          <p className="muted ppe-history-count">
            {visibleHistory.length} of {historyItems.length} historical incidents
          </p>

          <div className="table-scroll history-table-scroll">
            <table className="incident-management-table">
              <thead>
                <tr>
                  <th>ID / Time</th>
                  <th>Location</th>
                  <th>Violation</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {visibleHistory.map((item) => (
                  <tr key={item.id}>
                    <td>#{item.id}<br/><span className="muted ppe-incident-table-date">{incidentDisplayTime(item.createdAt, item.time || '—')}</span></td>
                    <td>{item.location}</td>
                    <td>
                      {item.issue}
                      {item.detectionCount > 1 && (
                        <span className="grouped-count">
                          {' | '}{item.detectionCount} detections
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`severity ${item.severity.toLowerCase()}`}>
                        {item.severity}
                      </span>
                    </td>
                    <td>
                      <span className={`status ${item.status.toLowerCase()}`}>
                        {item.status}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="outline-button"
                        onClick={() => setSelectedId(item.id)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
                {visibleHistory.length === 0 && (
                  <tr>
                    <td colSpan="6" className="ppe-empty-history">
                      No historical records match this filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {selected && <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) setSelectedId(null); }}><section className="detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-heading"><div className="modal-heading"><div><p className="eyebrow">INCIDENT #{selected.id}</p><h2 id="detail-heading">{selected.issue}</h2></div><div className="ppe-modal-heading-actions"><button type="button" className="outline-button" disabled={detailsLoading || reviewLoading} onClick={() => setReportOpen(true)}>Generate report</button><button type="button" className="outline-button" onClick={() => setSelectedId(null)} aria-label="Close incident details">✕</button></div></div>
        
        {selected.videoName && videoDetailFrames.length > 0 ? (
          <div className="incident-frame-review">

            <div className="incident-review-preview">
              <h3>
                Selected frame: {videoTime(selectedDetailFrame?.video_seconds)}
              </h3>

              {selectedDetailFrame?.evidence_url ? (
                <EvidenceImage
                  key={selectedDetailFrame.evidence_url}
                  src={selectedDetailFrame.evidence_url}
                  alt={`Evidence at ${videoTime(selectedDetailFrame.video_seconds)}`}
                  imageClass="incident-review-image"
                  onEnlarge={() => setZoomEvidenceUrl(selectedDetailFrame.evidence_url)}
                />
              ) : (
                <div className="incident-no-evidence">
                  No evidence image was saved for this frame.
                  Its model results are shown below.
                </div>
              )}

              <div className="incident-review-ppe">
                <div>
                  <span>Helmet</span>
                  <strong>{reviewLabel(selectedDetailFrame?.helmet_violation)}</strong>
                </div>
                <div>
                  <span>Safety vest</span>
                  <strong>{reviewLabel(selectedDetailFrame?.vest_violation)}</strong>
                </div>
                <div>
                  <span>Boots</span>
                  <strong>{reviewLabel(selectedDetailFrame?.boots_violation)}</strong>
                </div>
              </div>

              <div className="incident-frame-navigation">
                <button
                  type="button"
                  className="outline-button"
                  disabled={selectedFrameIndex === 0}
                  onClick={() => setSelectedFrameIndex(i => Math.max(0, i - 1))}
                >
                  &larr; Previous
                </button>

                <span>
                  {selectedFrameIndex + 1} / {videoDetailFrames.length}
                </span>

                <button
                  type="button"
                  className="outline-button"
                  disabled={selectedFrameIndex >= videoDetailFrames.length - 1}
                  onClick={() =>
                    setSelectedFrameIndex(i =>
                      Math.min(videoDetailFrames.length - 1, i + 1)
                    )
                  }
                >
                  Next &rarr;
                </button>
              </div>
            </div>

            <div className="incident-review-history">
              <h3>Frame analysis history ({videoDetailFrames.length})</h3>

              <div className="incident-frame-history" ref={frameHistoryRef}>
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Helmet</th>
                      <th>Vest</th>
                      <th>Boots</th>
                    </tr>
                  </thead>

                  <tbody>
                    {videoDetailFrames.map((frame, index) => (
                      <tr
                        key={frame.id}
                        data-frame-index={index}
                        className={
                          index === selectedFrameIndex
                            ? "incident-selected-frame"
                            : ""
                        }
                      >
                        <td>
                          <button
                            type="button"
                            className="text-button"
                            onClick={() => setSelectedFrameIndex(index)}
                          >
                            {videoTime(frame.video_seconds)}
                          </button>
                        </td>
                        <td title={reviewLabel(frame.helmet_violation)}>
                          {reviewIcon(frame.helmet_violation)}
                        </td>
                        <td title={reviewLabel(frame.vest_violation)}>
                          {reviewIcon(frame.vest_violation)}
                        </td>
                        <td title={reviewLabel(frame.boots_violation)}>
                          {reviewIcon(frame.boots_violation)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="muted">
                Use &larr; / &rarr; or click a timestamp to inspect its results.
              </p>
            </div>
          </div>
        ) : selected.evidenceUrl ? (
          <div className="evidence-section">
            <h3>Image evidence</h3>
            <p className="muted">
              Verify the photograph before taking action.
              Visual appearance cannot confirm certified safety footwear.
            </p>
            <EvidenceImage
              key={selectedEvidenceUrl || selected.evidenceUrl}
              src={selectedEvidenceUrl || selected.evidenceUrl}
              alt={`Evidence photo for incident ${selected.id}`}
              onEnlarge={() => setZoomEvidenceUrl(selectedEvidenceUrl || selected.evidenceUrl)}
            />
          </div>
        ) : (
          <p className="muted">
            No evidence photo was saved for this incident.
          </p>
        )}
        <section className="ppe-worker-review" aria-label="Per-worker PPE assessment">
          <div className="ppe-worker-review-heading">
            <div>
              <h3>Per-worker PPE assessment</h3>
              <p>
                {selected.videoName
                  ? `Saved AI assessment for ${videoTime(selectedDetailFrame?.video_seconds)} (selected frame).`
                  : 'Saved AI assessment for this photograph.'}
              </p>
            </div>
            {selectedWorkerAnalysis && (
              <span className="ppe-worker-count">{workerAssessments.length} listed</span>
            )}
          </div>
          {detailsLoading ? (
            <p className="ppe-worker-empty">Loading saved worker assessments…</p>
          ) : detailsError ? (
            <p className="ppe-worker-empty" role="alert">{detailsError}</p>
          ) : workerAssessments.length ? (
            <div className="ppe-worker-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Worker / position</th>
                    <th>Helmet</th>
                    <th>Safety vest</th>
                    <th>Boots</th>
                  </tr>
                </thead>
                <tbody>
                  {workerAssessments.map((worker, index) => (
                    <tr key={`${selectedWorkerAnalysis?.id || 'photo'}-${index}`}>
                      <td className="ppe-worker-position">{worker.position || `Worker ${index + 1}`}</td>
                      {['helmet', 'vest', 'boots'].map((item) => (
                        <td key={item}>
                          <span className={`ppe-worker-status ${workerPpeClass(worker[item])}`}>
                            {workerPpeLabel(worker[item])}
                          </span>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="ppe-worker-empty">
              {selectedWorkerAnalysis?.worker_count === 0
                ? 'The model reported no workers in this image/frame.'
                : 'Individual worker assessments were not saved for this record.'}
            </p>
          )}
          {!detailsLoading && !detailsError && workerCountMismatch && (
            <p className="ppe-worker-consistency-note">
              ⚠ The model reported {selectedWorkerAnalysis.worker_count} worker(s), but
              {` ${workerAssessments.length}`} individual assessment(s) were saved.
              Verify the evidence manually.
            </p>
          )}
          {hasUnclearWorkerPpe && (
            <p className="ppe-worker-unclear-note">
              Unclear means the model could not reliably assess that PPE item.
              It does not automatically mean PPE is missing.
              A photograph also cannot verify safety-footwear certification.
            </p>
          )}
        </section>
        {detailWarnings.length > 0 && (
          <div className="ppe-consistency-warning" role="alert">
            <strong>⚠ Conflicting model assessments — manual review required</strong>
            <ul>{detailWarnings.map((warning, index) => (
              <li key={`${index}-${warning}`}>{warning}</li>
            ))}</ul>
          </div>
        )}
                {/* Compact incident metadata, intentionally BELOW the frame/image reviewer */}
        <section className="incident-summary-section" aria-label="Incident information">
          <div className="incident-summary-header">
            <h3>Incident information</h3>
            <div className="incident-summary-badges">
              <span className={`severity ${selected.severity?.toLowerCase() || 'medium'}`}>
                {selected.severity}
              </span>
              <span className={`status ${selected.status?.toLowerCase() || 'open'}`}>
                {selected.status === 'Review' ? 'Under Review' : selected.status}
              </span>
            </div>
          </div>

          <div className="incident-summary-grid">
            <div className="incident-summary-group">
              <h4>Site &amp; source</h4>
              <div className="incident-summary-pair">
                <span>Location</span><strong>{selected.location}</strong>
              </div>
              <div className="incident-summary-pair">
                <span>{selected.videoName ? 'Video file' : 'Camera / source'}</span>
                <strong className="incident-summary-break">
                  {selected.videoName || (selected.camera === 'UPLOAD' ? 'Manual upload' : selected.camera)}
                </strong>
              </div>
              <div className="incident-summary-pair">
                <span>AI model</span>
                <strong className="incident-summary-break">
                  {selected.model || 'Not available'}
                </strong>
              </div>
            </div>

            <div className="incident-summary-group">
              <h4>Activity &amp; timing</h4>
              <div className="incident-summary-pair">
                <span>First detected</span>
                <strong>{incidentDisplayTime(selected.createdAt, selected.time || '—')}</strong>
              </div>
              <div className="incident-summary-pair">
                <span>Last detected</span>
                <strong>{incidentDisplayTime(selected.lastSeenAt, '—')}</strong>
              </div>
              {selected.videoName && (
                <>
                  <div className="incident-summary-pair">
                    <span>Frame range</span>
                    <strong>{videoTime(selected.firstVideoSecond)} – {videoTime(selected.lastVideoSecond)}</strong>
                  </div>
                  <div className="incident-summary-pair">
                    <span>Flagged frames</span>
                    <strong>{selected.detectionCount ?? 1}</strong>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Standalone photos have no per-frame PPE viewer, so keep their classification here. */}
          {!selected.videoName && selected.model && (
            <div className="incident-summary-photo-ppe">
              <span>PPE assessment</span>
              <span>Helmet: <strong>{reviewLabel(selected.helmetViolation)}</strong></span>
              <span>Vest: <strong>{reviewLabel(selected.vestViolation)}</strong></span>
              <span>Boots: <strong>{reviewLabel(selected.bootsViolation)}</strong></span>
            </div>
          )}
        </section>
        <section className="ppe-human-review" aria-label="Human verification and review history">
          <div className="ppe-human-review-heading">
            <div>
              <h3>Human verification</h3>
              <p>Record what a manager verified. This does not change the AI model's original prediction.</p>
            </div>
            <span className={`ppe-human-finding ${reviewData.currentFinding || 'pending'}`}>
              {humanFindingLabel(reviewData.currentFinding)}
            </span>
          </div>
          {reviewLoading ? (
            <p className="ppe-review-help">Loading saved review records…</p>
          ) : (
            <>
              <form className="ppe-review-form" onSubmit={saveHumanReview}>
                <fieldset disabled={!activeStatus(selected.status) || reviewBusy}>
                  <div className="ppe-review-form-grid">
                    <label>
                      <span>Reviewer name or initials</span>
                      <input
                        value={reviewerName}
                        onChange={(event) => setReviewerName(event.target.value)}
                        maxLength={80}
                        autoComplete="off"
                        placeholder="e.g. Safety Officer A"
                      />
                    </label>
                    <label>
                      <span>Manual finding</span>
                      <select value={manualFinding} onChange={(event) => setManualFinding(event.target.value)}>
                        <option value="">Select a finding…</option>
                        <option value="confirmed">Confirmed PPE concern</option>
                        <option value="false_alert">False alert / PPE present</option>
                        <option value="inconclusive">Inconclusive — more evidence needed</option>
                      </select>
                    </label>
                  </div>
                  <label>
                    <span>Review notes</span>
                    <textarea
                      value={reviewNotes}
                      onChange={(event) => setReviewNotes(event.target.value)}
                      maxLength={1000}
                      rows={3}
                      placeholder="Describe the evidence and why you reached this decision…"
                    />
                    <small>At least 8 characters. A new save creates another history entry.</small>
                  </label>
                  <div className="ppe-review-form-actions">
                    <button type="submit" disabled={reviewBusy}>Save review record</button>
                    {selected.status === 'Open' && (
                      <button type="button" className="outline-button" onClick={() => submitReviewAction('start')} disabled={reviewBusy}>
                        Start review
                      </button>
                    )}
                  </div>
                </fieldset>
              </form>
              <div className="ppe-review-decision-note">
                {reviewData.currentFinding === 'confirmed'
                  ? 'Confirmed PPE concern: the incident stays Under Review until corrective action is documented.'
                  : reviewData.currentFinding === 'false_alert'
                    ? 'False alert verified: you can dismiss this incident without changing the original AI result.'
                    : reviewData.currentFinding === 'inconclusive'
                      ? 'More evidence is needed. Resolution and dismissal remain unavailable.'
                      : 'Save a human finding first. The resolution and dismissal buttons will then enable for the matching decision.'}
              </div>
              {activeStatus(selected.status) && (
                <div className="ppe-review-close-actions">
                  {reviewData.currentFinding === 'confirmed' && (
                    <label>
                      <span>Corrective action taken</span>
                      <input
                        value={correctiveAction}
                        onChange={(event) => setCorrectiveAction(event.target.value)}
                        maxLength={1000}
                        placeholder="e.g. Worker was issued compliant PPE"
                      />
                    </label>
                  )}
                  <div className="ppe-review-form-actions">
                    <button
                      type="button"
                      disabled={reviewBusy || selected.status !== 'Review' || reviewData.currentFinding !== 'confirmed'}
                      onClick={() => submitReviewAction('resolve')}
                    >Mark resolved</button>
                    <button
                      type="button"
                      className="outline-button"
                      disabled={reviewBusy || selected.status !== 'Review' || reviewData.currentFinding !== 'false_alert'}
                      onClick={() => submitReviewAction('dismiss')}
                    >Dismiss false alert</button>
                  </div>
                </div>
              )}
              {['Resolved', 'Dismissed'].includes(selected.status) && (
                <div className="ppe-review-form-actions">
                  <button type="button" className="outline-button" onClick={() => submitReviewAction('reopen')} disabled={reviewBusy}>
                    Reopen for review
                  </button>
                </div>
              )}
              {selected.status === 'Archived' && (
                <p className="ppe-review-help">This incident is archived; review history is read-only.</p>
              )}
            </>
          )}
          {reviewError && <p className="ppe-review-error" role="alert">{reviewError}</p>}
          {reviewFeedback && <p className="ppe-review-feedback" role="status">{reviewFeedback}</p>}
          <div className="ppe-review-history">
            <div className="ppe-review-history-heading">
              <h3>Review history</h3>
              <span>{reviewData.history?.length || 0} entries</span>
            </div>
            {reviewData.history?.length ? (
              <ol>
                {reviewData.history.map((entry) => (
                  <li key={entry.id}>
                    <strong>{reviewEventLabel(entry)}</strong>
                    <small>{entry.reviewer} · {incidentDisplayTime(entry.createdAt)}</small>
                    {entry.notes && <p>{entry.notes}</p>}
                    {entry.fromStatus !== entry.toStatus && (
                      <small>{entry.fromStatus} → {entry.toStatus}</small>
                    )}
                  </li>
                ))}
              </ol>
            ) : <p className="ppe-review-help">No human review records have been saved yet.</p>}
          </div>
        </section>
        <p className="muted">Prototype: a VLM prediction is not a verified safety violation. Reviewer names are entered manually; there is no user authentication.</p>
      </section></div>}
      {selected && reportOpen && (
        <ReportPreview
          incident={selected}
          frames={detailFrames}
          review={reviewData}
          onClose={() => setReportOpen(false)}
        />
      )}
      {selected && zoomEvidenceUrl && (
        <div
          className="ppe-evidence-lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="Enlarged incident evidence"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setZoomEvidenceUrl('');
          }}
        >
          <button
            type="button"
            className="ppe-lightbox-close"
            onClick={() => setZoomEvidenceUrl('')}
          >
            ✕ Close
          </button>
          <EvidenceImage
            key={zoomEvidenceUrl}
            src={zoomEvidenceUrl}
            alt={`Enlarged saved evidence for incident ${selected.id}`}
          />
          <p>Saved evidence · Press Escape or Close to return to the incident.</p>
        </div>
      )}
      <footer>School project prototype · Image/video → FastAPI → configured Ollama · SQLite records · No live camera or Telegram integration</footer>
      </main>
    </div>
  );
}

function Metric({ title, value, note, symbol, tone = 'green' }) {
  return <article className={`metric-card ppe-command-metric tone-${tone}`}>
    <div className="ppe-command-metric-top"><p className="muted">{title}</p><span className="ppe-command-metric-symbol" aria-hidden="true">{symbol}</span></div>
    <strong>{value}</strong><p className="metric-note">{note}</p>
  </article>;
}

// An older SQLite record can retain a URL even after its JPEG is gone.
// Keep the image request separate from the incident/review state so a failed
// photograph never becomes a broken-image icon or changes a human finding.
function EvidenceImage({ src, alt, imageClass = '', onEnlarge }) {
  const [loadState, setLoadState] = useState('loading');
  const [attempt, setAttempt] = useState(0);
  const retryableUrl = attempt && !/^(data:|blob:)/i.test(src)
    ? `${src}${src.includes('?') ? '&' : '?'}evidence_retry=${attempt}`
    : src;

  function retryImage() {
    setLoadState('loading');
    setAttempt((count) => count + 1);
  }

  const image = (
    <img
      key={attempt}
      className={imageClass}
      src={retryableUrl}
      alt={alt}
      loading="eager"
      onLoad={() => setLoadState('ready')}
      onError={() => setLoadState('error')}
      style={{ opacity: loadState === 'ready' ? 1 : 0 }}
    />
  );

  return (
    <div className={`ppe-evidence-surface${onEnlarge ? '' : ' ppe-evidence-expanded'}`}
      aria-busy={loadState === 'loading'}>
      {onEnlarge ? (
        <button
          type="button"
          className="ppe-evidence-zoom-trigger"
          aria-label={`Enlarge ${alt.toLowerCase()}`}
          disabled={loadState !== 'ready'}
          onClick={onEnlarge}
        >
          {image}
          {loadState === 'ready' && <span className="ppe-evidence-zoom-hint">⤢ Enlarge evidence</span>}
        </button>
      ) : image}

      {loadState !== 'ready' && (
        <div className="ppe-evidence-status" role={loadState === 'error' ? 'alert' : 'status'}>
          {loadState === 'loading' ? (
            <span>Loading evidence image…</span>
          ) : (
            <>
              <strong>Evidence image could not be loaded.</strong>
              <p>The saved image may be unavailable, particularly for an older incident.</p>
              <button type="button" className="outline-button" onClick={retryImage}>
                Retry image
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function IncidentFilters({ search, onSearch, severity, onSeverity, ppe, onPpe, sort, onSort, onReset }) {
  return (
    <div className="ppe-incident-filters" role="group" aria-label="Incident search and filters">
      <label className="ppe-filter-search">
        <span>Search incidents</span>
        <input type="search" value={search} onChange={(e) => onSearch(e.target.value)} placeholder="ID, location, model or violation" />
      </label>
      <label>
        <span>Severity</span>
        <select value={severity} onChange={(e) => onSeverity(e.target.value)}>
          <option value="All">All severities</option>
          <option value="High">High</option>
          <option value="Medium">Medium</option>
        </select>
      </label>
      <label>
        <span>PPE category</span>
        <select value={ppe} onChange={(e) => onPpe(e.target.value)}>
          <option value="All">All PPE types</option>
          <option value="Helmet">Helmet</option>
          <option value="Safety vest">Safety vest</option>
          <option value="Boots">Boots</option>
          <option value="Unclear">Unclear / unverified</option>
        </select>
      </label>
      <label>
        <span>Sort by</span>
        <select value={sort} onChange={(e) => onSort(e.target.value)}>
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="severity">Highest severity</option>
        </select>
      </label>
      <button type="button" className="ppe-clear-filters" onClick={onReset}>Clear filters</button>
    </div>
  );
}

function MonitoringAnalytics() {
  const [period, setPeriod] = useState('7');
  const [location, setLocation] = useState('All locations');
  const [refreshKey, setRefreshKey] = useState(0);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    let refreshing = false;
    setAnalytics(null);
    setLoading(true);
    setError('');
    async function loadAnalytics() {
      if (refreshing || document.hidden) return;
      refreshing = true;
      try {
        const query = new URLSearchParams({ period, location });
        const result = await apiJson(`/api/analytics?${query}`);
        if (!cancelled) {
          setAnalytics(result);
          setError('');
        }
      } catch (err) {
        if (!cancelled) setError(`Monitoring analytics could not be loaded: ${err.message}`);
      } finally {
        refreshing = false;
        if (!cancelled) setLoading(false);
      }
    }
    void loadAnalytics();
    const timer = setInterval(() => { void loadAnalytics(); }, 30000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [period, location, refreshKey]);

  const summary = analytics?.summary;
  const categories = analytics?.categories || [];
  const categoryMax = Math.max(1, ...categories.map((item) => item.count));

  return (
    <div className="ppe-monitoring-page">
      <section className="ppe-monitoring-heading">
        <div>
          <p className="eyebrow">MONITORING INSIGHTS</p>
          <h2>Monitoring analytics</h2>
          <p className="muted">Identify recurring PPE concerns, compare locations and track model workload.</p>
        </div>
        <span className="ppe-analytics-badge">SQLite analysis history</span>
      </section>
      <p className="ppe-monitoring-notice">
        These are model-reported assessments, not verified safety findings or accuracy scores.
        Each analysed image or video frame counts as one attempt, even when several frames belong to one incident.
        Earlier browser incidents without saved analyses are excluded.
      </p>

      <div className="ppe-analytics-controls">
        <div>
          <span className="ppe-analytics-control-label">Reporting period</span>
          <div className="ppe-analytics-periods" role="group" aria-label="Reporting period">
            {[
              ['7', 'Last 7 days'], ['30', 'Last 30 days'], ['all', 'All available'],
            ].map(([value, label]) => (
              <button key={value} type="button" className={period === value ? 'selected' : ''}
                aria-pressed={period === value} onClick={() => setPeriod(value)}>{label}</button>
            ))}
          </div>
        </div>
        <div className="ppe-analytics-control-right">
          <label>
            <span className="ppe-analytics-control-label">Location</span>
            <select value={location} onChange={(event) => setLocation(event.target.value)}>
              <option value="All locations">All locations</option>
              {(analytics?.locations || []).filter((name) => name !== 'All locations').map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
              {location !== 'All locations' && !(analytics?.locations || []).includes(location) && (
                <option value={location}>{location}</option>
              )}
            </select>
          </label>
          <button type="button" className="ppe-analytics-reload" onClick={() => setRefreshKey((key) => key + 1)}>
            Refresh
          </button>
        </div>
      </div>

      {error && <div className="ppe-analytics-error" role="alert">{error}</div>}
      {loading && <p className="muted ppe-analytics-loading" role="status">Loading saved monitoring data…</p>}
      {!loading && analytics && (
        <>
          <div className="ppe-analytics-metrics">
            <AnalyticsMetric title="Analysed images / frames" value={summary?.total ?? 0} note="Saved model attempts in period" />
            <AnalyticsMetric title="Reported PPE violations" value={summary?.violations ?? 0} note="Model-reported; not verified" />
            <AnalyticsMetric title="Unclear / failed assessments" value={summary?.needsReview ?? 0} note="Includes unverified boots and errors" />
            <AnalyticsMetric title="Average processing time" value={summary?.avgSeconds == null ? '—' : `${summary.avgSeconds}s`} note="Seconds per saved attempt" />
          </div>

          <div className="ppe-analytics-upper-grid">
            <section className="panel ppe-analytics-panel">
              <div className="ppe-analytics-panel-head">
                <div><h2>Analysis outcomes over time</h2><p className="muted">{analytics.bucketType === 'month' ? 'Monthly' : 'Daily'} counts by model-reported outcome · Singapore time.</p></div>
                <span className="ppe-analytics-badge">Per analysis</span>
              </div>
              {summary.total > 0 ? (
                <div className="ppe-analytics-trend-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={analytics.trend} margin={{ top: 18, right: 8, left: -18, bottom: 6 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={12} interval="preserveStartEnd" />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                      <Tooltip labelFormatter={(_, payload) => payload?.[0]?.payload?.bucket || ''} />
                      <Bar dataKey="compliant" stackId="outcomes" name="Compliant" fill="#52af83" />
                      <Bar dataKey="violation" stackId="outcomes" name="Violation" fill="#ef806f" />
                      <Bar dataKey="unclear" stackId="outcomes" name="Unclear / unverified" fill="#e9b55d" />
                      <Bar dataKey="other" stackId="outcomes" name="No workers / error" fill="#95abbc" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : <p className="muted ppe-analytics-empty">No saved analyses match this period and location.</p>}
              <div className="ppe-analytics-legend">
                <span><i className="compliant" /> Compliant</span>
                <span><i className="violation" /> Violation</span>
                <span><i className="unclear" /> Unclear / unverified</span>
                <span><i className="other" /> No workers / error</span>
              </div>
            </section>

            <section className="panel ppe-analytics-panel">
              <div className="ppe-analytics-panel-head">
                <div><h2>PPE concern breakdown</h2><p className="muted">Reported missing PPE or ambiguous assessments.</p></div>
                <span className="ppe-analytics-badge">Categories overlap</span>
              </div>
              <div className="ppe-analytics-category-list">
                {categories.map((item) => (
                  <div className="ppe-analytics-category" key={item.name}>
                    <div><span>{item.name}</span><strong>{item.count}</strong></div>
                    <div className="ppe-analytics-category-track">
                      <span style={{ width: `${100 * item.count / categoryMax}%` }} />
                    </div>
                  </div>
                ))}
              </div>
              <p className="ppe-analytics-explainer">
                One analysis can flag more than one PPE category. Category totals may exceed the number of violation responses.
              </p>
            </section>
          </div>

          <div className="ppe-analytics-lower-grid">
            <section className="panel ppe-analytics-panel">
              <div className="ppe-analytics-panel-head">
                <div><h2>Location comparison</h2><p className="muted">Reported violations as a share of saved analysis attempts.</p></div>
              </div>
              <div className="ppe-analytics-table-wrap">
                <table><thead><tr><th>Location</th><th>Analyses</th><th>Violations</th><th>Violation rate</th></tr></thead><tbody>
                  {analytics.locationComparison.map((row) => (
                    <tr key={row.location}><td><strong>{row.location}</strong></td><td>{row.total}</td><td>{row.violations}</td>
                      <td><span className="ppe-analytics-rate"><i><span style={{ width: `${row.violationRate}%` }} /></i>{row.violationRate}%</span></td></tr>
                  ))}
                  {analytics.locationComparison.length === 0 && <tr><td colSpan="4">No location data for this selection.</td></tr>}
                </tbody></table>
              </div>
            </section>
            <section className="panel ppe-analytics-panel">
              <div className="ppe-analytics-panel-head">
                <div><h2>Model workload &amp; speed</h2><p className="muted">Activity and processing time, not model accuracy.</p></div>
              </div>
              <div className="ppe-analytics-table-wrap">
                <table><thead><tr><th>Model</th><th>Analyses</th><th>Avg. seconds</th><th>Needs review</th></tr></thead><tbody>
                  {analytics.modelComparison.map((row) => (
                    <tr key={row.model}><td><strong>{row.model}</strong></td><td>{row.total}</td>
                      <td>{row.avgSeconds == null ? '—' : `${row.avgSeconds}s`}</td><td>{row.needsReview}</td></tr>
                  ))}
                  {analytics.modelComparison.length === 0 && <tr><td colSpan="4">No model data for this selection.</td></tr>}
                </tbody></table>
              </div>
            </section>
          </div>
          <p className="muted ppe-analytics-disclaimer">PPE trends are based on saved AI assessments. Verify individual incidents using the original evidence before taking safety action.</p>
        </>
      )}
    </div>
  );
}

function AnalyticsMetric({ title, value, note }) {
  return <article className="ppe-analytics-metric"><p>{title}</p><strong>{value}</strong><small>{note}</small></article>;
}
export default App;
