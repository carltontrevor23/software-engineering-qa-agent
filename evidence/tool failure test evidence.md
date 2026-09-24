# Tool Failure and Authorization Test Evidence (Week 4)

**Project:** Software-Engineering QA Agent (Inspectra)  
**Deliverable:** Week 4 Activity 4 (Failure/Authorization Test Evidence)  
**Target:** `src/tool_calling.py`  
**Test Suite:** `tests/test_tool_failures.py`  

---

### 1. Test Summary Matrix

| ID | Test Category | Scenario | Input / Mock Condition | Expected Result | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TF-01** | Missing Parameter | Missing `user_id` on status lookup | `get_user_subscription_status.invoke({})` | Raises LangChain/Pydantic `ValidationError` | **PASS** |
| **TF-02** | Missing Parameter | Missing `user_id` on upgrade | `upgrade_user_subscription.invoke({})` | Raises LangChain/Pydantic `ValidationError` | **PASS** |
| **TF-03** | Missing Parameter | Invalid parameter type | `user_id = 12345` (integer instead of string) | Raises `ValidationError` | **PASS** |
| **TF-04** | Unavailable Service | API Network Timeout | `requests.get` raises `Timeout` | Exception captured / surfaced | **PASS** |
| **TF-05** | Unavailable Service | API HTTP 500 Server Error | `requests.get` returns HTTP 500 | Tool returns `{"status": "error", "error": "User not found."}` | **PASS** |
| **TF-06** | Unauthorized / 404 | User lookup on non-existent account | `requests.get` returns HTTP 404 | Tool returns `{"status": "error", "error": "User not found."}` | **PASS** |
| **TF-07** | Unauthorized / 404 | Upgrade on non-existent account | `requests.get` returns HTTP 404 | Tool returns `{"status": "error", "error": "User not found."}` | **PASS** |
| **TF-08** | Unexpected State | Upgrade on inactive/suspended user | Status = `"suspended"`, Balance = $150.00 | Tool returns `{"status": "error", "error": "User account is not active."}` | **PASS** |
| **TF-09** | Unexpected State | Upgrade on insufficient funds | Status = `"active"`, Balance = $25.50 | Tool returns `{"status": "error", "error": "User balance is below the required threshold."}` | **PASS** |
| **TF-10** | Unexpected State | Exact boundary condition ($49.99) | Status = `"active"`, Balance = $49.99 | Tool returns `{"status": "error", "error": "User balance is below the required threshold."}` | **PASS** |

---

### 2. Execution Log (Evidence Output)

```text
 python -m pytest tests/test_tool_failures.py -v
=================================================================== test session starts ====================================================================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\PC 12\Desktop\AWS\venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\PC 12\Desktop\QA_agent\software-engineering-qa-agent
plugins: anyio-4.13.0, langsmith-0.14.0
collected 10 items                                                                                                                                          

tests/test_tool_failures.py::test_missing_parameter_status_lookup PASSED                                                                              [ 10%]
tests/test_tool_failures.py::test_missing_parameter_upgrade PASSED                                                                                    [ 20%]
tests/test_tool_failures.py::test_invalid_parameter_type PASSED                                                                                       [ 30%]
tests/test_tool_failures.py::test_service_unavailable_timeout PASSED                                                                                  [ 40%]
tests/test_tool_failures.py::test_service_unavailable_500_server_error PASSED                                                                         [ 50%]
tests/test_tool_failures.py::test_unauthorized_user_lookup_404 PASSED                                                                                 [ 60%]
tests/test_tool_failures.py::test_unauthorized_upgrade_404 PASSED                                                                                     [ 70%]
tests/test_tool_failures.py::test_unexpected_response_inactive_user PASSED                                                                            [ 80%]
tests/test_tool_failures.py::test_unexpected_response_insufficient_funds PASSED                                                                       [ 90%]
tests/test_tool_failures.py::test_unexpected_response_boundary_balance PASSED                                                                         [100%]

===================================================================== warnings summary =====================================================================
..\..\AWS\venv\Lib\site-packages\google\genai\types.py:42
  C:\Users\PC 12\Desktop\AWS\venv\Lib\site-packages\google\genai\types.py:42: DeprecationWarning: '_UnionGenericAlias' is deprecated and slated for removal in Python 3.17
    VersionedUnionType = Union[builtin_types.UnionType, _UnionGenericAlias]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
============================================================== 10 passed, 1 warning in 4.39s ===============================================================