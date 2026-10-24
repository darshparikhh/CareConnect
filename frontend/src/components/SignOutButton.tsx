/**
 * Sign-out control. Clears the session and returns the user to sign-in.
 * Shared by all three dashboard placeholders.
 */

import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function SignOutButton() {
  const { signOut } = useAuth();
  const navigate = useNavigate();

  const handleClick = () => {
    signOut();
    navigate("/sign-in", { replace: true });
  };

  return (
    <button type="button" onClick={handleClick}>
      Sign out
    </button>
  );
}
