# Late fee calculation fails to cap at maximum fee

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

- `sandbox.generated.test_req_1_1_2d3ecd91::test_fee_at_cap_boundary`
- `sandbox.generated.test_req_1_1_2d3ecd91::test_fee_above_cap_boundary`

## Summary

Late fee calculation does not correctly cap at $20.00. The function returns $19.00 when the computed fee is $20.00 or higher.

---
_Drafted by Inspectra QA agent - not filed._
