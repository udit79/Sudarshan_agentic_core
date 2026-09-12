/* Google OAuth entry point for the public landing shell. */
document.addEventListener("DOMContentLoaded", async () => {
  const googleButton = document.getElementById("googleLoginBtn");
  const authStatus = document.getElementById("authStatus");
  const harnessUrl = window.SUDARSHAN_HARNESS_URL || "http://localhost:3080/";

  const setStatus = (message, isError = false) => {
    if (!authStatus) return;
    authStatus.textContent = message;
    authStatus.classList.toggle("error", isError);
  };

  try {
    await window.SudarshanAPI.getCurrentUser();
    window.location.replace(harnessUrl);
    return;
  } catch (error) {
    if (error.status && error.status !== 401) setStatus(error.message, true);
  }

  googleButton?.addEventListener("click", () => {
    googleButton.disabled = true;
    setStatus("Redirecting to Google securely...");
    window.SudarshanAPI.googleLogin();
  });
});
