"""
TitanCode Technologies — Core Currency & Subunit Module
=======================================================
This module provides precision currency and subunit arithmetic.
In financial transactions, amounts MUST be calculated and manipulated
in the smallest unit of the currency (e.g. cents for USD, kobo for NGN,
pesewas for GHS) without using floating-point decimals to eliminate
rounding loss, fractional drift, and penny leakage.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, List, Union, Mapping

# ISO-4217 Currency Subunit Exponents
# Most world currencies use 2 decimals (factor 100).
# Zero-decimal currencies use factor 1.
# Three-decimal currencies use factor 1000.
CURRENCY_DECIMAL_PLACES: Dict[str, int] = {
    # 2 decimal places (Factor: 100)
    "USD": 2,  # Cent
    "EUR": 2,  # Cent
    "GBP": 2,  # Penny
    "NGN": 2,  # Kobo
    "GHS": 2,  # Pesewa
    "KES": 2,  # Cent
    "ZAR": 2,  # Cent
    "CAD": 2,  # Cent
    "AUD": 2,  # Cent
    "CHF": 2,  # Rappen / Centime
    "INR": 2,  # Paisa
    "CNY": 2,  # Fen
    "BRL": 2,  # Centavo
    "MXN": 2,  # Centavo
    "EGP": 2,  # Piastre
    "TZS": 2,  # Cent
    # Zero-decimal currencies (Factor: 1)
    "UGX": 0,  # Ugandan Shilling
    "RWF": 0,  # Rwandan Franc
    "BIF": 0,  # Burundian Franc
    "XOF": 0,  # West African CFA franc
    "XAF": 0,  # Central African CFA franc
    "JPY": 0,  # Japanese Yen
    "KRW": 0,  # South Korean Won
    "VND": 0,  # Vietnamese Dong
    "CLP": 0,  # Chilean Peso
    "PYG": 0,  # Paraguayan Guarani
    # 3 decimal places (Factor: 1000)
    "BHD": 3,  # Bahraini Dinar
    "JOD": 3,  # Jordanian Dinar
    "KWD": 3,  # Kuwaiti Dinar
    "OMR": 3,  # Omani Rial
    "TND": 3,  # Tunisian Dinar
}

DEFAULT_CURRENCY = "USD"


def get_decimal_places(currency: str = DEFAULT_CURRENCY) -> int:
    """Return the number of decimal places (exponent) for the currency."""
    code = (currency or DEFAULT_CURRENCY).upper().strip()
    return CURRENCY_DECIMAL_PLACES.get(code, 2)


def get_subunit_factor(currency: str = DEFAULT_CURRENCY) -> int:
    """Return multiplier factor from major unit to smallest subunit."""
    places = get_decimal_places(currency)
    return 10 ** places


def to_subunits(amount: Union[Decimal, float, int, str], currency: str = DEFAULT_CURRENCY) -> int:
    """
    Convert a major currency amount (e.g. 10.50 USD or 500 NGN) to integer subunits
    (e.g. 1050 cents or 50000 kobo).
    
    Uses Decimal arithmetic with ROUND_HALF_UP to avoid floating-point imprecision.
    """
    if isinstance(amount, int):
        dec_amount = Decimal(amount)
    elif isinstance(amount, Decimal):
        dec_amount = amount
    else:
        clean_str = str(amount).replace(",", "").strip()
        try:
            dec_amount = Decimal(clean_str)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid currency amount: {amount}") from exc

    factor = get_subunit_factor(currency)
    subunits_decimal = (dec_amount * Decimal(factor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(subunits_decimal)


def from_subunits(subunits: int, currency: str = DEFAULT_CURRENCY) -> Decimal:
    """
    Convert integer subunits (e.g. 1050 cents) back to a Decimal major currency amount (e.g. 10.50).
    """
    places = get_decimal_places(currency)
    factor = 10 ** places
    dec_val = Decimal(subunits) / Decimal(factor)
    if places == 0:
        return dec_val.quantize(Decimal("1"))
    elif places == 3:
        return dec_val.quantize(Decimal("0.001"))
    return dec_val.quantize(Decimal("0.01"))


def distribute_subunits_equally(total_subunits: int, count: int) -> List[int]:
    """
    Distribute total integer subunits among `count` recipients with zero fractional loss.
    Any remainder subunits (modulus) are allocated one-by-one to early recipients,
    guaranteeing sum(shares) == total_subunits.
    """
    if count <= 0:
        return []
    if total_subunits <= 0:
        return [0] * count

    base_share = total_subunits // count
    remainder = total_subunits % count

    shares = [base_share + (1 if i < remainder else 0) for i in range(count)]
    assert sum(shares) == total_subunits, "Subunit conservation invariant violated!"
    return shares


def split_subunits_by_percentages(
    total_subunits: int,
    percentages: Mapping[str, Union[Decimal, float, int]],
    remainder_key: str = "treasury",
) -> Dict[str, int]:
    """
    Split total_subunits according to percentages, assigning any rounding remainder
    to the designated `remainder_key` (typically corporate treasury) to ensure
    100% subunit conservation.
    
    Example percentages: {"squad": 60.0, "overhead": 15.0, "treasury": 25.0}
    """
    if total_subunits <= 0:
        return {k: 0 for k in percentages}

    allocated: Dict[str, int] = {}
    sum_allocated = 0

    # First allocate all non-remainder keys
    for key, pct in percentages.items():
        if key == remainder_key:
            continue
        dec_pct = Decimal(str(pct)) / Decimal("100")
        share = int((Decimal(total_subunits) * dec_pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        allocated[key] = share
        sum_allocated += share

    # Remainder key receives the exact difference to ensure zero leakage
    allocated[remainder_key] = max(0, total_subunits - sum_allocated)
    
    assert sum(allocated.values()) == total_subunits, "Subunit conservation invariant violated!"
    return allocated
