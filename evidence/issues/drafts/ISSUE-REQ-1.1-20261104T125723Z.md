# Late fee calculation incorrectly capped

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

- `sandbox.generated.test_req_1_1_8e374c7a::test_fee_capped_at_maximum_exact_boundary`
- `sandbox.generated.test_req_1_1_8e374c7a::test_fee_capped_at_maximum_exceeded_boundary`

## Summary

Late fee calculation does not cap at $20.00 as specified. For 10 and 11 late days, the function returns $19.00 instead of the expected $20.00.

---
_Drafted by Inspectra QA agent - not filed._
