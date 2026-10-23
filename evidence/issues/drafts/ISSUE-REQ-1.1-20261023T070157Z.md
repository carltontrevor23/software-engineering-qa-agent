# Late Fee Capping Bug in late_fee Function

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

- `sandbox.generated.test_req_1_1_794523bf::test_fee_at_exact_cap_boundary`
- `sandbox.generated.test_req_1_1_794523bf::test_fee_just_above_cap_boundary`
- `sandbox.generated.test_req_1_1_794523bf::test_fee_exceeding_cap_is_capped`

## Summary

Late fee calculation does not cap at $20 as specified in REQ-1.1. The function returns $19.0 for amounts that should trigger the cap.

---
_Drafted by Inspectra QA agent - not filed._
