# Personal Budget Tracker: record transactions, summarise spending, and track budgets.
# Run with Python 3.9 or later: python3 budget_tracker.py
# Transactions and budget settings are saved in budget_data.json beside this file.
import calendar
import copy
import json
import re
import tempfile
from datetime import date
from pathlib import Path


EXPENSE_CATEGORIES = ("Food", "Transport", "Entertainment", "Rent", "Other")
INCOME_CATEGORIES = ("Salary", "Allowance", "Other")
WARNING_PERCENT = 80
MAX_CENTS = 99_999_999_999
DATA_FILE = Path(__file__).resolve().with_name("budget_data.json")


class Cancelled(Exception):
    pass


def parse_amount(text):
    text = text.strip()
    if not re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,2})?", text):
        raise ValueError("Enter a positive amount with at most 2 decimal places.")
    whole, _, fraction = text.partition(".")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if cents <= 0:
        raise ValueError("Amount must be greater than zero.")
    return cents


def money(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def parse_date(text):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        raise ValueError("Use a valid date in YYYY-MM-DD format.")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ValueError("Use a valid date in YYYY-MM-DD format.") from None
    return text


def month_bounds(month):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise ValueError("Use a valid month in YYYY-MM format.")
    first = date.fromisoformat(parse_date(month + "-01"))
    last_day = calendar.monthrange(first.year, first.month)[1]
    return first.isoformat(), f"{month}-{last_day:02d}"


def new_data():
    return {"version": 1, "transactions": [], "budgets": {}}


def validate_data(data):
    if not isinstance(data, dict) or type(data.get("version")) is not int:
        raise ValueError("Invalid data file format.")
    if data["version"] != 1:
        raise ValueError("Unsupported data file version.")
    transactions = data.get("transactions")
    budgets = data.get("budgets")
    if not isinstance(transactions, list) or not isinstance(budgets, dict):
        raise ValueError("Invalid transaction or budget data.")
    seen_ids = set()
    for item in transactions:
        if not isinstance(item, dict):
            raise ValueError("Invalid transaction.")
        number = item.get("id")
        if type(number) is not int or number <= 0 or number in seen_ids:
            raise ValueError("Transaction IDs must be unique positive integers.")
        seen_ids.add(number)
        kind = item.get("type")
        if kind not in ("income", "expense"):
            raise ValueError("Invalid transaction type.")
        categories = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
        if item.get("category") not in categories:
            raise ValueError("Invalid transaction category.")
        if not isinstance(item.get("date"), str):
            raise ValueError("Invalid transaction date.")
        parse_date(item["date"])
        amount = item.get("amount_cents")
        if type(amount) is not int or not 0 < amount <= MAX_CENTS:
            raise ValueError("Invalid transaction amount.")
        if not isinstance(item.get("note"), str):
            raise ValueError("Invalid transaction note.")
    for category, limit in budgets.items():
        if category not in EXPENSE_CATEGORIES:
            raise ValueError("Invalid budget category.")
        if type(limit) is not int or not 0 < limit <= MAX_CENTS:
            raise ValueError("Invalid budget limit.")


def load_data(path=DATA_FILE):
    path = Path(path)
    if not path.exists():
        return new_data()
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    validate_data(data)
    return data


def save_data(data, path=DATA_FILE):
    validate_data(data)
    path = Path(path)
    temporary = None
    try:
        # Replace the old file only after the complete new file is written.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def add_transaction(data, kind, amount_text, category, entry_date, note=""):
    categories = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
    if kind not in ("income", "expense") or category not in categories:
        raise ValueError("Invalid transaction type or category.")
    amount = parse_amount(amount_text)
    parse_date(entry_date)
    if not isinstance(note, str):
        raise ValueError("Note must be text.")
    number = max((item["id"] for item in data["transactions"]), default=0) + 1
    item = {"id": number, "date": entry_date, "type": kind,
            "category": category, "amount_cents": amount, "note": note.strip()}
    data["transactions"].append(item)
    return item


def select_transactions(data, start=None, end=None):
    if start is not None:
        parse_date(start)
    if end is not None:
        parse_date(end)
    if start is not None and end is not None and start > end:
        raise ValueError("Start date must not be after end date.")
    return sorted(
        [item for item in data["transactions"]
         if (start is None or item["date"] >= start)
         and (end is None or item["date"] <= end)],
        key=lambda item: (item["date"], item["id"])
    )


def summarise(transactions):
    income = 0
    expenses = {category: 0 for category in EXPENSE_CATEGORIES}
    for item in transactions:
        if item["type"] == "income":
            income += item["amount_cents"]
        else:
            expenses[item["category"]] += item["amount_cents"]
    total_expense = sum(expenses.values())
    return {"income": income, "expense": total_expense,
            "balance": income - total_expense, "by_category": expenses}


def set_budget(data, category, amount_text):
    if category not in EXPENSE_CATEGORIES:
        raise ValueError("Invalid budget category.")
    data["budgets"][category] = parse_amount(amount_text)


def budget_status(spent, limit):
    if limit is None:
        return "NO BUDGET"
    if spent > limit:
        return "OVER BUDGET"
    if spent == limit:
        return "AT LIMIT"
    if spent * 100 >= limit * WARNING_PERCENT:
        return "NEAR LIMIT"
    return "OK"


def budget_rows(data, month):
    start, end = month_bounds(month)
    expenses = summarise(select_transactions(data, start, end))["by_category"]
    rows = []
    for category in EXPENSE_CATEGORIES:
        spent = expenses[category]
        limit = data["budgets"].get(category)
        rows.append({"category": category, "spent": spent, "limit": limit,
                     "remaining": None if limit is None else limit - spent,
                     "status": budget_status(spent, limit)})
    return rows


def read_text(prompt):
    value = input(prompt).strip()
    if value.lower() == "q":
        raise Cancelled
    return value


def read_choice(prompt, choices):
    while True:
        value = read_text(prompt)
        if value in choices:
            return value
        print("Choose one of: " + ", ".join(choices))


def read_amount(prompt):
    while True:
        value = read_text(prompt)
        try:
            parse_amount(value)
            return value
        except ValueError as error:
            print(error)


def read_date(prompt, default=None):
    while True:
        value = read_text(prompt) or default
        try:
            if value is None:
                raise ValueError("A date is required.")
            return parse_date(value)
        except ValueError as error:
            print(error)


def read_month():
    current = date.today().strftime("%Y-%m")
    while True:
        value = read_text(f"Month YYYY-MM [Enter = {current}]: ") or current
        try:
            month_bounds(value)
            return value
        except ValueError as error:
            print(error)


def read_category(categories):
    for index, category in enumerate(categories, 1):
        print(f"  {index}. {category}")
    choices = [str(index) for index in range(1, len(categories) + 1)]
    return categories[int(read_choice("Category: ", choices)) - 1]


def read_period():
    print("1. All time   2. One month   3. Custom date range")
    choice = read_choice("Period: ", ("1", "2", "3"))
    if choice == "1":
        return None, None, "All time"
    if choice == "2":
        month = read_month()
        start, end = month_bounds(month)
        return start, end, month
    start = read_date("Start date YYYY-MM-DD: ")
    while True:
        end = read_date("End date YYYY-MM-DD (inclusive): ")
        if end >= start:
            return start, end, f"{start} to {end}"
        print("End date must not be before start date.")


def add_screen(data):
    print("1. Income   2. Expense")
    kind = "income" if read_choice("Type: ", ("1", "2")) == "1" else "expense"
    categories = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
    category = read_category(categories)
    amount = read_amount("Amount (e.g. 12.50, no currency symbol): ")
    today = date.today().isoformat()
    entry_date = read_date(f"Date YYYY-MM-DD [Enter = {today}]: ", today)
    note = read_text("Note [optional]: ")
    return add_transaction(data, kind, amount, category, entry_date, note)


def history_screen(data):
    start, end, label = read_period()
    entries = select_transactions(data, start, end)
    print(f"\nTRANSACTIONS | {label}")
    if not entries:
        print("No transactions in this period.")
        return
    for item in entries:
        print(f"#{item['id']} | {item['date']} | {item['type'].upper()} | "
              f"{item['category']} | {money(item['amount_cents'])} | {item['note']}")


def summary_screen(data):
    start, end, label = read_period()
    result = summarise(select_transactions(data, start, end))
    print(f"\nSUMMARY | {label}")
    print(f"Income:   {money(result['income'])}")
    print(f"Expenses: {money(result['expense'])}")
    print(f"Net:      {money(result['balance'])}")
    print("Spending by category:")
    for category, amount in result["by_category"].items():
        share = amount / result["expense"] * 100 if result["expense"] else 0
        print(f"  {category:<15} {money(amount):>18}  ({share:.1f}%)")


def budget_screen(data, month):
    print(f"\nMONTHLY BUDGETS | {month}")
    print("Current limits repeat each month; unused amounts do not carry over.")
    for row in budget_rows(data, month):
        if row["limit"] is None:
            print(f"  {row['category']}: spent {money(row['spent'])} | NO BUDGET")
            continue
        percent = row["spent"] / row["limit"] * 100
        remaining = row["remaining"]
        detail = (f"remaining {money(remaining)}" if remaining >= 0
                  else f"over by {money(-remaining)}")
        print(f"  {row['category']}: {money(row['spent'])} / {money(row['limit'])} "
              f"({percent:.1f}%) | {row['status']} | {detail}")


def budget_settings_screen(data):
    print("Limits repeat monthly. Changing a limit also changes past-month comparisons.")
    category = read_category(EXPENSE_CATEGORIES)
    existing = data["budgets"].get(category)
    print("Current limit: " + (money(existing) if existing is not None else "Not set"))
    print("1. Set / update limit   2. Remove limit")
    choice = read_choice("Action: ", ("1", "2"))
    if choice == "1":
        set_budget(data, category, read_amount("Monthly limit: "))
    else:
        data["budgets"].pop(category, None)


def main():
    print("PERSONAL BUDGET TRACKER")
    print("Single user, single currency ($). Type q to cancel any prompt.")
    print(f"Data file: {DATA_FILE}")
    try:
        data = load_data()
    except (OSError, ValueError, UnicodeError) as error:
        print(f"Cannot load data: {error}")
        print("Your existing file has not been changed. Back it up and repair it before retrying.")
        return 1
    if data["budgets"]:
        budget_screen(data, date.today().strftime("%Y-%m"))
    while True:
        print("\n1. Add income / expense\n2. View transactions\n3. Spending summary"
              "\n4. Set / remove monthly budget\n5. View monthly budgets\n0. Exit")
        try:
            choice = read_choice("Choose: ", ("0", "1", "2", "3", "4", "5"))
        except (Cancelled, EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0
        try:
            if choice == "0":
                print("Goodbye. All confirmed changes have been saved.")
                return 0
            if choice in ("1", "4"):
                candidate = copy.deepcopy(data)
                if choice == "1":
                    item = add_screen(candidate)
                else:
                    budget_settings_screen(candidate)
                save_data(candidate)
                data = candidate
                print("Saved successfully.")
                if choice == "1" and item["type"] == "expense":
                    budget_screen(data, item["date"][:7])
                elif choice == "4":
                    budget_screen(data, date.today().strftime("%Y-%m"))
            elif choice == "2":
                history_screen(data)
            elif choice == "3":
                summary_screen(data)
            elif choice == "5":
                budget_screen(data, read_month())
        except Cancelled:
            print("Cancelled. Returned to the menu.")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye. Any completed saves are retained.")
            return 0
        except (OSError, ValueError, UnicodeError) as error:
            print(f"Operation failed: {error}")
            print("If you were making a change, it was not confirmed. Please retry.")


if __name__ == "__main__":
    raise SystemExit(main())
