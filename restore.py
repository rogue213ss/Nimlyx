import sys

with open('backend/steam.py', 'r', encoding='utf-8') as f:
    text = f.read()

currency = """_CURRENCY_SYMBOLS = {
    "USD": "$", "CAD": "CA$", "AUD": "A$", "NZD": "NZ$", "SGD": "S$",
    "GBP": "£", "EUR": "€", "JPY": "¥", "CNY": "¥", "KRW": "?",
    "INR": "?", "RUB": "?", "BRL": "R$", "MXN": "MX$", "PKR": "Rs ",
}

def _format_price_cents"""

text = text.replace("def _format_price_cents", currency)

with open('backend/steam.py', 'w', encoding='utf-8') as f:
    f.write(text)
