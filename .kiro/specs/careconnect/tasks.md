# Implementation Plan: CareConnect

## Overview

This plan implements CareConnect incrementally on the designed stack: a FastAPI (Python 3.11) + SQLAlchemy/SQLite backend hosting the two deterministic data science engines and the appointment state machine, fronted by a React (Vite + TypeScript) SPA with three role-scoped dashboards. Testing uses `pytest` + `hypothesis`.

The build order is: backend foundation (config, SQLAlchemy models, deterministic synthetic seed, session/role auth) → credential derivation and the services that feed clean inputs (Registration, Credential, Availability, Appointment state machine, Insurance, Visit, Review) → the two DS engines (Matching, Recommendation) with property-based tests for every correctness property → REST API wiring with role enforcement → the three React dashboards → the end-to-end Boston flu demo seed and integration test. Safety constraints (credential gating, hard filters, display-only medications, verified-insurance compatibility, role-based access, consent gate, clinician license gate) are built into the services and models, not the UI.

Stretch features (Notifications R21, Live Prescriptions R22, Demand Prediction R23) are marked optional (`*`) so the core demo stays focused.

## Tasks

- [x] 1. Set up backend project foundation
  - Create the FastAPI project structure (`backend/app/` with `models/`, `services/`, `engines/`, `api/`, `tests/`)
  - Add `pyproject.toml`/`requirements.txt` with FastAPI, Uvicorn, Pydantic, SQLAlchemy, NumPy, pytest, hypothesis
  - Configure the SQLAlchemy engine/session factory against a file-based SQLite database with a transactional session dependency
  - Add a pytest configuration with an isolated in-memory/temp-file SQLite fixture
  - _Requirements: 20.1_

- [x] 2. Define the data model and database schema
  - [x] 2.1 Implement enumerations and core SQLAlchemy models
    - Define `AppointmentState {booked, accepted, completed, cancelled}`, `VerificationStatus {unverified, verified}`, `InsuranceCompatibility {compatible, incompatible, unknown}`
    - Implement `Patient`, `Volunteer`, `Clinician` tables with role, hashed password, and `location{lat,lng}`; Patient carries `consent_given` and `required_specialty`
    - Implement `Credential` (owner, type, `authorizes_service_types`, status, verifying_authority, verified_at, expires_at, `conditions[]{kind,satisfied}`) and `Service_Type` (name, `required_tests`, `required_questions`)
    - Implement `Availability_Slot`, `Appointment` (with `queued_for_review`, `reviewed`), `Questionnaire`, `Test_Result`, `Clinical_Decision`, `Referral`, `Recommended_Doctor`, `Insurance_Record`, `Medication`, and the derived `Authorized_Service` join
    - _Requirements: 1.1, 1.4, 1.5, 2.1, 2.4, 3.1, 5.1, 6.1, 8.10, 10.1, 10.3, 11.3, 12.1, 13.1, 14.1, 15.1, 16.4, 20.1_
  - [ ]* 2.2 Write unit tests for model persistence and constraints
    - Verify create/read round-trips, enum constraints, and foreign-key relationships for the core entities
    - _Requirements: 20.1_

- [x] 3. Build the deterministic synthetic data seed
  - [x] 3.1 Implement the seed script
    - Produce a fixed, deterministic dataset: Patients (with Boston-area locations, insurance records, consent), Volunteers with credentials, Clinicians with licenses, providers (`Recommended_Doctor`), insurance records, and `Service_Type` definitions (e.g., `vaccination`) with required questions/tests
    - Make all records Synthetic_Data and expose a single `seed(session)` entry point reusable by the demo and integration tests
    - _Requirements: 20.1_
  - [ ]* 3.2 Write a test asserting seed determinism
    - Seed twice into fresh databases and assert identical record counts and key fields
    - _Requirements: 20.1_

- [x] 4. Implement authentication and role-based access control
  - [x] 4.1 Implement Auth_Service
    - Implement `authenticate(email, password)` returning a session carrying the role, and `authorize(session, resource_role)` returning allow/deny
    - Implement a FastAPI dependency that validates the session, resolves the role, returns 401 for unauthenticated dashboard requests (redirect to sign-in) and 403 for wrong-role access
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 20.2_
  - [ ]* 4.2 Write example tests for role-based access
    - Each role is granted its own dashboard resource and denied the other two; unauthenticated requests are denied and redirected
    - _Requirements: 4.3, 4.4, 4.5, 4.6, 20.2_

