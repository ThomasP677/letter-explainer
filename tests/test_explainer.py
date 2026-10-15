"""Run from the project folder:  python -m unittest discover tests -v"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from explainer import check_input, explain, find_dates, verify  # noqa: E402

S = ROOT / "samples"
DMV = (S / "1_normal_dmv_renewal.txt").read_text()
FTB = (S / "2_difficult_ftb_notice.txt").read_text()
RECEIPT = (S / "3_invalid_grocery_receipt.txt").read_text()


class InputChecks(unittest.TestCase):
    def test_empty_rejected(self):
        self.assertFalse(check_input("   ")[0])

    def test_too_short_rejected(self):
        self.assertIn("error", explain("Please pay.", api_key=""))

    def test_too_long_rejected(self):
        self.assertFalse(check_input("Notice. " * 5000)[0])


class DateParsing(unittest.TestCase):
    def test_formats_normalize_to_same_date(self):
        a = find_dates("due October 22, 2026")[0][0]
        b = find_dates("due 10/22/2026")[0][0]
        c = find_dates("due 2026-10-22")[0][0]
        self.assertEqual(a, b)
        self.assertEqual(b, c)


class Verifier(unittest.TestCase):
    """The core safety net: catch plausible-but-wrong AI answers."""

    def test_correct_answer_passes(self):
        ai = {"is_official_letter": True,
              "deadlines": [{"date": "November 15, 2026", "what": "renew"}],
              "amounts": [{"amount": "$296.00", "what": "total"}],
              "amount_due_now": "$296.00"}
        r = verify(ai, DMV)
        self.assertTrue(r["amount_due_verified"])
        self.assertTrue(r["deadlines"][0]["verified"])

    def test_calculated_total_is_flagged(self):
        # Plausible mistake: AI adds the $34 installment fee to $793.91 -> $827.91
        ai = {"is_official_letter": True,
              "deadlines": [{"date": "October 22, 2026", "what": "pay"},
                            {"date": "November 21, 2026", "what": "protest"}],
              "amounts": [{"amount": "$827.91", "what": "total with fee"}],
              "amount_due_now": "$827.91"}
        r = verify(ai, FTB)
        self.assertFalse(r["amount_due_verified"])
        self.assertFalse(r["all_verified"])

    def test_wrong_date_is_flagged(self):
        # Plausible mistake: AI says protest deadline is 60 days from today, not from notice date
        ai = {"is_official_letter": True,
              "deadlines": [{"date": "December 11, 2026", "what": "protest"}],
              "amounts": [], "amount_due_now": None}
        r = verify(ai, FTB)
        self.assertFalse(r["deadlines"][0]["verified"])

    def test_missed_deadline_is_flagged(self):
        # AI only lists the payment date and forgets the protest deadline
        ai = {"is_official_letter": True,
              "deadlines": [{"date": "October 22, 2026", "what": "pay"}],
              "amounts": [], "amount_due_now": None}
        r = verify(ai, FTB)
        self.assertTrue(any("November 21, 2026" in d for d in r["possibly_missed_dates"]))


class OfflineMode(unittest.TestCase):
    def test_dmv_offline(self):
        r = explain(DMV, api_key="")
        self.assertEqual(r["mode"], "offline")
        self.assertEqual(r["amount_due_now"], "$296.00")
        self.assertTrue(r["amount_due_verified"])

    def test_receipt_not_official(self):
        r = explain(RECEIPT, api_key="")
        self.assertFalse(r["is_official_letter"])
        self.assertEqual(r["deadlines"], [])


if __name__ == "__main__":
    unittest.main()
