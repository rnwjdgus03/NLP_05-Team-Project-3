# V39 fixed Top-30 candidate

"

    "V39 changes no learned score weights from the frozen V36 engine. It expands the fixed Stage-A "
    "blend from Top-12 to Top-30 and raises the Stage-B coordinate beam from 300 to 400. Stage B still "
    "preserves one review-only coordinate per Stage-A table; Stage C keeps the frozen ITEM/OBJ scope, "
    "ratio, period, and unit safety rules. No expanded candidate becomes READY without KOSIS API "
    "verification.

"
    "Development evidence on table-disjoint v38 dev300: API-exact multigold ITEM Top-5 75.33%, "
    "coordinate/full Top-5 71.67%, VERIFIED_MATCH 197/300. This is development evidence only. "
    "V37 claim/gold rows were not used for v38 tuning; prior table IDs were exclusions only. "
    "A new blind100 must be selected after this freeze and evaluated exactly once.
"
