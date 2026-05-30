"""Unit tests for ouro/tools/email_parser.py"""

import pytest

from ouro.tools.email_parser import (
    _clean,
    _extract_labeled_dates,
    _parse_all_dates,
    _parse_email_dates,
)
from ouro.tools.gmail_flight_scanner import _parse_email
import unittest.mock


# ---------------------------------------------------------------------------
# _clean
# ---------------------------------------------------------------------------

class TestClean:
    def test_strips_html_tags(self):
        assert _clean("<b>hello</b>") == " hello "

    def test_decodes_ndash(self):
        assert "&ndash;" not in _clean("a &ndash; b")
        assert "-" in _clean("a &ndash; b")

    def test_decodes_amp(self):
        assert _clean("a &amp; b") == "a & b"

    def test_decodes_nbsp(self):
        result = _clean("a&nbsp;b")
        assert "a" in result and "b" in result

    def test_collapses_whitespace(self):
        result = _clean("a   b")
        assert "  " not in result

    def test_preserves_newlines(self):
        result = _clean("line1\nline2")
        assert "\n" in result

    def test_numeric_entity(self):
        assert "-" in _clean("a &#8211; b")


# ---------------------------------------------------------------------------
# _parse_all_dates
# ---------------------------------------------------------------------------

class TestParseAllDates:
    def test_day_month_name_year(self):
        assert "2026-05-28" in _parse_all_dates("28 May 2026")

    def test_iso_format(self):
        assert "2026-05-28" in _parse_all_dates("2026-05-28")

    def test_slash_mm_dd_when_day_gt_12(self):
        # 28 > 12 → unambiguously MM/DD
        assert "2026-05-28" in _parse_all_dates("05/28/2026")

    def test_slash_dd_mm_when_first_gt_12(self):
        # 28 > 12 → DD/MM
        assert "2026-05-28" in _parse_all_dates("28/05/2026")

    def test_all_formats_same_iso(self):
        formats = ["28 May 2026", "2026-05-28", "05/28/2026", "28/05/2026"]
        for fmt in formats:
            assert "2026-05-28" in _parse_all_dates(fmt), f"failed for: {fmt}"

    def test_no_double_counting_weekday_and_plain(self):
        text = "Thu, May 28, 2026 and May 28, 2026"
        dates = _parse_all_dates(text)
        assert dates.count("2026-05-28") == 1

    def test_multiple_distinct_dates(self):
        dates = _parse_all_dates("May 28, 2026 and May 31, 2026")
        assert "2026-05-28" in dates
        assert "2026-05-31" in dates

    def test_no_dates(self):
        assert _parse_all_dates("no dates here at all") == []

    def test_month_name_day_year(self):
        assert "2026-06-05" in _parse_all_dates("June 5, 2026")

    def test_weekday_month_name(self):
        assert "2026-05-28" in _parse_all_dates("Thursday, May 28, 2026")


# ---------------------------------------------------------------------------
# _extract_labeled_dates
# ---------------------------------------------------------------------------

class TestExtractLabeledDates:
    def test_checkin_plain(self):
        result = _extract_labeled_dates("Check-In: Thursday, May 28, 2026")
        assert result["checkin"] == ["2026-05-28"]

    def test_checkout_plain(self):
        result = _extract_labeled_dates("Check-Out: Sunday, May 31, 2026")
        assert result["checkout"] == ["2026-05-31"]

    def test_departure_iso(self):
        result = _extract_labeled_dates("Departure: 2026-06-01")
        assert result["departure"] == ["2026-06-01"]

    def test_arrival_month_name(self):
        result = _extract_labeled_dates("Arrival: June 5, 2026")
        assert result["arrival"] == ["2026-06-05"]

    def test_html_th_checkin(self):
        html = "<th>Check-In:</th><th>Thursday, May 28, 2026</th>"
        cleaned = _clean(html)
        result = _extract_labeled_dates(cleaned)
        assert result["checkin"] == ["2026-05-28"]

    def test_html_td_checkout(self):
        html = "<td>Check-Out:</td><td>Sunday, May 31, 2026</td>"
        cleaned = _clean(html)
        result = _extract_labeled_dates(cleaned)
        assert result["checkout"] == ["2026-05-31"]

    def test_no_labels_returns_empty(self):
        result = _extract_labeled_dates("Thu, May 28, 2026 - Sun, May 31, 2026")
        assert result["checkin"] == []
        assert result["checkout"] == []