- [x] 5. Implement Credential_Service and authorized-service derivation
  - [x] 5.1 Implement credential recording and `recompute_authorized_services`
    - Implement `record_credential` (status unverified), `verify_credential` (records authority/timestamp and adds authorized Service_Types), `revoke_or_expire` (flips to unverified, removes services authorized only by that credential), and `recompute_authorized_services` as the single pure source of truth
    - A Service_Type is authorized only when a credential authorizing it is verified AND all its recorded conditions are satisfied; role alone never authorizes vaccines/specimen/tests
    - Implement `is_clinician_license_verified`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 11.6, 13.2_
  - [x]* 5.2 Write property test for authorized-service derivation
    - **Property 6: Authorized_Services reflect only verified, condition-satisfied credentials**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.6, 5.7**

- [x] 6. Implement Registration_Service
  - [x] 6.1 Implement patient, volunteer, and clinician registration
    - Implement `register_patient` (records location, insurance, needs, pcp, and consent at creation), `register_volunteer` (records declared credentials as unverified via Credential_Service), and `register_clinician` (records license as unverified)
    - Reject missing fields by naming each missing field; reject duplicate email with account-already-exists; store all records as Synthetic_Data
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 20.1, 20.4_
  - [ ]* 6.2 Write example tests for registration validation messaging
    - Assert each missing required field is named, and duplicate-email returns account-already-exists
    - _Requirements: 1.2, 1.3, 2.3, 3.3_

- [x] 7. Implement Insurance_Service
  - [x] 7.1 Implement insurance verification and compatibility
    - New patient insurance starts unverified; a match to synthetic records sets verified; a mismatch stays unverified with a could-not-verify message
    - Implement `compatibility(patient, doctor)` returning `unknown` while the patient's insurance is unverified; network acceptance is surfaced as a caveat that does not guarantee service/home-visit coverage
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_
  - [ ]* 7.2 Write example tests for insurance verification
    - Assert verified-on-match, unverified-with-message on mismatch, and compatibility unknown while unverified against the seeded records
    - _Requirements: 14.2, 14.3, 14.4_

- [x] 8. Implement Availability_Service
  - [x] 8.1 Implement slot management
    - Implement `add_slot` (available), `remove_slot` (unavailable when unassigned, rejected with slot-has-appointment when assigned), `mark_available`/`mark_unavailable`, and `slots_for_matching`
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ]* 8.2 Write unit tests for slot management
    - Cover add/remove, rejection of removing an assigned slot, and exposure of available slots
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 9. Implement the appointment lifecycle state machine
  - [x] 9.1 Implement the transition table and `transition`
    - Encode the valid transition allow-list (booked→accepted, booked→cancelled, booked→completed, accepted→completed, accepted→cancelled); reject any other transition, preserve current state, return invalid-transition
    - Bind side effects: decline/cancel return the slot to available; `*→completed` queues for clinician review; recorded state is always exactly one of the four
    - _Requirements: 8.6, 8.7, 8.8, 8.9, 8.10_
  - [x]* 9.2 Write property test for appointment transitions
    - **Property 7: Appointment transitions follow only the valid transition graph**
    - **Validates: Requirements 8.6, 8.7, 8.8, 8.9, 8.10**

- [x] 10. Implement Appointment_Service booking and preconditions
  - [x] 10.1 Implement `book` with safety gates and transactional slot lock
    - Require an available slot, the requested Service_Type in the Volunteer's current Authorized_Services, and recorded Patient consent; reject otherwise with slot-unavailable / not-authorized / consent-required
    - Mark the slot unavailable transactionally before returning booking-confirmed to close the concurrent-booking race
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 20.4_
  - [ ]* 10.2 Write property test for the consent gate
    - **Property 8: Booking requires recorded consent**
    - **Validates: Requirements 8.5, 20.4**
  - [ ]* 10.3 Write integration test for the concurrent-booking race
    - Simulate two bookings of the same slot in one transaction window; exactly one succeeds and the other receives slot-unavailable
    - _Requirements: 8.2, 8.3_

