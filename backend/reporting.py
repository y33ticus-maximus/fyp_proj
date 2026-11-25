"""Read-only PPE summary-report selection and PDF generation.

Only JPEGs previously saved by this backend can enter a report. A video's
sampled frames are observations, never proof of unique workers or accuracy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import re
from xml.sax.saxutils import escape

from PIL import Image as PILImage

SGT = timezone(timedelta(hours=8))
EVIDENCE_PATTERN = re.compile(r'^/api/evidence/([a-f0-9]{32}\.jpg)$')
PPE_FIELDS = ('helmet_violation', 'vest_violation', 'boots_violation')


def saved_evidence_path(url: str | None, evidence_dir: Path) -> Path | None:
    """Reject external URLs, untrusted paths, and old transient browser blobs."""
    matched = EVIDENCE_PATTERN.fullmatch(url or '')
    if not matched:
        return None
    path = Path(evidence_dir) / matched.group(1)
    return path if path.is_file() else None


def available_evidence_ids(frames: list[dict], evidence_dir: Path) -> list[int]:
    return [int(frame['id']) for frame in frames
            if saved_evidence_path(frame.get('evidence_url'), evidence_dir)]


def recommend_summary_frames(frames: list[dict], evidence_dir: Path,
                             limit: int = 6) -> list[int]:
    """Choose varied saved evidence; prioritise definite, multi-PPE concerns.

    This is deterministic selection by saved status and timestamp, not image
    similarity detection or a claim about severity/ground-truth accuracy.
    """
    candidates = [f for f in frames if saved_evidence_path(f.get('evidence_url'), evidence_dir)]
    if not candidates or limit <= 0:
        return []

    def seconds(frame):
        value = frame.get('video_seconds')
        return float(value) if value is not None else 0.0

    def yes_items(frame):
        return frozenset(key for key in PPE_FIELDS if frame.get(key) == 'yes')

    def unclear_items(frame):
        return frozenset(key for key in PPE_FIELDS if frame.get(key) == 'unclear')

    def rank(frame):
        yes, unclear = yes_items(frame), unclear_items(frame)
        return (-bool(yes), -len(yes), -bool(unclear), -len(unclear), seconds(frame), frame['id'])

    ranked = sorted(candidates, key=rank)
    chosen: list[dict] = []
    chosen_ids: set[int] = set()

    def add(frame):
        if frame is not None and frame['id'] not in chosen_ids and len(chosen) < limit:
            chosen.append(frame)
            chosen_ids.add(frame['id'])

    # Different reported missing-PPE combinations should be represented.
    seen_patterns: set[frozenset] = set()
    for frame in ranked:
        pattern = yes_items(frame)
        if pattern and pattern not in seen_patterns:
            add(frame)
            seen_patterns.add(pattern)

    # Include at least one visually unclear assessment when there is room.
    add(next((f for f in ranked if unclear_items(f) and f['id'] not in chosen_ids), None))

    # A compliant frame gives context, but never takes precedence over new PPE concerns.
    if len(chosen) < limit:
        add(next((f for f in ranked if f.get('overall_status') == 'compliant'), None))

    # Fill remaining slots with spaced frames to avoid repeated adjacent samples.
    remaining = [f for f in ranked if f['id'] not in chosen_ids]
    while len(chosen) < limit and remaining:
        def spacing_score(frame):
            separation = min((abs(seconds(frame) - seconds(old)) for old in chosen),
                             default=float('inf'))
            return (int(bool(yes_items(frame))), len(yes_items(frame)),
                    min(separation, 120), -seconds(frame), -int(frame['id']))
        best = max(remaining, key=spacing_score)
        add(best)
        remaining.remove(best)

    return [int(f['id']) for f in sorted(chosen, key=lambda f: (seconds(f), f['id']))]


def _printable(value, fallback='Not recorded', limit=500):
    if value is None or str(value).strip() == '':
        return fallback
    # Built-in PDF fonts support Latin characters but not emoji/CJK glyphs.
    text = str(value).strip()[:limit].encode('latin-1', 'replace').decode('latin-1')
    return escape(text).replace('\n', '<br/>')


def _sg_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(SGT).strftime('%d %b %Y, %I:%M %p SGT')
    except (TypeError, ValueError):
        return 'Not recorded'


def _video_time(value):
    seconds = max(0, int(float(value or 0)))
    return f'{seconds // 3600:02}:{(seconds // 60) % 60:02}:{seconds % 60:02}'


def _flag(value):
    return {'yes': 'Reported missing', 'no': 'No reported violation',
            'unclear': 'Unclear'}.get(value, 'Not recorded')


def render_summary_pdf(incident: dict, frames: list[dict], review: dict | None,
                       selected_ids: list[int], evidence_dir: Path) -> bytes:
    """Generate a concise, printable A4 summary without mutating SQLite."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate,
                                   Spacer, Table, TableStyle)

    navy = colors.HexColor('#122948')
    green = colors.HexColor('#16764e')
    muted = colors.HexColor('#5c7087')
    line = colors.HexColor('#dce6ef')
    light = colors.HexColor('#f3f7fa')
    ink = colors.HexColor('#1c2b3e')

    base = getSampleStyleSheet()
    styles = {
        'brand': ParagraphStyle('PPEBrand', parent=base['Normal'], fontName='Helvetica-Bold',
                                fontSize=9, leading=13, textColor=green),
        'title': ParagraphStyle('PPETitle', parent=base['Heading1'], fontName='Helvetica-Bold',
                                fontSize=22, leading=27, textColor=navy, spaceAfter=9),
        'section': ParagraphStyle('PPESection', parent=base['Heading2'], fontName='Helvetica-Bold',
                                  fontSize=12, leading=16, textColor=navy, spaceBefore=13, spaceAfter=7),
        'body': ParagraphStyle('PPEBody', parent=base['Normal'], fontName='Helvetica',
                               fontSize=9, leading=13.5, textColor=ink),
        'small': ParagraphStyle('PPESmall', parent=base['Normal'], fontName='Helvetica',
                                fontSize=8, leading=11, textColor=muted),
        'label': ParagraphStyle('PPELabel', parent=base['Normal'], fontName='Helvetica-Bold',
                                fontSize=8, leading=11, textColor=muted),
        'center': ParagraphStyle('PPECenter', parent=base['Normal'], alignment=TA_CENTER,
                                 fontSize=8, leading=11, textColor=muted),
    }

    def p(text, style='body'):
        return Paragraph(text, styles[style])

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=42, rightMargin=42,
                            topMargin=41, bottomMargin=49, title=f'PPE Incident {incident["id"]} Summary',
                            author='PPE Safety Manager')
    story = [p('SAFETY MONITORING  /  INCIDENT DOCUMENTATION', 'brand'), Spacer(1, 4),
             p('PPE Incident Summary', 'title')]

    status = _printable(incident.get('status'))
    source = 'Video upload' if incident.get('video_name') else 'Image upload'
    intro = Table([
        [p(f'<b>Incident #{incident["id"]}</b>'), p(f'<b>Status: {status}</b>')],
        [p(f'Source: {source}', 'small'), p(f'Severity label: {_printable(incident.get("severity"))}', 'small')],
    ], colWidths=[255, 252])
    intro.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), light),
                               ('BOX', (0, 0), (-1, -1), .6, line),
                               ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('LEFTPADDING', (0, 0), (-1, -1), 12),
                               ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                               ('TOPPADDING', (0, 0), (-1, -1), 7),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    story.extend([intro, Spacer(1, 9)])

    meta = [
        ('Location', incident.get('location'), 'Model', incident.get('model')),
        ('Source file', incident.get('video_name') or incident.get('camera'),
         'First detected', _sg_time(incident.get('created_at'))),
        ('Last detected', _sg_time(incident.get('last_seen_at')),
         'Saved analyses', str(len(frames)) if frames else 'No individual analyses saved'),
    ]
    metadata = Table([
        [p(f'<b>{left}</b><br/>{_printable(lv)}', 'body'),
         p(f'<b>{right}</b><br/>{_printable(rv)}', 'body')]
        for left, lv, right, rv in meta
    ], colWidths=[253.5, 253.5])
    metadata.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .4, line),
                                  ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                  ('LEFTPADDING', (0, 0), (-1, -1), 10),
                                  ('TOPPADDING', (0, 0), (-1, -1), 8),
                                  ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story.extend([metadata, p('AI-reported PPE findings', 'section')])
    ppe = Table([
        [p('Helmet', 'label'), p('Safety vest', 'label'), p('Boots', 'label')],
        [p(_flag(incident.get('helmet_violation'))),
         p(_flag(incident.get('vest_violation'))),
         p(_flag(incident.get('boots_violation')))],
    ], colWidths=[169, 169, 169])
    ppe.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), light),
                             ('GRID', (0, 0), (-1, -1), .4, line),
                             ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                             ('LEFTPADDING', (0, 0), (-1, -1), 9),
                             ('TOPPADDING', (0, 0), (-1, -1), 7),
                             ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
    story.extend([ppe, Spacer(1, 6),
                  p('These are model-reported assessments, not verified safety findings or model accuracy scores.', 'small')])

    history = (review or {}).get('history') or []
    current = (review or {}).get('currentFinding')
    finding = {'confirmed': 'Confirmed PPE concern', 'false_alert': 'False alert / PPE present',
               'inconclusive': 'Inconclusive - more evidence required'}.get(current, 'No current human finding')
    latest_review = next((event for event in history if event.get('action') == 'review'), None)
    latest_resolution = next((event for event in history if event.get('action') == 'resolve'), None)
    story.append(p('Human verification', 'section'))
    story.append(p(f'<b>Current finding:</b> {_printable(finding)}'))
    if latest_review and current:
        story.append(p(f'<b>Reviewed by:</b> {_printable(latest_review.get("reviewer"))} '
                       f'({_sg_time(latest_review.get("createdAt"))})'))
        story.append(p(f'<b>Reviewer notes:</b> {_printable(latest_review.get("notes"), limit=1000)}'))
    if latest_resolution:
        story.append(p(f'<b>Corrective action:</b> {_printable(latest_resolution.get("notes"), limit=1000)}'))
    story.append(Spacer(1, 6))
    if incident.get('video_name'):
        story.append(p('Video reports show selected saved frames, not the playable source video. '
                       'Repeated frames can show the same person.', 'small'))
    story.append(p('AI findings are unverified. Appearance alone cannot establish certified safety footwear.', 'small'))

    indexed = {int(f['id']): f for f in frames}
    selected_frames = [indexed[i] for i in selected_ids if i in indexed]
    selected_frames.sort(key=lambda f: (float(f.get('video_seconds') or 0), f['id']))
    story.append(p(f'Selected evidence ({len(selected_frames)} frame(s))', 'section'))
    if not selected_frames:
        story.append(p('No saved evidence frames were selected or available for this incident.', 'small'))

    for idx, frame in enumerate(selected_frames, 1):
        path = saved_evidence_path(frame.get('evidence_url'), evidence_dir)
        picture = p('Image file is no longer available.', 'small')
        if path:
            try:
                with PILImage.open(path) as picture_file:
                    width, height = picture_file.size
                    picture_file.verify()
                width_scale = min(209 / width, 110 / height)
                picture = Image(str(path), width=width * width_scale,
                                height=height * width_scale)
            except (OSError, ValueError, ZeroDivisionError):
                picture = p('Image file could not be read.', 'small')

        heading = (f'Frame {idx} - {_video_time(frame.get("video_seconds"))}'
                   if incident.get('video_name') else 'Saved photograph')
        detail = [p(f'<b>{_printable(heading)}</b>'),
                  p(f'<b>Model outcome:</b> {_printable(frame.get("overall_status"))}'),
                  p(f'Helmet: {_flag(frame.get("helmet_violation"))}', 'small'),
                  p(f'Vest: {_flag(frame.get("vest_violation"))}', 'small'),
                  p(f'Boots: {_flag(frame.get("boots_violation"))}', 'small')]
        workers = frame.get('workers') or []
        if workers:
            detail.append(p(f'Worker descriptions saved: {len(workers)}', 'small'))
        frame_row = Table([[picture, detail]], colWidths=[223, 284])
        frame_row.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), .5, line),
                                       ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                                       ('BACKGROUND', (0, 0), (-1, -1), light),
                                       ('LEFTPADDING', (0, 0), (-1, -1), 9),
                                       ('TOPPADDING', (0, 0), (-1, -1), 9),
                                       ('BOTTOMPADDING', (0, 0), (-1, -1), 9)]))
        story.extend([frame_row, Spacer(1, 9)])

    def page_footer(canvas, doc_obj):
        canvas.setStrokeColor(line)
        canvas.line(42, 34, A4[0] - 42, 34)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(muted)
        canvas.drawString(42, 23, f'PPE Incident #{incident["id"]}  |  Generated {_sg_time(datetime.now(timezone.utc).isoformat())}')
        canvas.drawRightString(A4[0] - 42, 23, f'Page {doc_obj.page}')

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return buffer.getvalue()