# ---------------------------------------------------------------------------
# _parse_email_dates — basic labeled extraction
# ---------------------------------------------------------------------------

class TestParseEmailDatesLabeled:
    def test_checkin_plain(self):
        r = _parse_email_dates("Check-In: Thursday, May 28, 2026")
        assert r["checkin"] == "2026-05-28"

    def test_checkout_plain(self):
        r = _parse_email_dates("Check-Out: Sunday, May 31, 2026")
        assert r["checkout"] == "2026-05-31"

    def test_departure_iso(self):
        r = _parse_email_dates("Departure: 2026-06-01")
        assert r["departure"] == "2026-06-01"

    def test_arrival_month_name(self):
        r = _parse_email_dates("Arrival: June 5, 2026")
        assert r["arrival"] == "2026-06-05"

    def test_source_is_body(self):
        r = _parse_email_dates("Check-In: May 28, 2026")
        assert r["source"] == "body"

    def test_no_dates(self):
        r = _parse_email_dates("No dates here.")
        assert r["checkin"] is None
        assert r["checkout"] is None
        assert r["departure"] is None
        assert r["arrival"] is None
        assert r["raw_dates"] == []

    def test_subject_ignored(self):
        r = _parse_email_dates("", subject="Check-In: May 28, 2026")
        assert r["checkin"] is None


# ---------------------------------------------------------------------------
# _parse_email_dates — HTML labeled extraction (Marriott-style)
# ---------------------------------------------------------------------------

class TestParseEmailDatesHTML:
    MARRIOTT_SNIPPET = """
        <th>Check-In:</th>
        <th>Thursday, May 28, 2026</th>
        <td>Check-Out:</td>
        <td>Sunday, May 31, 2026</td>
        <td>12:00 PM</td>
    """

    def test_marriott_checkin(self):
        r = _parse_email_dates(self.MARRIOTT_SNIPPET)
        assert r["checkin"] == "2026-05-28"

    def test_marriott_checkout(self):
        r = _parse_email_dates(self.MARRIOTT_SNIPPET)
        assert r["checkout"] == "2026-05-31"

    def test_marriott_source(self):
        r = _parse_email_dates(self.MARRIOTT_SNIPPET)
        assert r["source"] == "body"

    def test_marriott_no_inferred_warning(self):
        r = _parse_email_dates(self.MARRIOTT_SNIPPET)
        inferred = [w for w in r["warnings"] if "inferred" in w.lower()]
        assert inferred == []


# ---------------------------------------------------------------------------
# _parse_email_dates — date range inference
# ---------------------------------------------------------------------------

class TestParseEmailDatesRanges:
    def test_range_with_weekday(self):
        r = _parse_email_dates("Thu, May 28, 2026 – Sun, May 31, 2026")
        assert r["checkin"] == "2026-05-28"
        assert r["checkout"] == "2026-05-31"

    def test_range_inferred_warning(self):
        r = _parse_email_dates("Thu, May 28, 2026 – Sun, May 31, 2026")
        assert any("inferred" in w.lower() for w in r["warnings"])

    def test_range_cross_month(self):
        r = _parse_email_dates("May 28 – Jun 1, 2026")
        assert r["checkin"] == "2026-05-28"
        assert r["checkout"] == "2026-06-01"

    def test_range_html_entity_ndash(self):
        r = _parse_email_dates("Thu, May 28, 2026 &ndash; Sun, May 31, 2026")
        assert r["checkin"] == "2026-05-28"
        assert r["checkout"] == "2026-05-31"


