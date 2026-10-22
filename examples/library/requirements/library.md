# Library Lending

## Section 1.1: Late Fees
Feature: Late fee calculation

Acceptance Criteria:
1. A book returned on or before its due day has a late fee of 0.
2. A book returned after the due day costs 2.00 per late day.
3. The fee is capped at 20.00 per book.
4. A negative number of late days raises ValueError.
