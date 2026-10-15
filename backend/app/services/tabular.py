# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Read uploaded spreadsheets (.xlsx or .csv) into rows of text, and build the
blank templates admins download."""

import csv
import io
from datetime import date, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000


class TableError(Exception):
    pass


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))  # Excel stores 2026 / 12345 as 2026.0
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M") if (v.hour or v.minute) else v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def read_table(data: bytes, filename: str) -> list[list[str]]:
    """Rows of the first sheet (or the CSV), header first, as stripped strings."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise TableError(f"file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not data:
        raise TableError("the file is empty")
    name = filename.lower()
    if name.endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise TableError("the CSV isn't UTF-8 text; save it from Excel as .xlsx instead")
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
    elif name.endswith((".xlsx", ".xlsm")):
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise TableError("couldn't read the file as an Excel workbook (.xlsx)")
        ws = wb.worksheets[0]
        rows = [[_text(v) for v in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        raise TableError("upload an Excel file (.xlsx) or a .csv")
    while rows and not any(rows[-1]):
        rows.pop()
    if len(rows) > MAX_ROWS + 1:
        raise TableError(f"too many rows (at most {MAX_ROWS:,})")
    return rows


def template(title: str, header: list[str], examples: list[list[str]], notes: list[str]) -> bytes:
    """A workbook with the header row (bold), example rows and a Notes sheet."""
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2563EB")
    for row in examples:
        ws.append(row)
    for i, h in enumerate(header, start=1):
        width = max(len(h), *(len(r[i - 1]) for r in examples)) if examples else len(h)
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 4, 12), 48)
    ws.freeze_panes = "A2"
    notes_ws = wb.create_sheet("Notes")
    for line in notes:
        notes_ws.append([line])
    notes_ws.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
