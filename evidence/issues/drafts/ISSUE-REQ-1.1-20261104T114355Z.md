# Late fee cap implementation incorrect

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

- `sandbox.generated.test_req_1_1_39a7d558::test_cap_boundary_late_fee`
- `sandbox.generated.test_req_1_1_39a7d558::test_above_cap_late_fee`

## Summary

Late fee calculation does not correctly apply the 20.00 cap for 10 or more late days.

---
_Drafted by Inspectra QA agent - not filed._
