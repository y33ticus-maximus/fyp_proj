"""Safely compact and move PPE incident metadata below the frame reviewer.

Run from the project root (containing my-app/src/App.jsx) or from my-app/:
    py -3.12 apply_compact_incident_details.py

This patches ONLY the existing incident metadata block, preserving unrelated
changes such as cross-device polling. Each affected file is backed up.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys

APP_MARKER = '<dl className="detail-grid">'
FOLLOWING_MARKER = '<p className="muted">This is a prototype.'
CSS_MARKER = '/* PPE INCIDENT COMPACT SUMMARY V1 */'

HELPER = '''function incidentDisplayTime(value, fallback = "—") {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat('en-SG', {
    timeZone: 'Asia/Singapore',
    day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(date);
}

'''

SUMMARY = '''        {/* Compact incident metadata, intentionally BELOW the frame/image reviewer */}
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
'''

CSS = r'''
/* PPE INCIDENT COMPACT SUMMARY V1 */
.detail-modal .incident-summary-section {
  margin-top: 20px;
  padding: 15px;
  border-radius: 12px;
  border: 1px solid #dce6ef;
  background: #f8fafc;
}
.detail-modal .incident-summary-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 9px;
  margin-bottom: 12px;
}
.detail-modal .incident-summary-header h3 {
  font-size: 15px;
  margin: 0;
}
.detail-modal .incident-summary-badges {
  display: flex;
  gap: 7px;
  align-items: center;
  flex-wrap: wrap;
}
.detail-modal .incident-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.detail-modal .incident-summary-group {
  min-width: 0;
  padding: 12px 13px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
}
.detail-modal .incident-summary-group h4 {
  margin: 0 0 10px;
  color: #64748b;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .045em;
  text-transform: uppercase;
}
.detail-modal .incident-summary-pair {
  display: grid;
  grid-template-columns: 106px minmax(0, 1fr);
  align-items: baseline;
  column-gap: 10px;
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.4;
}
.detail-modal .incident-summary-pair > span {
  color: #64748b;
}
.detail-modal .incident-summary-pair strong {
  min-width: 0;
  font-size: 12px;
  font-weight: 650;
  color: inherit;
}
.detail-modal .incident-summary-break {
  overflow-wrap: anywhere;
}
.detail-modal .incident-summary-photo-ppe {
  display: flex;
  gap: 8px 16px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 11px;
  border-top: 1px solid #e2e8f0;
  font-size: 12px;
}
.detail-modal .incident-summary-photo-ppe > span:first-child {
  color: #64748b;
  font-weight: 750;
}
.dark-theme .detail-modal .incident-summary-section {
  background: #14243a;
  border-color: #36516e;
}
.dark-theme .detail-modal .incident-summary-group {
  background: #192b40;
  border-color: #36516e;
}
.dark-theme .detail-modal .incident-summary-pair > span,
.dark-theme .detail-modal .incident-summary-group h4,
.dark-theme .detail-modal .incident-summary-photo-ppe > span:first-child {
  color: #b4c8df;
}
.dark-theme .detail-modal .incident-summary-photo-ppe {
  border-color: #36516e;
}
@media (max-width: 700px) {
  .detail-modal .incident-summary-grid {
    grid-template-columns: 1fr;
  }
  .detail-modal .incident-summary-pair {
    grid-template-columns: 100px minmax(0, 1fr);
  }
  .detail-modal .incident-summary-section {
    padding: 11px;
  }
}
'''


def find_files():
    paths = [Path('my-app/src'), Path('src')]
    for folder in paths:
        if (folder / 'App.jsx').is_file() and (folder / 'App.css').is_file():
            return folder / 'App.jsx', folder / 'App.css'
    raise RuntimeError('Cannot locate App.jsx and App.css. Run this script from your project root or my-app folder.')


def backup(path: Path, suffix: str) -> Path:
    target = path.with_name(f'{path.name}.backup-{suffix}')
    shutil.copy2(path, target)
    return target


def patch_jsx(source: str) -> str:
    if 'incident-summary-section' in source:
        raise RuntimeError('Compact incident details appear to be installed already; no changes made.')
    if source.count(APP_MARKER) != 1:
        raise RuntimeError('Expected old incident metadata grid exactly once; no changes made.')
    if source.count(FOLLOWING_MARKER) != 1:
        raise RuntimeError('Could not identify end of frame reviewer; no changes made.')
    if 'incident-frame-review' not in source:
        raise RuntimeError('Video frame reviewer is missing; no changes made.')

    start = source.index(APP_MARKER)
    end = source.find('</dl>', start)
    if end == -1:
        raise RuntimeError('The original metadata grid has no closing </dl>; no changes made.')
    end += len('</dl>')
    # Preserve any automatic polling or other functions elsewhere in App.jsx.
    source = source[:start] + source[end:]
    anchor = source.index(FOLLOWING_MARKER)
    source = source[:anchor] + SUMMARY + source[anchor:]
    if 'function incidentDisplayTime(' not in source:
        target = 'function App() {'
        if target not in source:
            raise RuntimeError('Could not locate App function; no changes made.')
        source = source.replace(target, HELPER + target, 1)
    return source


def main():
    jsx_path, css_path = find_files()
    jsx_source = jsx_path.read_text(encoding='utf-8')
    css_source = css_path.read_text(encoding='utf-8')

    new_jsx = patch_jsx(jsx_source)
    new_css = css_source if CSS_MARKER in css_source else css_source.rstrip() + '\n' + CSS + '\n'
    if new_jsx.count('incident-summary-section') != 1:
        raise RuntimeError('Verification failed: summary count is not one. No files changed.')

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backups = [backup(jsx_path, timestamp), backup(css_path, timestamp)]
    try:
        jsx_path.write_text(new_jsx, encoding='utf-8')
        css_path.write_text(new_css, encoding='utf-8')
    except Exception:
        shutil.copy2(backups[0], jsx_path)
        shutil.copy2(backups[1], css_path)
        raise

    print('Done: incident information is now compact and below the frame/image review.')
    print('Updated:', jsx_path, 'and', css_path)
    print('Backups:', *backups, sep='\n  ')
    print('All existing API, analysis, incident, and dashboard refresh logic is preserved.')
    print('Run npm.cmd run build from the my-app folder, then inspect an incident.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Not updated:', exc, file=sys.stderr)
        sys.exit(1)
