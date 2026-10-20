"use strict";

(async () => {
  const status = document.querySelector("#sign-in-status");
  try {
    if (!window.Clerk || !window.__internal_ClerkUICtor) throw new Error();
    await window.Clerk.load({
      ui: { ClerkUI: window.__internal_ClerkUICtor },
      localization: { signIn: { start: { title: "Sign in to Veriq" } } },
    });
    if (window.Clerk.session) {
      location.replace("/upload/login");
      return;
    }
    window.Clerk.mountSignIn(document.querySelector("#clerk-sign-in"), {
      routing: "hash",
      forceRedirectUrl: location.origin + "/upload/login",
      signUpForceRedirectUrl: location.origin + "/upload/login",
      appearance: {
        variables: { colorPrimary: "#11130f", fontFamily: "Arial, Helvetica, sans-serif", borderRadius: "8px" },
      },
    });
    status.hidden = true;
  } catch {
    status.classList.add("error");
    status.textContent = "The sign-in form could not load. Continue on Clerk’s sign-in page below.";
  }
})();