- [ ] 11. Checkpoint - foundation and core services
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implement Visit_Service
  - [x] 12.1 Implement visit detail and data capture with gating
    - Implement `visit_detail` (requested service + location, only the Volunteer's authorized services) and `submit_questionnaire`/`submit_test_result`
    - Allow entry only for authorized services and only in the `accepted` state; reject unauthorized services (retain prior data) and wrong-state submissions (return current state); reject questionnaires missing required questions by naming each; treat Test_Result as information only
    - When all required questionnaire questions and required test results for the Service_Type are present, ask Appointment_Service to transition to `completed` and queue for review
    - _Requirements: 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 13.3, 13.4_
  - [ ]* 12.2 Write property test for completion trigger
    - **Property 9: Completion occurs exactly when required visit data is present**
    - **Validates: Requirements 10.5**
  - [ ]* 12.3 Write unit tests for visit data gating
    - Cover unauthorized-service rejection (prior data retained), wrong-state rejection (current state returned), and missing-required-question messaging
    - _Requirements: 9.3, 10.2, 10.4, 10.6_

- [x] 13. Implement Review_Service and medication display rules
  - [x] 13.1 Implement clinician review, decisions, referrals, and medication gating
    - Implement `open_for_review` (only completed+queued; else not-ready), `record_decision` (non-empty stored and marked reviewed; empty rejected; unverified license discarded with not-verified), `approve_decision` (nothing-to-approve when no decision), and `issue_referral` (records specialty and sets the Patient's `required_specialty`)
    - Withhold decisions/referrals from the Patient until approved; create Medication only via a verified Clinician and display only when approved; never derive a prescription from a Test_Result, Questionnaire, or automation
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 12.1, 12.2, 13.1, 13.2, 13.4, 13.5_
  - [ ]* 13.2 Write property test for approval-gated decision visibility
    - **Property 10: Clinical decisions are visible to the patient exactly when approved**
    - **Validates: Requirements 11.8, 11.9**
  - [ ]* 13.3 Write property test for medication display rules
    - **Property 11: Displayed medications are verified-prescribed and approved**
    - **Validates: Requirements 13.1, 13.5**
  - [ ]* 13.4 Write example tests for the no-automated-prescribing guarantee
    - Assert prescription creation from a non-verified clinician, a Test_Result, a Questionnaire, or an automated component is rejected and not persisted
    - _Requirements: 13.2, 13.4_

- [x] 14. Implement the Matching_Engine
  - [x] 14.1 Implement hard filters, normalization, scoring, and tie-break
    - Apply the authorization filter (service in credential-derived Authorized_Services) and availability filter (slot covers the full chosen duration); return empty + no-qualified-volunteers when the candidate set is empty
    - Extract proximity (haversine), availability, and qualification features; min-max normalize each to [0,1] with 1.0 most favorable (invert proximity; all-equal → 1.0 for all); score `w_prox·D + w_avail·A + w_qual·Q`; sort descending with tie-break (higher qualification, then nearer proximity, then earliest slot)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_
  - [x]* 14.2 Write property test for the authorization hard filter
    - **Property 1: Matching never returns an unauthorized volunteer**
    - **Validates: Requirements 7.1, 7.7**
  - [ ]* 14.3 Write property test for the availability hard filter
    - **Property 2: Matching only returns volunteers with a covering available slot**
    - **Validates: Requirements 7.2**
  - [ ]* 14.4 Write property test for matching feature normalization
    - **Property 3: Matching features normalize into range**
    - **Validates: Requirements 7.3**
  - [ ]* 14.5 Write property test for matching ranking determinism
    - **Property 4: Matching ranking is ordered and deterministic**
    - **Validates: Requirements 7.4, 7.5**
  - [ ]* 14.6 Write property test for the empty-result condition
    - **Property 5: Matching returns empty exactly when no volunteer qualifies**
    - **Validates: Requirements 7.6**

- [x] 15. Implement the Recommendation_Engine
  - [x] 15.1 Implement preprocessing, hard filters, weighted scoring, ranking, and cap
    - Preprocess provider Synthetic_Data (clean/repair malformed records, coerce types, bound ratings) and compute haversine proximity before normalization
    - Apply hard filters in order: required specialty must exist (else no-required-specialty), exact specialty match, and verified-insurance compatibility; return empty + no-compatible-doctors when none pass; never assert compatibility while insurance is unverified
    - Validate configured weights (each in [0,1], sum 1.0±0.001) and fall back to defaults `(0.40,0.30,0.20,0.10)` with an invalid-weights message; normalize D,A,R,T to [0,1] (invert distance and travel time; all-equal → 1.0); score `S=0.40·D+0.30·A+0.20·R+0.10·T`; sort descending with tie-break by ascending proximity within 0.001; cap at 50
    - _Requirements: 12.2, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9, 16.10_
  - [ ]* 15.2 Write property test for insurance-unknown while unverified
    - **Property 12: Insurance compatibility is unknown while insurance is unverified**
    - **Validates: Requirements 14.4, 15.4**
  - [x]* 15.3 Write property test for the recommendation hard filters
    - **Property 13: Recommendation never returns a doctor failing a hard filter**
    - **Validates: Requirements 15.1, 15.2, 15.3, 16.10**
  - [ ]* 15.4 Write property test for recommendation empty conditions
    - **Property 14: Recommendation returns empty exactly when filters pass no one**
    - **Validates: Requirements 15.5, 15.6**
  - [ ]* 15.5 Write property test for the result cap
    - **Property 15: Recommendation result size is capped at 50**
    - **Validates: Requirements 15.7**
  - [ ]* 15.6 Write property test for recommendation factor normalization
    - **Property 16: Recommendation factors normalize into range with degenerate handling**
    - **Validates: Requirements 16.1, 16.2, 16.3, 16.9**
  - [ ]* 15.7 Write property test for recommendation ranking determinism
    - **Property 17: Recommendation ranking is ordered and deterministic**
    - **Validates: Requirements 16.5, 16.6**
  - [ ]* 15.8 Write property test for weight validation
    - **Property 18: Scoring weights always normalize**
    - **Validates: Requirements 16.7, 16.8**

- [ ] 16. Checkpoint - services and DS engines
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 17. Wire the REST API with role enforcement
  - [ ] 17.1 Implement auth and registration routes
    - Expose sign-in/session routes and patient/volunteer/clinician registration routes behind the Auth_Service dependency
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 4.2, 4.6_
  - [x] 17.2 Implement patient-facing routes
    - Expose match-request, booking, approved decisions/referrals, medication display, and doctor-recommendation routes, each role-gated to Patient
    - _Requirements: 4.3, 7.1, 8.1, 11.9, 13.1, 15.1, 16.1, 20.2_
  - [x] 17.3 Implement volunteer-facing routes
    - Expose availability management, appointment accept/decline, and questionnaire/test-result submission routes, each role-gated to Volunteer
    - _Requirements: 4.4, 6.1, 8.6, 9.1, 10.1, 10.3, 20.2_
  - [x] 17.4 Implement clinician-facing routes
    - Expose review-queue, findings view, decision/referral recording, and approval routes, each role-gated to Clinician
    - _Requirements: 4.5, 11.1, 11.3, 12.1, 11.9, 20.2_
  - [ ]* 17.5 Write integration tests for role-gated routes
    - Assert each route rejects callers of the wrong role and serves the correct role end-to-end over the seeded data
    - _Requirements: 4.3, 4.4, 4.5, 20.2_

- [x] 18. Build the React frontend foundation
  - [x] 18.1 Scaffold the Vite + TypeScript SPA with routing and auth
    - Create the Vite/TS app, a typed API client, React Router with role-scoped routes, a sign-in screen, and session handling that redirects unauthenticated users to sign-in
    - _Requirements: 4.1, 4.2, 4.6_

- [x] 19. Implement the Patient_Dashboard
  - [x] 19.1 Build patient dashboard views
    - Show upcoming appointments with lifecycle states; provide the request-match-and-book flow (with consent gate surfaced); display only approved decisions/referrals and approved medications; render ranked Recommended_Doctors with proximity, specialty, and insurance-compatibility status
    - _Requirements: 13.1, 17.1, 17.2, 17.3, 17.4_
  - [ ]* 19.2 Write component tests for the patient dashboard
    - Assert only approved decisions/medications render and recommendations show required fields
    - _Requirements: 17.1, 17.3, 17.4_

- [x] 20. Implement the Volunteer_Dashboard
  - [x] 20.1 Build volunteer dashboard views
    - Show assigned appointments with states; availability set/remove interface; accept appointments and submit questionnaires/test results; display per appointment only the Volunteer's authorized services
    - _Requirements: 18.1, 18.2, 18.3, 18.4_
  - [ ]* 20.2 Write component tests for the volunteer dashboard
    - Assert only authorized services are offered for data entry per appointment
    - _Requirements: 18.4_

- [x] 21. Implement the Clinician_Dashboard
  - [x] 21.1 Build clinician dashboard views
    - Show the completed-and-queued review queue; view submitted questionnaires/test results; record decisions and issue referrals; mark decisions approved for patient visibility
    - _Requirements: 19.1, 19.2, 19.3, 19.4_
  - [ ]* 21.2 Write component tests for the clinician dashboard
    - Assert only completed+queued appointments appear and approval controls gate visibility
    - _Requirements: 19.1, 19.4_

- [x] 22. Wire the end-to-end Boston flu demo scenario
  - [x] 22.1 Implement the demo integration test over the seeded data
    - Drive the full journey: register Boston patient (insurance verified, consent) → request flu-vaccination match → book top authorized volunteer (slot locked) → volunteer accepts → record questionnaire + flu test result → auto-complete and queue → clinician reviews, records and approves a decision, issues a referral (sets required specialty) → patient views ranked compatible specialists
    - Assert each stage's expected state and that the safety gates (authorization, consent, verified insurance, approval) hold end-to-end
    - _Requirements: 7.1, 8.1, 8.6, 10.5, 11.3, 11.9, 12.2, 15.1, 16.1, 17.4_

- [ ] 23. Final checkpoint - full journey
  - Ensure all tests pass, ask the user if questions arise.

- [ ]* 24. Implement stretch features (optional)
  - [ ]* 24.1 Implement automated notifications
    - Emit notifications on appointment acceptance, decision approval, and volunteer assignment
    - _Requirements: 21.1, 21.2, 21.3_
  - [ ]* 24.2 Implement live prescription integration
    - Transmit a verified-clinician prescription to a configured external system; on unavailability, record locally and return integration-unavailable; keep creation restricted to authorized clinicians
    - _Requirements: 22.1, 22.2, 22.3_
  - [ ]* 24.3 Implement healthcare demand prediction
    - Analyze synthetic appointment history by geographic area, produce a Demand_Forecast per area, and rank areas by predicted volunteer shortfall
    - _Requirements: 23.1, 23.2, 23.3, 23.4_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP; stretch requirements (21–23) are entirely optional (task 24).
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation at natural boundaries.
- Property-based tests (Properties 1–18) validate the universal invariants of the two DS engines, credential derivation, and the appointment state machine; each runs at least 100 iterations with `hypothesis` and is tagged `# Feature: careconnect, Property {number}: {property_text}`.
- Example and integration tests cover role access, the concurrent-booking race, the no-automated-prescribing guarantee, validation messaging, insurance verification, and the dashboards.
- Safety constraints are enforced in the services and models (credential gating, hard filters, display-only medications, verified-insurance compatibility, role-based access, consent gate, clinician license gate), not in the UI.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.1"] },
    { "id": 3, "tasks": ["3.2", "4.2", "5.1", "8.1"] },
    { "id": 4, "tasks": ["5.2", "6.1", "7.1", "8.2", "9.1"] },
    { "id": 5, "tasks": ["6.2", "7.2", "9.2", "10.1", "14.1", "15.1"] },
    { "id": 6, "tasks": ["10.2", "10.3", "12.1", "13.1", "14.2", "14.3", "14.4", "14.5", "14.6", "15.2", "15.3", "15.4", "15.5", "15.6", "15.7", "15.8"] },
    { "id": 7, "tasks": ["12.2", "12.3", "13.2", "13.3", "13.4", "17.1", "17.2", "17.3", "17.4"] },
    { "id": 8, "tasks": ["17.5", "18.1"] },
    { "id": 9, "tasks": ["19.1", "20.1", "21.1"] },
    { "id": 10, "tasks": ["19.2", "20.2", "21.2", "22.1"] },
    { "id": 11, "tasks": ["24.1", "24.2", "24.3"] }
  ]
}
```