# ---------------------------------------------------------------------------
# _parse_email_dates — labeled beats range
# ---------------------------------------------------------------------------

class TestLabeledBeatsRange:
    def test_labeled_wins_over_range(self):
        body = (
            "Check-In: Thursday, May 28, 2026\n"
            "Check-Out: Sunday, May 31, 2026\n"
            "Thu, May 28, 2026 – Sun, May 31, 2026"
        )
        r = _parse_email_dates(body)
        assert r["checkin"] == "2026-05-28"
        assert r["checkout"] == "2026-05-31"

    def test_labeled_no_inferred_warning(self):
        body = (
            "Check-In: Thursday, May 28, 2026\n"
            "Check-Out: Sunday, May 31, 2026\n"
            "Thu, May 28, 2026 – Sun, May 31, 2026"
        )
        r = _parse_email_dates(body)
        inferred = [w for w in r["warnings"] if "inferred" in w.lower()]
        assert inferred == []


# ---------------------------------------------------------------------------
# _parse_email_dates — multiple check-in warning
# ---------------------------------------------------------------------------

class TestMultipleCheckinWarning:
    def test_two_different_checkins_warns(self):
        body = "Check-In: May 28, 2026\nCheck-In: May 29, 2026"
        r = _parse_email_dates(body)
        assert r["checkin"] == "2026-05-28"
        assert any("multiple" in w.lower() and "checkin" in w.lower() for w in r["warnings"])

    def test_two_same_checkins_no_warn(self):
        body = "Check-In: May 28, 2026\nCheck-In: May 28, 2026"
        r = _parse_email_dates(body)
        assert r["checkin"] == "2026-05-28"
        assert not any("multiple" in w.lower() for w in r["warnings"])


# ---------------------------------------------------------------------------
# _parse_email_dates — raw_dates deduplication
# ---------------------------------------------------------------------------

class TestRawDates:
    def test_raw_dates_deduped(self):
        r = _parse_email_dates("Thu, May 28, 2026 and May 28, 2026")
        assert r["raw_dates"].count("2026-05-28") == 1

    def test_raw_dates_contains_all_dates(self):
        r = _parse_email_dates("28 May 2026 and 31 May 2026")
        assert "2026-05-28" in r["raw_dates"]
        assert "2026-05-31" in r["raw_dates"]


# ---------------------------------------------------------------------------
# Full Marriott range line (HTML entity in range)
# ---------------------------------------------------------------------------

class TestMarriottRangeLine:
    def test_entity_ndash_in_range(self):
        """&ndash; decoded to dash so range is parsed correctly."""
        r = _parse_email_dates("Thu, May 28, 2026 &ndash; Sun, May 31, 2026")
        assert r["checkin"] == "2026-05-28"
        assert r["checkout"] == "2026-05-31"

    def test_labeled_and_range_together(self):
        """When both labeled dates and a range appear, labeled dates win."""
        body = (
            "<th>Check-In:</th><th>Thursday, May 28, 2026</th>"
            "<td>Check-Out:</td><td>Sunday, May 31, 2026</td>"
            "<p>Thu, May 28, 2026 &ndash; Sun, May 31, 2026</p>"
        )
        r = _parse_email_dates(body)
        assert r["checkin"] == "2026-05-28"
        assert r["checkout"] == "2026-05-31"
        assert not any("inferred" in w.lower() for w in r["warnings"])


# ---------------------------------------------------------------------------
# _parse_email — date parse validation
# ---------------------------------------------------------------------------

