---
feature: [FEATURE_NAME]
created: [CREATED_DATE]
---

# Pre-Implementation Checklist: [FEATURE_NAME]

## Spec Quality

- [ ] All user stories have GIVEN/WHEN/THEN acceptance scenarios
- [ ] All functional requirements have `<epistemic-status>` labels
- [ ] Success criteria are measurable and falsifiable
- [ ] Edge cases are enumerated
- [ ] Main Contradiction is clearly identified
- [ ] Out of Scope is explicitly documented
- [ ] No `[NEEDS CLARIFICATION]` markers remain (all resolved in clarify phase)

## Constitution Compliance

- [ ] Plan references constitution version `[VERSION]`
- [ ] All constitutional principles checked (pass or justified violation)
- [ ] No unjustified violations (must be 0)
- [ ] Complexity Tracking table filled for any justified violations

## Plan Quality

- [ ] Architecture overview shows before/after
- [ ] Source graph lists all affected files with dependency order
- [ ] Each implementation step has: file(s), change, rollback, test
- [ ] Verification plan covers unit, integration, manual, and regression

## Task Quality

- [ ] Tasks are grouped by user story
- [ ] Each user story is independently testable
- [ ] Task dependencies are explicit
- [ ] Parallelizable tasks marked with `[P]`
- [ ] Checkpoints defined after each phase
- [ ] Implementation strategy selected (MVP First / Incremental / Parallel)

## Risk Assessment

- [ ] Breaking changes identified and documented
- [ ] Data migration plan (if needed)
- [ ] Rollback plan for each step
- [ ] External dependencies confirmed available
- [ ] Performance implications considered

## Gate Decision

- [ ] **ALL ITEMS PASSED** — Ready for `/speckit.implement`
- [ ] **SOME ITEMS FAILED** — See notes below before proceeding

## Notes

[Any items that need attention, waivers, or follow-up]
