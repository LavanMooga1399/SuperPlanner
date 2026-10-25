"""Units of measure (M1-DESIGN 3.2)."""

import pytest

from superplanner.mfg.units import UOM_CODES, UnitMismatch, convert, dimension, is_count, normalize_uom


def test_codes_in_table_order():
    assert UOM_CODES == ("EA", "M", "CM", "MM", "KG", "G", "L", "ML", "M2")


@pytest.mark.parametrize("text,code", [("pcs", "EA"), (" Nos. ", "EA"), ("each", "EA"), ("mtr", "M"),
                                       ("Metres", "M"), ("mm", "MM"), ("kgs", "KG"), ("gram", "G"),
                                       ("Ltr", "L"), ("ml.", "ML"), ("sq.m", "M2"), ("SQM", "M2")])
def test_aliases(text, code):
    assert normalize_uom(text) == code


def test_unknown_alias():
    assert normalize_uom("barrel") is None


def test_conversion_and_dimensions():
    assert convert(1500, "MM", "M") == pytest.approx(1.5)
    assert convert(2, "L", "ML") == pytest.approx(2000)
    assert convert(3, "EA", "EA") == 3
    assert dimension("CM") == "length" and is_count("EA") and not is_count("KG")


def test_mismatch_raises():
    with pytest.raises(UnitMismatch):
        convert(1, "M", "EA")
    with pytest.raises(ValueError):
        dimension("XX")