class TestGmailFlightScannerDateValidation:
    """Tests for date parse validation added to gmail_flight_scanner._parse_email."""

    def test_flight_with_departure_date_parse_ok(self):
        email = {"subject": "Flight confirmation", "body": "Departure: 2026-06-01", "messageId": "test-id-123"}
        record = _parse_email(email)
        assert record["date_parse_ok"] is True
        assert "departure date not found" not in record["parse_warnings"]

    def test_flight_missing_departure_date_parse_fail(self):
        email = {"subject": "Flight confirmation", "body": "Your booking is confirmed.", "messageId": "test-id-123"}
        record = _parse_email(email)
        assert record["date_parse_ok"] is False
        assert "departure date not found" in record["parse_warnings"]

    def test_hotel_with_checkin_date_parse_ok(self):
        email = {
            "subject": "Hotel reservation",
            "body": "Check-In: May 28, 2026\nCheck-Out: May 31, 2026",
            "messageId": "test-id-123",
        }
        record = _parse_email(email)
        assert record["date_parse_ok"] is True

    def test_hotel_missing_checkin_date_parse_fail(self):
        email = {
            "subject": "Hotel reservation",
            "body": "Your hotel booking is confirmed.",
            "messageId": "test-id-123",
        }
        record = _parse_email(email)
        assert record["date_parse_ok"] is False
        assert "checkin date not found" in record["parse_warnings"]

    def test_other_type_always_date_parse_ok(self):
        email = {
            "subject": "Order confirmation",
            "body": "Your order has been placed.",
            "messageId": "test-id-123",
        }
        record = _parse_email(email)
        assert record["date_parse_ok"] is True

    def test_parse_warnings_include_parser_warnings(self):
        email = {
            "subject": "Hotel reservation",
            "body": "Check-In: May 28, 2026\nCheck-In: May 29, 2026",
            "messageId": "test-id-123",
        }
        record = _parse_email(email)
        assert len(record["parse_warnings"]) > 0
        assert any("multiple" in w.lower() for w in record["parse_warnings"])


class TestLLMFallback:
    """Tests for LLM date extraction fallback in gmail_flight_scanner."""

    def test_llm_fallback_not_called_when_dates_found(self):
        """LLM fallback should NOT be called when regex already found dates."""
        email = {
            "subject": "Flight confirmation",
            "body": "Departure: 2026-06-01\nArrival: 2026-06-01",
            "messageId": "test-llm-001",
        }
        with unittest.mock.patch(
            "ouro.tools.gmail_flight_scanner._llm_extract_dates"
        ) as mock_llm:
            record = _parse_email(email)
        assert record["date_parse_ok"] is True
        mock_llm.assert_not_called()

    def test_llm_fallback_called_when_no_dates_for_flight(self):
        """LLM fallback SHOULD be called for flights with no detected dates."""
        email = {
            "subject": "Flight confirmation TK9999",
            "body": "Your Turkish Airlines flight is confirmed.",
            "messageId": "test-llm-002",
        }
        with unittest.mock.patch(
            "ouro.tools.gmail_flight_scanner._llm_extract_dates",
            return_value={
                "departure": "2026-06-01T10:00:00",
                "arrival": "2026-06-01T14:00:00",
                "checkin": None,
                "checkout": None,
            },
        ) as mock_llm:
            record = _parse_email(email)
        mock_llm.assert_called_once()
        assert record["date_parse_ok"] is True
        assert record["departure"] == "2026-06-01T10:00:00"
        assert "dates extracted via LLM fallback" in record["parse_warnings"]

    def test_llm_fallback_hotel_applied(self):
        """LLM fallback applies checkin/checkout for hotel emails."""
        email = {
            "subject": "Hotel booking confirmed - Superbude Wien",
            "body": "Your hotel reservation at Superbude is confirmed.",
            "messageId": "test-llm-003",
        }
        with unittest.mock.patch(
            "ouro.tools.gmail_flight_scanner._llm_extract_dates",
            return_value={
                "departure": None,
                "arrival": None,
                "checkin": "2026-06-01",
                "checkout": "2026-06-05",
            },
        ):
            record = _parse_email(email)
        assert record["date_parse_ok"] is True
        assert record["checkin"] == "2026-06-01"
        assert record["checkout"] == "2026-06-05"
        assert "dates extracted via LLM fallback" in record["parse_warnings"]

    def test_llm_fallback_failure_leaves_date_parse_ok_false(self):
        """If LLM fallback returns None, date_parse_ok stays False."""
        email = {
            "subject": "Flight confirmation",
            "body": "Your flight is confirmed.",
            "messageId": "test-llm-004",
        }
        with unittest.mock.patch(
            "ouro.tools.gmail_flight_scanner._llm_extract_dates",
            return_value=None,
        ):
            record = _parse_email(email)
        assert record["date_parse_ok"] is False
        assert "dates extracted via LLM fallback" not in record["parse_warnings"]

    def test_llm_fallback_all_none_keeps_date_parse_ok_false_for_flight(self):
        """If LLM returns dict with no departure for a flight, date_parse_ok stays False."""
        email = {
            "subject": "Flight confirmation",
            "body": "Your flight is confirmed.",
            "messageId": "test-llm-005",
        }
        with unittest.mock.patch(
            "ouro.tools.gmail_flight_scanner._llm_extract_dates",
            return_value={
                "departure": None,
                "arrival": None,
                "checkin": "2026-06-01",
                "checkout": None,
            },
        ):
            record = _parse_email(email)
        # Flight type with no departure should still be False
        assert record["date_parse_ok"] is False


