"""Fictional CV documents generated on the fly (no real personal data)."""

from __future__ import annotations

import io

SAMPLE_CV_HTML = """
<html><head><meta charset="utf-8"></head><body style="font-family: DejaVu Sans">
<h1>Anna Berger</h1>
<p>Vienna, Austria · anna.berger@example.com · +43 660 1234567</p>
<p><a href="https://www.linkedin.com/in/anna-berger-example">LinkedIn</a> ·
<a href="https://portfolio.example.com/anna">Portfolio</a></p>
<h2>Summary</h2>
<p>Video editor and content creator with experience producing short-form social media videos.</p>
<h2>Experience</h2>
<p>Content Creator | Bright Media GmbH 03/2022 – present</p>
<ul><li>Edited short-form videos for Instagram and TikTok</li>
<li>Planned weekly content calendar</li></ul>
<p>Junior Video Editor | Studio Nord 01/2020 – 02/2022</p>
<ul><li>Cut and colour-graded promotional clips</li></ul>
<h2>Education</h2>
<p>University of Applied Arts Vienna, BA Media Design 2016 – 2019</p>
<h2>Skills</h2>
<p>CapCut, Adobe Premiere Pro, DaVinci Resolve, Storytelling</p>
<h2>Languages</h2>
<p>English – C1</p><p>German – A2</p><p>Ukrainian – Native</p>
</body></html>
"""


def make_sample_pdf() -> bytes:
    from weasyprint import HTML

    return HTML(string=SAMPLE_CV_HTML).write_pdf()


def make_sample_docx() -> bytes:
    import docx

    document = docx.Document()
    document.sections[0].header.paragraphs[0].text = "Oleh Kovalenko · oleh.k@example.org · +49 151 2345678"
    document.add_heading("Oleh Kovalenko", 0)
    document.add_paragraph("Berlin, Germany")
    document.add_heading("Berufserfahrung", 1)
    document.add_paragraph("Logistics Coordinator | Spedition Muster GmbH 05/2021 – heute")
    document.add_paragraph("• Coordinated FTL shipments across EU countries")
    document.add_heading("Ausbildung", 1)
    document.add_paragraph("Kyiv National Economic University, Bachelor Logistics 2014 – 2018")
    document.add_heading("Kenntnisse", 1)
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "SAP"
    table.rows[0].cells[1].text = "Excel"
    document.add_heading("Sprachen", 1)
    document.add_paragraph("Deutsch – B2")
    document.add_paragraph("Englisch – B2")
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
