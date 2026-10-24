/**
 * Component tests for the patient dashboard sections (task 19.2).
 *
 * The approval/verification gates are enforced server-side, so these sections
 * render exactly what `api/patient` returns. We therefore mock that module with
 * `vi.mock` and assert the rendered output reflects the controlled data:
 *
 *  - ApprovedCareSection renders the approved decisions/referrals/medications
 *    the API returns, and shows empty-state copy for empty lists (R17.3).
 *  - RecommendationsSection renders recommended doctors with their required
 *    fields: name, specialty, proximity, insurance-compatibility status (R17.4).
 *  - AppointmentsSection renders appointments with their lifecycle states (R17.1).
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  Appointment,
  Decision,
  Medication,
  RecommendationResponse,
  RecommendedDoctor,
  Referral,
} from "../../api/patient";

// Mock the whole patient API module. Every function is a vi.fn() we configure
// per test; the components call these and render the resolved data.
vi.mock("../../api/patient", () => ({
  listAppointments: vi.fn(),
  listDecisions: vi.fn(),
  listReferrals: vi.fn(),
  listMedications: vi.fn(),
  getRecommendations: vi.fn(),
  requestMatch: vi.fn(),
  bookVisit: vi.fn(),
  bookingErrorMessage: vi.fn(),
}));

import {
  getRecommendations,
  listAppointments,
  listDecisions,
  listMedications,
  listReferrals,
} from "../../api/patient";
import { AppointmentsSection } from "./AppointmentsSection";
import { ApprovedCareSection } from "./ApprovedCareSection";
import { RecommendationsSection } from "./RecommendationsSection";

const mockListAppointments = vi.mocked(listAppointments);
const mockListDecisions = vi.mocked(listDecisions);
const mockListReferrals = vi.mocked(listReferrals);
const mockListMedications = vi.mocked(listMedications);
const mockGetRecommendations = vi.mocked(getRecommendations);

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// ApprovedCareSection — R17.3: show exactly what the approved-only API returns
// ---------------------------------------------------------------------------

describe("ApprovedCareSection (R17.3)", () => {
  it("renders the approved decisions, referrals, and medications the API returns", async () => {
    const decisions: Decision[] = [
      { id: 1, appointment_id: 10, content: "Flu shot administered; no adverse reaction.", approved: true },
      { id: 2, appointment_id: 11, content: "Recommend annual booster next season.", approved: true },
    ];
    const referrals: Referral[] = [
      { id: 5, appointment_id: 10, specialty: "Cardiology" },
    ];
    const medications: Medication[] = [
      { id: 7, name: "Oseltamivir 75mg", approved: true },
    ];

    mockListDecisions.mockResolvedValue(decisions);
    mockListReferrals.mockResolvedValue(referrals);
    mockListMedications.mockResolvedValue(medications);

    render(<ApprovedCareSection />);

    // Decisions render verbatim.
    await screen.findByText("Flu shot administered; no adverse reaction.");
    expect(
      screen.getByText("Recommend annual booster next season."),
    ).toBeInTheDocument();

    // Referral renders with its specialty.
    const referralItem = screen.getByText("Cardiology").closest("li");
    expect(referralItem).not.toBeNull();
    expect(referralItem).toHaveTextContent("Referral to");
    expect(referralItem).toHaveTextContent("Cardiology");

    // Medication renders by name.
    expect(screen.getByText("Oseltamivir 75mg")).toBeInTheDocument();

    // No empty-state copy appears when data is present.
    expect(screen.queryByText("No approved decisions yet.")).not.toBeInTheDocument();
    expect(screen.queryByText("No approved referrals yet.")).not.toBeInTheDocument();
    expect(screen.queryByText("No approved medications.")).not.toBeInTheDocument();
  });

  it("shows empty-state copy for each list when the API returns nothing", async () => {
    mockListDecisions.mockResolvedValue([]);
    mockListReferrals.mockResolvedValue([]);
    mockListMedications.mockResolvedValue([]);

    render(<ApprovedCareSection />);

    expect(await screen.findByText("No approved decisions yet.")).toBeInTheDocument();
    expect(screen.getByText("No approved referrals yet.")).toBeInTheDocument();
    expect(screen.getByText("No approved medications.")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// RecommendationsSection — R17.4: required fields on each recommended doctor
// ---------------------------------------------------------------------------

describe("RecommendationsSection (R17.4)", () => {
  it("renders recommended doctors with name, specialty, proximity, and insurance status", async () => {
    const doctors: RecommendedDoctor[] = [
      {
        id: 101,
        name: "Dr. Ada Chen",
        specialty: "Family Medicine",
        rating: 4.6,
        proximity_km: 2.3,
        score: 0.91,
        insurance_status: "compatible",
      },
      {
        id: 102,
        name: "Dr. Omar Patel",
        specialty: "Internal Medicine",
        rating: null,
        proximity_km: 5.0,
        score: 0.74,
        insurance_status: "unknown",
      },
    ];
    const response: RecommendationResponse = {
      doctors,
      message: null,
      insurance_asserted: true,
    };
    mockGetRecommendations.mockResolvedValue(response);

    render(<RecommendationsSection />);

    // Name.
    const firstRow = (await screen.findByText(/Dr\. Ada Chen/)).closest("li")!;
    const secondRow = screen.getByText(/Dr\. Omar Patel/).closest("li")!;

    // Specialty + proximity in the first row.
    expect(firstRow).toHaveTextContent("Family Medicine");
    expect(firstRow).toHaveTextContent("2.3 km away");
    // Insurance-compatibility status.
    expect(within(firstRow).getByText("Insurance compatible")).toBeInTheDocument();

    // Second row: specialty, proximity, and the unknown/unverified status.
    expect(secondRow).toHaveTextContent("Internal Medicine");
    expect(secondRow).toHaveTextContent("5.0 km away");
    expect(within(secondRow).getByText("Insurance unverified")).toBeInTheDocument();
  });

  it("renders incompatible insurance status verbatim from the engine", async () => {
    const response: RecommendationResponse = {
      doctors: [
        {
          id: 200,
          name: "Dr. Lee",
          specialty: "Pediatrics",
          rating: 4.0,
          proximity_km: 1.0,
          score: 0.5,
          insurance_status: "incompatible",
        },
      ],
      message: null,
      insurance_asserted: true,
    };
    mockGetRecommendations.mockResolvedValue(response);

    render(<RecommendationsSection />);

    const row = (await screen.findByText(/Dr\. Lee/)).closest("li")!;
    expect(row).toHaveTextContent("Pediatrics");
    expect(row).toHaveTextContent("1.0 km away");
    expect(within(row).getByText("Insurance incompatible")).toBeInTheDocument();
  });

  it("surfaces the engine advisory message when there are no doctors", async () => {
    const response: RecommendationResponse = {
      doctors: [],
      message: "No compatible doctors found for your required specialty.",
      insurance_asserted: false,
    };
    mockGetRecommendations.mockResolvedValue(response);

    render(<RecommendationsSection />);

    expect(
      await screen.findByText(
        "No compatible doctors found for your required specialty.",
      ),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AppointmentsSection — R17.1: appointments with their lifecycle states
// ---------------------------------------------------------------------------

describe("AppointmentsSection (R17.1)", () => {
  it("renders appointments with their lifecycle state labels", async () => {
    const appointments: Appointment[] = [
      {
        id: 1,
        volunteer_id: 50,
        service_type: "vaccination",
        state: "booked",
        slot_start: "2025-01-10T09:00:00Z",
        slot_end: "2025-01-10T09:30:00Z",
        queued_for_review: false,
        reviewed: false,
      },
      {
        id: 2,
        volunteer_id: 51,
        service_type: "screening",
        state: "accepted",
        slot_start: "2025-01-11T10:00:00Z",
        slot_end: "2025-01-11T10:30:00Z",
        queued_for_review: false,
        reviewed: false,
      },
      {
        id: 3,
        volunteer_id: 52,
        service_type: "follow-up",
        state: "completed",
        slot_start: "2025-01-12T11:00:00Z",
        slot_end: "2025-01-12T11:30:00Z",
        queued_for_review: true,
        reviewed: false,
      },
      {
        id: 4,
        volunteer_id: 53,
        service_type: "vaccination",
        state: "cancelled",
        slot_start: "2025-01-13T12:00:00Z",
        slot_end: "2025-01-13T12:30:00Z",
        queued_for_review: false,
        reviewed: false,
      },
    ];
    mockListAppointments.mockResolvedValue(appointments);

    render(<AppointmentsSection reloadKey={0} />);

    // Each appointment's service type renders.
    const bookedRow = (await screen.findByText("screening")).closest("li");
    expect(bookedRow).not.toBeNull();

    // Each lifecycle state label is shown.
    expect(screen.getByText("booked")).toBeInTheDocument();
    expect(screen.getByText("accepted")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("cancelled")).toBeInTheDocument();

    // The completed appointment row carries its state pill.
    const completedRow = screen.getByText("follow-up").closest("li")!;
    expect(within(completedRow).getByText("completed")).toBeInTheDocument();
  });

  it("shows the empty-state copy when there are no appointments", async () => {
    mockListAppointments.mockResolvedValue([]);

    render(<AppointmentsSection reloadKey={0} />);

    await waitFor(() =>
      expect(
        screen.getByText(
          "No appointments yet. Request a match below to book a visit.",
        ),
      ).toBeInTheDocument(),
    );
  });
});
