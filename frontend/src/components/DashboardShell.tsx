/**
 * Minimal layout shell shared by the role dashboards.
 *
 * Renders a header with the role name and a sign-out button, and a content
 * slot. The dashboard tasks (19-21) fill the slot with real views; for now the
 * pages pass a short placeholder.
 */

import type { ReactNode } from "react";
import type { Role } from "../api/types";
import { SignOutButton } from "./SignOutButton";

const ROLE_LABEL: Record<Role, string> = {
  patient: "Patient",
  volunteer: "Volunteer",
  clinician: "Clinician",
};

export function DashboardShell({
  role,
  children,
}: {
  role: Role;
  children?: ReactNode;
}) {
  return (
    <main>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <h1>{ROLE_LABEL[role]} Dashboard</h1>
        <SignOutButton />
      </header>
      <section>{children}</section>
    </main>
  );
}
