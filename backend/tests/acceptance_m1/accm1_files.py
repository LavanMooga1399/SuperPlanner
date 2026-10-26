"""Hand-built hostile import files for the WP-D adversarial checks (raw zip/XML, no product code)."""

from __future__ import annotations

import io
import zipfile

CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/xl/workbook.xml" '
      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      '<Override PartName="/xl/worksheets/sheet1.xml" '
      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
      '</Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="xl/workbook.xml"/></Relationships>')
WB = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
      '<sheets><sheet name="items" sheetId="1" r:id="rId1"/></sheets></workbook>')
WB_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
           'worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
SHEET_HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
SHEET_TAIL = '</sheetData></worksheet>'

BILLION_LAUGHS_DTD = ('<!DOCTYPE lolz [<!ENTITY lol "lol">'
                      + "".join(f'<!ENTITY lol{i} "{("&lol%s;" % ("" if i == 1 else i - 1)) * 10}">'
                                for i in range(1, 10))
                      + ']>')
XXE_DTD = '<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'


def istr(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def num(ref: str, v: str) -> str:
    return f'<c r="{ref}"><v>{v}</v></c>'


HEADER_ROW = f'<row r="1">{istr("A1", "part_number")}{istr("B1", "make_buy")}{istr("C1", "lead_time_days")}</row>'


def items_rows(*rows: tuple[str, str, str]) -> str:
    out = []
    for i, (pn, mb, lt) in enumerate(rows, start=2):
        out.append(f'<row r="{i}">{istr(f"A{i}", pn)}{istr(f"B{i}", mb)}{lt.replace("@", str(i))}</row>')
    return "".join(out)


def xlsx(sheet_xml: str, *, workbook: str = WB, content_types: str = CT, extra: dict[str, bytes] | None = None,
         compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", RELS)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", WB_RELS)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


def sheet(rows_xml: str, head: str = SHEET_HEAD) -> str:
    return head + rows_xml + SHEET_TAIL


def zip_of(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in members.items():
            z.writestr(k, v)
    return buf.getvalue()


def lie_about_size(data: bytes, member: str, declared: int) -> bytes:
    """Rewrite the uncompressed size of `member` in the local header and the central directory."""
    import struct

    b = bytearray(data)
    name = member.encode()
    # local file header: sig PK\x03\x04, uncompressed size at offset 22
    i = b.find(b"PK\x03\x04" + b"")
    while i != -1:
        n_len = struct.unpack_from("<H", b, i + 26)[0]
        if bytes(b[i + 30:i + 30 + n_len]) == name:
            struct.pack_into("<I", b, i + 22, declared)
        i = b.find(b"PK\x03\x04", i + 4)
    j = b.find(b"PK\x01\x02")
    while j != -1:
        n_len = struct.unpack_from("<H", b, j + 28)[0]
        if bytes(b[j + 46:j + 46 + n_len]) == name:
            struct.pack_into("<I", b, j + 24, declared)
        j = b.find(b"PK\x01\x02", j + 4)
    return bytes(b)
