from typing import Dict, List, Tuple


CATEGORY_KEYWORDS = {
    "food": ["food", "lunch", "dinner", "breakfast", "pizza", "burger", "restaurant", "cafe",
             "coffee", "tea", "snack", "meal", "eat", "drinks", "bar", "pub", "grocery",
             "groceries", "supermarket", "sushi", "noodle", "biryani", "swiggy", "zomato"],
    "travel": ["travel", "uber", "ola", "taxi", "cab", "flight", "bus", "train", "metro",
               "petrol", "fuel", "toll", "parking", "bike", "auto", "transport", "trip",
               "journey", "airport", "ticket", "visa"],
    "accommodation": ["hotel", "hostel", "airbnb", "rent", "room", "stay", "lodge",
                      "motel", "booking", "accommodation", "house", "flat", "pg"],
    "entertainment": ["movie", "cinema", "netflix", "spotify", "game", "concert", "show",
                      "event", "ticket", "party", "club", "amusement", "fun", "outing"],
    "utilities": ["electricity", "water", "wifi", "internet", "phone", "bill", "recharge",
                  "gas", "mobile", "broadband", "dth", "subscription", "insurance"],
    "shopping": ["shopping", "clothes", "amazon", "flipkart", "shoes", "bag", "mall",
                 "store", "purchase", "buy", "gift", "gadget", "electronics"],
}


def categorize_expense(description: str) -> str:
    text = description.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "other"


def calculate_balances(expenses_data: List[Dict]) -> Dict[str, float]:
    """
    Returns net balance for each member.
    Positive = this person is owed money (others owe them).
    Negative = this person owes money.
    """
    balances: Dict[str, float] = {}

    for exp in expenses_data:
        paid_by = exp["paid_by"]
        amount = exp["amount"]

        # Payer gets credit for the full amount
        balances[paid_by] = balances.get(paid_by, 0) + amount

        # Each participant gets debited their share
        for p in exp["participants"]:
            uid = p["user_id"]
            share = p["amount"]
            balances[uid] = balances.get(uid, 0) - share

    return balances


def get_settlement_instructions(balances: Dict[str, float], user_names: Dict[str, str]) -> List[Dict]:
    """
    Greedy algorithm to minimize number of transactions.
    Returns list of {from, from_name, to, to_name, amount}.
    """
    # debtors owe money (negative balance), creditors are owed (positive balance)
    debtors = {k: -v for k, v in balances.items() if v < -0.005}
    creditors = {k: v for k, v in balances.items() if v > 0.005}

    transactions = []

    while debtors and creditors:
        debtor = max(debtors, key=debtors.get)
        creditor = max(creditors, key=creditors.get)

        amount = round(min(debtors[debtor], creditors[creditor]), 2)
        transactions.append({
            "from": debtor,
            "from_name": user_names.get(debtor, debtor),
            "to": creditor,
            "to_name": user_names.get(creditor, creditor),
            "amount": amount
        })

        debtors[debtor] = round(debtors[debtor] - amount, 10)
        creditors[creditor] = round(creditors[creditor] - amount, 10)

        if debtors[debtor] < 0.005:
            del debtors[debtor]
        if creditors[creditor] < 0.005:
            del creditors[creditor]

    return transactions
