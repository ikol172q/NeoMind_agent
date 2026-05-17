---
feature: [FEATURE_NAME]
plan: [PATH_TO_PLAN_MD]
total_tasks: [N]
created: [CREATED_DATE]
---

# Tasks: [FEATURE_NAME]

Inputs: `plan.md` (required), `spec.md`, `research.md`, `data-model.md`, `contracts/`

Tasks are grouped by user story for independent implementation and testing.
Format: `[ID] [P?] [Story] Description`
- `[P]` = parallelizable (different files, no shared dependencies)
- `[Story]` = maps to user story label (US1, US2, US3)

---

## Phase 1: Setup (Shared Infrastructure)

Project initialization and shared dependencies.

- [ ] T001 [P] Create project structure per plan.md
- [ ] T002 [P] Initialize/verify dependencies and tooling
- [ ] T003 [P] Configure linting, formatting, type checking

## Phase 2: Foundational (Blocking Prerequisites)

⚠️ CRITICAL — No user story work begins until this phase is complete.

- [ ] T004 [P] Database schema / data model setup
- [ ] T005 [P] Core infrastructure (routing, middleware, error handling)
- [ ] T006 [P] Environment configuration and secrets management
- [ ] T007 Base models / entities / types shared across user stories

**Checkpoint**: Foundation ready — user story implementation can now begin.

## Phase 3: User Story 1 — [US1_TITLE] (Priority: P1) 🎯 MVP

**Goal**: [One sentence describing what US1 delivers]

**Independent Test**: [How to verify US1 works on its own without other stories]

### Tests for User Story 1

- [ ] T008 [P] [US1] Contract/integration test for [US1 endpoint/behavior]
- [ ] T009 [P] [US1] Unit tests for [US1 core logic]

### Implementation for User Story 1

- [ ] T010 [US1] Create [model/entity/types] in `[file_path]`
- [ ] T011 [US1] Implement [core service/logic] in `[file_path]`
- [ ] T012 [US1] Implement [endpoint/interface] in `[file_path]`
- [ ] T013 [US1] Add validation and error handling
- [ ] T014 [US1] Add logging / observability

**Checkpoint**: User Story 1 complete and independently testable.

## Phase 4: User Story 2 — [US2_TITLE] (Priority: P2)

**Goal**: [One sentence describing what US2 delivers]

**Independent Test**: [How to verify US2 works on its own]

### Tests for User Story 2

- [ ] T015 [P] [US2] Contract/integration test for [US2 endpoint/behavior]
- [ ] T016 [P] [US2] Unit tests for [US2 core logic]

### Implementation for User Story 2

- [ ] T017 [US2] Create [model/entity/types] in `[file_path]`
- [ ] T018 [US2] Implement [core service/logic] in `[file_path]`
- [ ] T019 [US2] Integration with US1 [if applicable]

**Checkpoint**: User Stories 1 AND 2 both working independently.

## Phase 5: User Story 3 — [US3_TITLE] (Priority: P3)

**Goal**: [One sentence describing what US3 delivers]

**Independent Test**: [How to verify US3 works on its own]

### Tests for User Story 3

- [ ] T020 [P] [US3] Contract/integration test for [US3 endpoint/behavior]
- [ ] T021 [P] [US3] Unit tests for [US3 core logic]

### Implementation for User Story 3

- [ ] T022 [US3] Create [model/entity/types] in `[file_path]`
- [ ] T023 [US3] Implement [core service/logic] in `[file_path]`

**Checkpoint**: All user stories complete.

<!-- Add more user story phases as needed -->

## Phase N: Polish & Cross-Cutting Concerns

- [ ] T024 [P] Documentation updates
- [ ] T025 [P] Code cleanup and refactoring
- [ ] T026 [P] Additional unit tests (edge cases)
- [ ] T027 Security hardening review
- [ ] T028 Quickstart / developer guide validation

---

## Dependencies & Execution Order

### Phase Dependencies
- **Setup**: No dependencies
- **Foundational**: Depends on Setup — blocks ALL user stories
- **User Stories**: All depend on Foundational; may optionally depend on earlier stories
- **Polish**: Depends on all desired user stories being complete

### Within Each User Story
- Tests MUST be written and verified to FAIL before implementation
- Models / types BEFORE services
- Services BEFORE endpoints / interfaces
- Core implementation BEFORE integration with other stories
- Story MUST be complete (with passing tests) before moving to next priority

### Parallel Opportunities
- All `[P]` tasks within the same phase can run concurrently
- Different user stories can be worked on in parallel once Foundational is done
- Tests for the same user story can be written in parallel

---

## Implementation Strategy

1. **MVP First**: Phase 1 → Phase 2 → Phase 3 (US1), then STOP AND VALIDATE
2. **Incremental Delivery**: Foundation → US1 → validate → US2 → validate → US3 → validate
3. **Parallel Team**: Setup + Foundational together → split US1/US2/US3 across workers

**Recommended**: MVP First for most features.

## Notes

- `[P]` tasks touch different files with no shared dependencies — safe to parallelize
- `[Story]` label (US1/US2/US3) provides traceability from task back to spec user story
- Each user story should be independently completable and testable
- Write tests FIRST, verify they fail, THEN implement
- Commit after each task or logical group of tasks
- Validate at every Checkpoint before proceeding
- Avoid vague tasks ("refactor codebase") or hidden cross-story dependencies
