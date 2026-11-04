# Bug: Late fee cap incorrectly implemented

**Requirement:** REQ-1.1 (examples/library/requirements/library.md)

> ## Section 1.1: Late Fees
> Feature: Late fee calculation
>
> Acceptance Criteria:
> 1. A book returned on or before its due day has a late fee of 0.
> 2. A book returned after the due day costs 2.00 per late day.
> 3. The fee is capped at 20.00 per book.
> 4. A negative number of late days raises ValueError.

## Failing tests

- `sandbox.generated.test_req_1_1_dd6d4393::test_fee_at_cap`

## Summary

Late fee calculation fails to correctly apply cap at $20.00 per book.

---
_Drafted by Inspectra QA agent - not filed._
