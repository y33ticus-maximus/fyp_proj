"""SQLite storage for PPE analyses, incidents and in-app notifications.

No model connection is required for this module. All database writes are transactional.
This is a single-user/small-prototype store, not a multi-tenant production service.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

SGT = timezone(timedelta(hours=8))
ALERT_STATES = {'violation', 'unclear'}
INCIDENT_STATUSES = {'Open', 'Review', 'Resolved', 'Dismissed', 'Archived'}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def issue_for_result(result: dict) -> tuple[str, str, str, str]:
    tokens, descriptions = [], []
    for key, token, description in (
        ('helmet_violation', 'helmet', 'Missing hard hat'),
        ('vest_violation', 'vest', 'Missing safety vest'),
        ('boots_violation', 'boots', 'Missing protective boots (visual)'),
    ):
        if result.get(key) == 'yes':
            tokens.append(token)
            descriptions.append(description)
    if not tokens:
        # The unclear incident must have a meaningful grouping key.
        unclear_parts = [key for key in ('helmet', 'vest', 'boots')
                         if result.get(f'{key}_violation') == 'unclear']
        tokens = ['review', *unclear_parts]
        descriptions = ['PPE assessment unclear']
    status = 'Review' if result['overall_status'] == 'unclear' else 'Open'
    severity = 'High' if result.get('helmet_violation') == 'yes' else 'Medium'
    return '+'.join(tokens), ' + '.join(descriptions), status, severity


class PPEStore:
    def __init__(self, path: Path, cooldown_seconds: float = 120):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.initialize()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode = WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_key TEXT NOT NULL,
                    issue TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    location TEXT NOT NULL,
                    camera TEXT NOT NULL,
                    source TEXT NOT NULL,
                    model TEXT,
                    worker_count INTEGER,
                    helmet_violation TEXT,
                    vest_violation TEXT,
                    boots_violation TEXT,
                    processing_seconds REAL,
                    evidence_url TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    detection_count INTEGER NOT NULL DEFAULT 1,
                    video_session_id TEXT,
                    video_name TEXT,
                    first_video_seconds REAL,
                    last_video_seconds REAL,
                    legacy_key TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS ix_incidents_video
                  ON incidents(video_session_id, issue_key, last_video_seconds);
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analyzed_at TEXT NOT NULL,
                    model TEXT NOT NULL,
                    overall_status TEXT NOT NULL,
                    helmet_violation TEXT,
                    vest_violation TEXT,
                    boots_violation TEXT,
                    worker_count INTEGER NOT NULL DEFAULT 0,
                    processing_seconds REAL,
                    location TEXT NOT NULL,
                    camera TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    video_session_id TEXT,
                    video_name TEXT,
                    video_seconds REAL,
                    evidence_url TEXT,
                    review_unclear_boots INTEGER NOT NULL DEFAULT 0,
                    incident_id INTEGER REFERENCES incidents(id),
                    error_text TEXT,
                    result_json TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_analyses_incident ON analyses(incident_id);
                CREATE INDEX IF NOT EXISTS ix_analyses_status_time ON analyses(overall_status, analyzed_at);
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id INTEGER NOT NULL UNIQUE REFERENCES incidents(id),
                    is_read INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
            ''')

    def save_analysis(self, result: dict, *, video_session_id: str = '',
                      video_name: str = '', video_seconds: float | None = None) -> dict:
        "Save each prediction, with at most one alert incident per uploaded video."
        # One session = one incident; each frame remains in analyses.
        now = result.get('analyzed_at') or utc_now()
        overall = result['overall_status']
        incident_id, action = None, 'none'
        session = (video_session_id or '')[:128]
        video_name = (video_name or '')[:255]
        seconds = None if video_seconds is None else float(video_seconds)
        is_alert = overall in ALERT_STATES

        with self.connect() as conn:
            # Serialize the lookup + insert to avoid duplicate notifications.
            conn.execute('BEGIN IMMEDIATE')
            previous = None
            if session:
                previous = conn.execute('''
                    SELECT * FROM incidents
                    WHERE video_session_id = ?
                    ORDER BY id ASC LIMIT 1
                ''', (session,)).fetchone()

            if is_alert and previous:
                # Union the reported concerns over the whole video: a later vest
                # report must not overwrite an earlier helmet report, for example.
                def merge_flag(old, new):
                    values = {old, new}
                    if 'yes' in values:
                        return 'yes'
                    if 'unclear' in values:
                        return 'unclear'
                    return 'no' if 'no' in values else None

                helmet = merge_flag(previous['helmet_violation'], result.get('helmet_violation'))
                vest = merge_flag(previous['vest_violation'], result.get('vest_violation'))
                boots = merge_flag(previous['boots_violation'], result.get('boots_violation'))
                aggregate = {'overall_status': 'violation' if 'yes' in (helmet, vest, boots) else 'unclear',
                             'helmet_violation': helmet, 'vest_violation': vest, 'boots_violation': boots}
                issue_key, _, next_status, severity = issue_for_result(aggregate)
                reported = [name for name, value in (('helmet', helmet), ('vest', vest), ('boots', boots))
                            if value == 'yes']
                issue = ('Video PPE concerns: ' + ', '.join(reported)) if reported else 'Video PPE assessment unclear'
                # Never undo an explicit safety-manager resolution/dismissal.
                status = previous['status'] if previous['status'] in ('Resolved', 'Dismissed', 'Archived') else next_status
                incident_id = previous['id']
                action = 'grouped'
                conn.execute('''
                    UPDATE incidents
                    SET issue_key = ?, issue = ?, status = ?, severity = ?,
                        last_seen_at = ?, detection_count = detection_count + 1,
                        first_video_seconds = CASE
                            WHEN ? IS NULL THEN first_video_seconds
                            WHEN first_video_seconds IS NULL THEN ?
                            ELSE MIN(first_video_seconds, ?) END,
                        last_video_seconds = CASE
                            WHEN ? IS NULL THEN last_video_seconds
                            WHEN last_video_seconds IS NULL THEN ?
                            ELSE MAX(last_video_seconds, ?) END,
                        evidence_url = COALESCE(?, evidence_url),
                        worker_count = ?, processing_seconds = ?, model = ?,
                        helmet_violation = ?, vest_violation = ?, boots_violation = ?
                    WHERE id = ?
                ''', (issue_key, issue, status, severity, now,
                      seconds, seconds, seconds, seconds, seconds, seconds,
                      result.get('evidence_url'), result.get('worker_count'),
                      result.get('processing_seconds'), result.get('model'),
                      helmet, vest, boots, incident_id))

            elif is_alert:
                issue_key, issue, status, severity = issue_for_result(result)
                first_second = seconds
                if session:
                    issue = ('Video PPE concerns: ' + ', '.join(
                        name for name, flag in (
                            ('helmet', result.get('helmet_violation')),
                            ('vest', result.get('vest_violation')),
                            ('boots', result.get('boots_violation')),
                        ) if flag == 'yes')
                    ) if status == 'Open' else 'Video PPE assessment unclear'
                    earliest = conn.execute('''
                        SELECT MIN(video_seconds) AS first_second FROM analyses
                        WHERE video_session_id = ?
                    ''', (session,)).fetchone()['first_second']
                    if earliest is not None:
                        first_second = min(float(earliest), seconds) if seconds is not None else float(earliest)
                cur = conn.execute('''
                    INSERT INTO incidents (
                        issue_key, issue, status, severity, location, camera, source, model,
                        worker_count, helmet_violation, vest_violation, boots_violation,
                        processing_seconds, evidence_url, created_at, last_seen_at,
                        detection_count, video_session_id, video_name,
                        first_video_seconds, last_video_seconds
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)
                ''', (issue_key, issue, status, severity,
                      result.get('location') or 'Manual upload',
                      result.get('camera') or 'UPLOAD', 'Ollama', result.get('model'),
                      result.get('worker_count'), result.get('helmet_violation'),
                      result.get('vest_violation'), result.get('boots_violation'),
                      result.get('processing_seconds'), result.get('evidence_url'),
                      now, now, session or None, video_name or None, first_second, seconds))
                incident_id = cur.lastrowid
                action = 'created'
                conn.execute('''
                    INSERT INTO notifications(incident_id, is_read, created_at)
                    VALUES (?, 0, ?)
                ''', (incident_id, now))
                if session:
                    # Link compliant/failed frames recorded before the first alert.
                    conn.execute('''
                        UPDATE analyses SET incident_id = ?
                        WHERE video_session_id = ? AND incident_id IS NULL
                    ''', (incident_id, session))

            elif previous:
                # Even non-alert frames belong to the same video summary.
                incident_id = previous['id']
                action = 'linked'
                conn.execute('''
                    UPDATE incidents SET last_seen_at = ?,
                        last_video_seconds = CASE
                            WHEN ? IS NULL THEN last_video_seconds
                            WHEN last_video_seconds IS NULL THEN ?
                            ELSE MAX(last_video_seconds, ?) END
                    WHERE id = ?
                ''', (now, seconds, seconds, seconds, incident_id))

            cur = conn.execute('''
                INSERT INTO analyses (
                    analyzed_at, model, overall_status, helmet_violation, vest_violation,
                    boots_violation, worker_count, processing_seconds, location, camera,
                    source_type, video_session_id, video_name, video_seconds, evidence_url,
                    review_unclear_boots, incident_id, error_text, result_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (now, result.get('model') or '', overall,
                  result.get('helmet_violation'), result.get('vest_violation'),
                  result.get('boots_violation'), result.get('worker_count') or 0,
                  result.get('processing_seconds'), result.get('location') or 'Manual upload',
                  result.get('camera') or 'UPLOAD', 'video_frame' if session else 'image',
                  session or None, video_name or None, seconds, result.get('evidence_url'),
                  int(bool(result.get('review_unclear_boots'))), incident_id,
                  result.get('error_text'), json.dumps(result, ensure_ascii=False)))
            analysis_id = cur.lastrowid
        return {'analysis_id': analysis_id, 'incident_id': incident_id,
                'incident_action': action}

    def save_failure(self, *, model: str, location: str, camera: str, message: str,
                     processing_seconds: float, video_session_id: str = '',
                     video_name: str = '', video_seconds: float | None = None):
        data = {
            'model': model, 'overall_status': 'error', 'location': location,
            'camera': camera, 'worker_count': 0, 'processing_seconds': processing_seconds,
            'error_text': message[:500], 'analyzed_at': utc_now(),
        }
        return self.save_analysis(data, video_session_id=video_session_id,
                                  video_name=video_name, video_seconds=video_seconds)

    def import_browser_incidents(self, client_id: str, items: list, notifications: list) -> int:
        """Idempotent migration of *real* legacy browser incidents, not simulations."""
        client_id = ''.join(c for c in client_id[:128] if c.isalnum() or c in '-_')
        if not client_id:
            return 0
        read_flags = {}
        for item in notifications[:5000]:
            if isinstance(item, dict) and 'incidentId' in item:
                read_flags[str(item['incidentId'])] = bool(item.get('read'))
        imported = 0
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for item in items[:5000]:
                if not isinstance(item, dict) or item.get('id') is None:
                    continue
                # Old real records identify the model and contain a known PPE issue.
                if not item.get('model') or not item.get('issue') or item.get('source') == 'Simulation':
                    continue
                legacy_key = f'{client_id}:{str(item["id"])[:80]}'
                if conn.execute('SELECT 1 FROM incidents WHERE legacy_key=?', (legacy_key,)).fetchone():
                    continue
                status = item.get('status', 'Open')
                if status not in INCIDENT_STATUSES:
                    status = 'Review'
                date = str(item.get('createdAt') or utc_now())[:64]
                cur = conn.execute('''
                    INSERT INTO incidents (
                        issue_key, issue, status, severity, location, camera, source, model,
                        worker_count, helmet_violation, vest_violation, boots_violation,
                        processing_seconds, evidence_url, created_at, last_seen_at,
                        detection_count, legacy_key
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
                ''', ('legacy', str(item['issue'])[:255], status,
                      'High' if item.get('severity') == 'High' else 'Medium',
                      str(item.get('location') or 'Manual upload')[:100],
                      str(item.get('camera') or 'UPLOAD')[:100],
                      str(item.get('source') or 'Ollama')[:60],
                      str(item.get('model'))[:160], item.get('workerCount'),
                      item.get('helmetViolation'), item.get('vestViolation'),
                      item.get('bootsViolation'), item.get('processingSeconds'),
                      item.get('evidenceUrl'), date, date, legacy_key))
                if str(item['id']) in read_flags:
                    conn.execute('''
                        INSERT INTO notifications(incident_id,is_read,created_at)
                        VALUES (?,?,?)
                    ''', (cur.lastrowid, int(read_flags[str(item['id'])]), date))
                imported += 1
        return imported

    def update_status(self, incident_id: int, status: str) -> bool:
        if status not in INCIDENT_STATUSES:
            raise ValueError('Invalid incident status')
        with self.connect() as conn:
            cur = conn.execute('UPDATE incidents SET status=? WHERE id=?', (status, incident_id))
            if cur.rowcount and status in ('Resolved', 'Dismissed', 'Archived'):
                conn.execute(
                    'DELETE FROM notifications WHERE incident_id=?',
                    (incident_id,)
                )
            return cur.rowcount > 0

    def delete_incident_notification(self, incident_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                'DELETE FROM notifications WHERE incident_id=?',
                (incident_id,)
            )
            return cur.rowcount > 0

    # PPE_ARCHIVE_HISTORY_V1
    def archive_incident(self, incident_id: int) -> bool:
        """Archive an active incident, retaining evidence and history."""
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            cur = conn.execute(
                "UPDATE incidents SET status='Archived' "
                "WHERE id=? AND status IN ('Open', 'Review')",
                (incident_id,)
            )
            if cur.rowcount:
                conn.execute(
                    'DELETE FROM notifications WHERE incident_id=?',
                    (incident_id,)
                )
            return cur.rowcount > 0

    def mark_notification(self, notification_id: int, is_read: bool = True) -> bool:
        with self.connect() as conn:
            cur = conn.execute('UPDATE notifications SET is_read=? WHERE id=?',
                               (int(is_read), notification_id))
            return cur.rowcount > 0

    def mark_all_read(self):
        with self.connect() as conn:
            conn.execute('UPDATE notifications SET is_read = 1 WHERE is_read = 0')

    def incident_analyses(self, incident_id: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute('''
                SELECT id, analyzed_at, overall_status, video_seconds, evidence_url,
                       model, helmet_violation, vest_violation, boots_violation
                FROM analyses WHERE incident_id = ? ORDER BY id ASC
            ''', (incident_id,)).fetchall()
        return [dict(row) for row in rows]

    def state(self) -> dict:
        with self.connect() as conn:
            incidents = conn.execute('''
                SELECT * FROM incidents ORDER BY last_seen_at DESC, id DESC
            ''').fetchall()
            notifications = conn.execute('''
                SELECT * FROM notifications ORDER BY created_at DESC, id DESC
            ''').fetchall()
            groups = conn.execute('''
                SELECT overall_status, COUNT(*) AS count,
                       COALESCE(SUM(worker_count), 0) AS workers
                FROM analyses GROUP BY overall_status
            ''').fetchall()
            daily = conn.execute('''
                SELECT date(analyzed_at, '+8 hours') AS day,
                       SUM(CASE WHEN overall_status='compliant' THEN 1 ELSE 0 END) AS good,
                       SUM(CASE WHEN overall_status='violation' THEN 1 ELSE 0 END) AS bad
                FROM analyses
                WHERE overall_status IN ('compliant','violation')
                GROUP BY date(analyzed_at, '+8 hours')
            ''').fetchall()
        counts = {row['overall_status']: row['count'] for row in groups}
        total_observations = sum(row['workers'] for row in groups if row['overall_status'] != 'error')
        compliant = counts.get('compliant', 0)
        violations = counts.get('violation', 0)
        decisive = compliant + violations
        today = datetime.now(SGT).date()
        daily_lookup = {row['day']: row for row in daily}
        trend = []
        for offset in range(6, -1, -1):
            date = today - timedelta(days=offset)
            day = daily_lookup.get(date.isoformat())
            good = int(day['good']) if day else 0
            bad = int(day['bad']) if day else 0
            trend.append({'day': date.strftime('%a'), 'date': date.isoformat(),
                          'rate': round(good * 100 / (good + bad), 1) if good + bad else None,
                          'decisive': good + bad})
        items = []
        for row in incidents:
            d = dict(row)
            date = d['created_at']
            try:
                local = datetime.fromisoformat(date.replace('Z', '+00:00')).astimezone(SGT)
                time_str = local.strftime('%H:%M')
            except (ValueError, TypeError):
                time_str = '—'
            items.append({
                'id': d['id'], 'issue': d['issue'], 'status': d['status'],
                'severity': d['severity'], 'location': d['location'], 'camera': d['camera'],
                'source': d['source'], 'model': d['model'], 'workerCount': d['worker_count'],
                'helmetViolation': d['helmet_violation'], 'vestViolation': d['vest_violation'],
                'bootsViolation': d['boots_violation'], 'processingSeconds': d['processing_seconds'],
                'evidenceUrl': d['evidence_url'], 'createdAt': d['created_at'], 'time': time_str,
                'lastSeenAt': d['last_seen_at'], 'detectionCount': d['detection_count'],
                'videoName': d['video_name'], 'firstVideoSecond': d['first_video_seconds'],
                'lastVideoSecond': d['last_video_seconds'], 'legacy': bool(d['legacy_key']),
                'confidence': None,
            })
        note = {
            'compliant': compliant, 'violations': violations,
            'unclear': counts.get('unclear', 0),
            'bootsUnverified': counts.get('boots_unverified', 0),
            'noWorkers': counts.get('no_workers', 0),
            'failed': counts.get('error', 0),
            'analyses': sum(counts.values()),
            'workerObservations': total_observations,
            'complianceRate': round(100 * compliant / decisive, 1) if decisive else None,
            'decisive': decisive,
            'incidents': len(incidents),
            'activeIncidents': sum(1 for i in incidents if i['status'] in ('Open', 'Review')),
        }
        return {
            'items': items,
            'notifications': [{
                'id': f'notification-{n["id"]}', 'incidentId': n['incident_id'],
                'read': bool(n['is_read']), 'createdAt': n['created_at'],
            } for n in notifications],
            'statistics': note, 'trend': trend,
        }
