# Automated tests for calculations, input validation, budgets, and file persistence.
# Run from this folder: python3 -B -m unittest -v test_budget_tracker
# Temporary folders keep these tests separate from the user's saved data.
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import budget_tracker as tracker


class BudgetTrackerTests(unittest.TestCase):
    def setUp(self):
        self.data = tracker.new_data()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "budget_data.json"

    def expense(self, amount, category="Food", day="2026-10-08"):
        return tracker.add_transaction(self.data, "expense", amount, category, day)

    def test_amounts_use_exact_cents(self):
        for text, expected in (("0.10", 10), ("12.5", 1250), ("12", 1200),
                               (" 1.09 ", 109), ("999999999.99", tracker.MAX_CENTS)):
            with self.subTest(text=text):
                self.assertEqual(tracker.parse_amount(text), expected)
        self.assertEqual(tracker.parse_amount("0.10") + tracker.parse_amount("0.20"), 30)

    def test_invalid_amounts(self):
        for text in ("0", "0.00", "-1", "1.234", "NaN", "inf", "1e2", "$10",
                     "1,000", "", "1000000000", ".5", "1."):
            with self.subTest(text=text), self.assertRaises(ValueError):
                tracker.parse_amount(text)

    def test_money_format(self):
        self.assertEqual(tracker.money(-123456), "-$1,234.56")
        self.assertEqual(tracker.money(1), "$0.01")

    def test_calendar_and_leap_years(self):
        self.assertEqual(tracker.month_bounds("2024-02"), ("2024-02-01", "2024-02-29"))
        self.assertEqual(tracker.month_bounds("2026-02"), ("2026-02-01", "2026-02-28"))
        self.assertEqual(tracker.month_bounds("2026-12"), ("2026-12-01", "2026-12-31"))
        for day in ("2026-02-29", "2026-13-01", "2026-1-01", "0000-01-01"):
            with self.subTest(day=day), self.assertRaises(ValueError):
                tracker.parse_date(day)

    def test_empty_first_run(self):
        self.assertEqual(tracker.load_data(self.path), tracker.new_data())
        self.assertFalse(self.path.exists())
        result = tracker.summarise([])
        self.assertEqual((result["income"], result["expense"], result["balance"]), (0, 0, 0))

    def test_transaction_ids_and_notes(self):
        first = self.expense("12")
        second = tracker.add_transaction(self.data, "income", "200", "Salary",
                                         "2026-10-01", " Salary ")
        self.assertEqual((first["id"], second["id"]), (1, 2))
        self.assertEqual(second["note"], "Salary")

    def test_invalid_transaction_does_not_change_data(self):
        for kind, amount, category, day in (
            ("expense", "-1", "Food", "2026-10-01"),
            ("income", "10", "Rent", "2026-10-01"),
            ("expense", "10", "Food", "2026-02-30"),
            ("refund", "10", "Food", "2026-10-01"),
        ):
            with self.subTest(kind=kind, amount=amount, day=day):
                with self.assertRaises(ValueError):
                    tracker.add_transaction(self.data, kind, amount, category, day)
                self.assertEqual(self.data["transactions"], [])

    def test_summary_by_category_and_type(self):
        tracker.add_transaction(self.data, "income", "200", "Other", "2026-10-01")
        self.expense("20", "Food")
        self.expense("5.50", "Food")
        self.expense("10", "Transport")
        self.expense("1", "Other")
        result = tracker.summarise(self.data["transactions"])
        self.assertEqual(result["income"], 20000)
        self.assertEqual(result["expense"], 3650)
        self.assertEqual(result["balance"], 16350)
        self.assertEqual(result["by_category"]["Food"], 2550)
        self.assertEqual(result["by_category"]["Other"], 100)

    def test_negative_net_is_allowed(self):
        self.expense("5")
        self.assertEqual(tracker.summarise(self.data["transactions"])["balance"], -500)

    def test_inclusive_period_and_sorted_history(self):
        for day in ("2026-11-01", "2026-10-31", "2026-09-30", "2026-10-01"):
            self.expense("1", day=day)
        entries = tracker.select_transactions(self.data, "2026-10-01", "2026-10-31")
        self.assertEqual([entry["date"] for entry in entries], ["2026-10-01", "2026-10-31"])
        self.assertEqual(len(tracker.select_transactions(self.data)), 4)
        self.assertEqual(len(tracker.select_transactions(self.data, "2026-10-31", "2026-10-31")), 1)

    def test_reversed_period_rejected(self):
        with self.assertRaises(ValueError):
            tracker.select_transactions(self.data, "2026-11-01", "2026-10-01")

    def test_warning_boundaries(self):
        for spent, expected in ((7999, "OK"), (8000, "NEAR LIMIT"),
                                (9999, "NEAR LIMIT"), (10000, "AT LIMIT"),
                                (10001, "OVER BUDGET")):
            with self.subTest(spent=spent):
                self.assertEqual(tracker.budget_status(spent, 10000), expected)
        self.assertEqual(tracker.budget_status(99999, None), "NO BUDGET")

    def test_monthly_budgets_exclude_other_months_and_income(self):
        tracker.set_budget(self.data, "Food", "100")
        self.expense("80")
        self.expense("50", day="2026-09-01")
        tracker.add_transaction(self.data, "income", "1000", "Salary", "2026-10-01")
        row = tracker.budget_rows(self.data, "2026-10")[0]
        self.assertEqual((row["spent"], row["remaining"], row["status"]), (8000, 2000, "NEAR LIMIT"))
        next_month = tracker.budget_rows(self.data, "2026-11")[0]
        self.assertEqual((next_month["spent"], next_month["limit"]), (0, 10000))

    def test_budget_update_and_validation(self):
        tracker.set_budget(self.data, "Food", "100")
        tracker.set_budget(self.data, "Food", "200")
        self.assertEqual(self.data["budgets"]["Food"], 20000)
        for category, amount in (("Salary", "20"), ("Food", "0")):
            with self.subTest(category=category), self.assertRaises(ValueError):
                tracker.set_budget(self.data, category, amount)
        self.assertEqual(self.data["budgets"]["Food"], 20000)

    def test_round_trip_persistence(self):
        tracker.add_transaction(self.data, "expense", "2.35", "Food", "2026-10-08", "Breakfast")
        tracker.set_budget(self.data, "Food", "100")
        tracker.save_data(self.data, self.path)
        self.assertEqual(tracker.load_data(self.path), self.data)
        self.expense("10")
        tracker.save_data(self.data, self.path)
        self.assertEqual(tracker.load_data(self.path), self.data)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_corrupt_file_preserved(self):
        content = "{broken file"
        self.path.write_text(content, encoding="utf-8")
        with self.assertRaises(ValueError):
            tracker.load_data(self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), content)

    def test_invalid_saved_data_rejected(self):
        self.expense("1")
        invalid_cases = []
        for field, value in (("amount_cents", True), ("amount_cents", -1),
                             ("date", "bad"), ("category", "Unknown"), ("note", None)):
            changed = copy.deepcopy(self.data)
            changed["transactions"][0][field] = value
            invalid_cases.append(changed)
        duplicate = copy.deepcopy(self.data)
        duplicate["transactions"].append(copy.deepcopy(duplicate["transactions"][0]))
        invalid_cases.extend([duplicate, {"version": 2, "transactions": [], "budgets": {}},
                              {"version": 1, "transactions": [], "budgets": {"Food": 0}}])
        for index, data in enumerate(invalid_cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                tracker.validate_data(data)

    def test_failed_replace_keeps_previous_file(self):
        tracker.save_data(self.data, self.path)
        original = self.path.read_bytes()
        self.expense("20")
        with patch.object(Path, "replace", side_effect=PermissionError("Read-only folder")):
            with self.assertRaises(OSError):
                tracker.save_data(self.data, self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_failed_save_does_not_confirm_transaction(self):
        answers = ["1", "2", "1", "10", "2026-10-08", "Lunch", "2", "1", "0"]
        output = io.StringIO()
        with patch.object(tracker, "load_data", return_value=self.data), \
                patch.object(tracker, "save_data", side_effect=OSError("Disk full")), \
                patch("builtins.input", side_effect=answers), redirect_stdout(output):
            self.assertEqual(tracker.main(), 0)
        self.assertEqual(self.data["transactions"], [])
        self.assertIn("Operation failed", output.getvalue())
        self.assertIn("No transactions", output.getvalue())

    def test_cancel_does_not_save(self):
        output = io.StringIO()
        with patch.object(tracker, "load_data", return_value=self.data), \
                patch.object(tracker, "save_data") as save, \
                patch("builtins.input", side_effect=["1", "2", "q", "0"]), \
                redirect_stdout(output):
            self.assertEqual(tracker.main(), 0)
        save.assert_not_called()
        self.assertIn("Cancelled", output.getvalue())

    def test_actual_cli_restart_and_reports(self):
        script = Path(self.folder.name) / "budget_tracker.py"
        shutil.copyfile(tracker.__file__, script)
        first_input = "\n".join([
            "4", "1", "1", "100",
            "1", "2", "1", "80", "2026-10-08", "Lunch",
            "1", "1", "1", "200", "2026-10-08", "Pay",
            "1", "2", "1", "20", "2026-10-09", "Dinner",
            "1", "2", "1", "1", "2026-10-10", "Snack", "0", ""
        ])
        first = subprocess.run([sys.executable, str(script)], input=first_input,
                               text=True, capture_output=True, cwd="/", timeout=10)
        self.assertEqual(first.returncode, 0, first.stderr)
        for status in ("NEAR LIMIT", "AT LIMIT", "OVER BUDGET"):
            self.assertIn(status, first.stdout)
        second_input = "\n".join(["2", "2", "2026-10", "3", "2", "2026-10",
                                  "5", "2026-10", "4", "1", "2", "0", ""])
        second = subprocess.run([sys.executable, str(script)], input=second_input,
                                text=True, capture_output=True, cwd="/", timeout=10)
        self.assertEqual(second.returncode, 0, second.stderr)
        for text in ("Lunch", "Income:   $200.00", "Expenses: $101.00", "Net:      $99.00"):
            self.assertIn(text, second.stdout)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["transactions"]), 4)
        self.assertEqual(saved["budgets"], {})


if __name__ == "__main__":
    unittest.main()
