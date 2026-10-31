PERSONAL BUDGET TRACKER

Small spends. Big total.
A Python terminal app for students to track everyday spending and understand
how small purchases add up.

Features
- Record income and expenses with categories, dates and optional notes.
- View transactions and spending summaries for all time, a month or a date range.
- Set category budgets and see the percentage used, remaining funds or overspending.

Requirements and run
Python 3.9 or later. Standard library only; no installation of extra packages.
Extract the ZIP and open a terminal in the budget_tracker folder:
    python3 budget_tracker.py
On Windows, use py instead of python3.

For Ed, upload budget_tracker.py, test_budget_tracker.py and README.txt.
Run budget_tracker.py as the entry point.

Usage
Follow the numbered menus. Enter positive amounts such as 12.50, without a
currency symbol and with at most two decimal places. Dates use YYYY-MM-DD;
months use YYYY-MM. Blank dates/months default to today/the current month.
Enter q to cancel an operation or exit from the main menu.

Budget rules
80% to below 100%: NEAR LIMIT. Exactly 100%: AT LIMIT. Above 100%: OVER BUDGET.
Warnings appear in the terminal after recording an expense. Limits repeat each
month without carrying over unused amounts. Changing a limit also changes
past-month comparisons.

Saving
Confirmed changes are saved automatically to budget_data.json beside the program
and loaded next time. The folder must be writable. Keep this file when backing
up or moving the program. Invalid data files are not overwritten.

Tests
Run from the same folder:
    python3 -B -m unittest -v test_budget_tracker
The 21 tests cover calculations, validation and saving/loading without changing
your real records.

Scope
Single user, one currency ($). Net means income minus expenses for the selected
period. Transactions cannot be edited or deleted through the menu.
