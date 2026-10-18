"use strict";

const login = document.querySelector("#login");
const logout = document.querySelector("#logout");
const accountStatus = document.querySelector("#account-status");
const pageError = document.querySelector("#page-error");
const forms = [...document.querySelectorAll(".file-card")];
let signedIn = false;
let uploadCount = 0;

function showError(message) {
  pageError.textContent = message;
  pageError.hidden = !message;
}

function setSignedIn(value) {
  signedIn = value;
  login.hidden = value;
  logout.hidden = !value;
  for (const form of forms) form.querySelector("fieldset").disabled = !value;
}

async function checkSession() {
  try {
    const response = await fetch("/upload/session", { cache: "no-store" });
    if (!response.ok) throw new Error();
    const session = await response.json();
    setSignedIn(session.signed_in);
    if (!session.configured) {
      login.hidden = true;
      accountStatus.textContent = "Browser login is not configured yet. Contact the Veriq administrator.";
    } else if (signedIn) {
      accountStatus.textContent = "Signed in for uploads. Sessions last up to one hour. Use this same Clerk account in ChatGPT.";
    } else {
      accountStatus.textContent = "Sign in with the same Clerk account you connected to Veriq in ChatGPT.";
    }
  } catch {
    setSignedIn(false);
    login.hidden = true;
    accountStatus.textContent = "Could not check your session. Reload the page to try again.";
  }
}

function addArtifact(file, result) {
  const item = document.createElement("li");
  item.className = "artifact";
  const details = document.createElement("div");
  details.className = "artifact-details";
  const name = document.createElement("strong");
  name.textContent = file.name;
  const id = document.createElement("code");
  id.textContent = result.artifact_id;
  const expiry = document.createElement("small");
  expiry.textContent = `${result.kind.toUpperCase()} · Expires ${new Date(result.expires_at * 1000).toLocaleString()}`;
  details.append(name, id, expiry);
  const copy = document.createElement("button");
  copy.className = "button secondary";
  copy.type = "button";
  copy.textContent = "Copy ID";
  copy.setAttribute("aria-label", `Copy artifact ID for ${file.name}`);
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(result.artifact_id);
      copy.textContent = "Copied";
    } catch {
      copy.textContent = "Select the ID to copy";
    }
  });
  item.append(details, copy);
  document.querySelector("#artifact-list").prepend(item);
  document.querySelector("#empty-results").hidden = true;
  uploadCount += 1;
  document.querySelector("#result-count").textContent = `${uploadCount} file${uploadCount === 1 ? "" : "s"} uploaded`;
}

for (const form of forms) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!signedIn || !form.reportValidity()) return;
    const input = form.querySelector("input[type=file]");
    const file = input.files[0];
    const status = form.querySelector(".form-status");
    const button = form.querySelector("button");
    const type = form.dataset.type;
    const extension = file.name.split(".").pop().toLowerCase();
    const extensions = { workflow: ["json"], sop: ["pdf", "docx"], policy: ["yaml", "yml"] };
    const limit = (type === "sop" ? 10 : 2) * 1024 * 1024;
    status.classList.remove("error");
    if (!extensions[type].includes(extension) || file.size === 0 || file.size > limit) {
      status.textContent = "Choose a nonempty file with the listed format and size limit.";
      status.classList.add("error");
      return;
    }
    button.disabled = true;
    input.disabled = true;
    form.setAttribute("aria-busy", "true");
    status.textContent = "Uploading and validating…";
    try {
      const kind = type === "sop" ? extension : type;
      const response = await fetch(`/upload/artifacts/${kind}`, {
        method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file,
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          setSignedIn(false);
          accountStatus.textContent = "Your upload session ended. Sign in again to continue.";
        }
        throw new Error(result.error || "Upload failed. Check the file and try again.");
      }
      addArtifact(file, result);
      form.reset();
      status.textContent = "Uploaded. Your artifact ID is below.";
      if (result.compatibility?.node_issues?.length) {
        status.textContent += ` ${result.compatibility.node_issues.length} node(s) are outside the supported model. Ask Veriq to inspect the workflow before auditing.`;
      }
    } catch (error) {
      status.classList.add("error");
      status.textContent = error instanceof TypeError || error instanceof SyntaxError
        ? "The upload result could not be confirmed. The file may have been saved; retrying creates another artifact."
        : error.message;
    } finally {
      button.disabled = false;
      input.disabled = false;
      form.removeAttribute("aria-busy");
    }
  });
}

logout.addEventListener("click", async () => {
  logout.disabled = true;
  try {
    const response = await fetch("/upload/logout", { method: "POST" });
    if (!response.ok) throw new Error();
    setSignedIn(false);
    for (const form of forms) form.reset();
    document.querySelector("#artifact-list").replaceChildren();
    document.querySelector("#empty-results").hidden = false;
    uploadCount = 0;
    document.querySelector("#result-count").textContent = "No files uploaded yet";
    accountStatus.textContent = "Signed out of uploads. Your files will expire automatically.";
  } catch {
    showError("Could not sign out. Try again.");
  } finally {
    logout.disabled = false;
  }
});

if (new URLSearchParams(location.search).get("login") === "failed") {
  showError("Sign-in did not complete. Try again. If it keeps failing, contact the Veriq administrator.");
}
history.replaceState(null, "", "/upload");
checkSession();
