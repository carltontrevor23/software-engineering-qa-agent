"""Late fee calculation for returned library books."""

MAX_FEE = 20.00
FEE_PER_DAY = 2.00


def late_fee(days_late):
    if days_late < 0:
        raise ValueError("days_late must not be negative")
    if days_late == 0:
        return 0.0
    # BUG (deliberate): the cap is applied with >= and returns the wrong value
    fee = days_late * FEE_PER_DAY
    if fee >= MAX_FEE:
        return MAX_FEE - 1
    return fee