class TestReferenceFixtures:
    """Tests using reference corpus from real booking emails."""

    def test_reference_fixtures_exist(self):
        """Reference fixture file exists and has entries."""
        import json
        import os

        fixture_path = os.path.join(
            os.path.dirname(__file__), "fixtures", "email_parser_reference.json"
        )
        assert os.path.exists(fixture_path), f"Reference fixtures not found: {fixture_path}"
        data = json.load(open(fixture_path))
        assert len(data) > 0, "Reference fixtures should not be empty"

    def test_reference_fixtures_structure(self):
        """Each reference fixture has required fields."""
        import json
        import os

        fixture_path = os.path.join(
            os.path.dirname(__file__), "fixtures", "email_parser_reference.json"
        )
        data = json.load(open(fixture_path))
        required_fields = {"messageId", "booking_type", "subject"}
        for entry in data:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Missing fields {missing} in fixture: {entry.get('messageId')}"

    def test_reference_fixtures_have_travel_types(self):
        """Reference fixtures include flight/hotel/train booking types."""
        import json
        import os

        fixture_path = os.path.join(
            os.path.dirname(__file__), "fixtures", "email_parser_reference.json"
        )
        data = json.load(open(fixture_path))
        types = {e["booking_type"] for e in data}
        assert types & {"flight", "hotel", "train"}, (
            f"Expected at least one travel booking type, got: {types}"
        )

    def test_vienna_hotel_fixture_present(self):
        """Vienna hotel (Superbude) fixture is in reference corpus."""
        import json
        import os

        fixture_path = os.path.join(
            os.path.dirname(__file__), "fixtures", "email_parser_reference.json"
        )
        data = json.load(open(fixture_path))
        ids = {e["messageId"] for e in data}
        # Superbude Wien hotel booking
        assert "19e3bcb1ed50a085" in ids, "Vienna hotel fixture missing from reference corpus"

    def test_vienna_flight_fixture_present(self):
        """Vienna flight (Turkish Airlines TBS->VIE) fixture is in reference corpus."""
        import json
        import os

        fixture_path = os.path.join(
            os.path.dirname(__file__), "fixtures", "email_parser_reference.json"
        )
        data = json.load(open(fixture_path))
        ids = {e["messageId"] for e in data}
        # Turkish Airlines TBS->VIE
        assert "19e3bbdc5bf3a73f" in ids, "Vienna flight fixture missing from reference corpus"

