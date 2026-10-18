# Veriq privacy policy

Effective: 18 October 2026. Publisher: [Vantalim12](https://github.com/Vantalim12).

Veriq checks exported n8n workflows against reviewed rules without executing the workflows. The hosted service at `https://veriq.sgp.appwrite.run` uses Clerk for sign-in and Appwrite for hosting and private storage. It currently runs as a development pilot.

## Information processed

Veriq processes files you choose to upload: workflow JSON, rules YAML, and SOP PDF or DOCX documents. These may contain business information, document text, workflow parameters, or credentials present in an export. Remove secrets and unnecessary personal information before uploading. Only upload material you are authorized to share.

Veriq validates OAuth access tokens and derives an owner identifier from the issuer and user ID. Private storage records include this identifier, file type, size, expiry, and artifact or audit reference. Browser sign-in uses a secure, HTTP-only cookie. Passwords are handled by Clerk, not by Veriq's upload page.

## Purpose and access

Files are used to parse inputs, check rules, draft unapproved requirements, and produce findings and reports. Veriq tools restrict access to the authenticated owner. The deployed service and its hosting providers process the data needed to operate the service; this is not end-to-end encrypted storage.

When you call Veriq through ChatGPT, tool results are returned to ChatGPT. Results can include source quotations and evidence from your files. OpenAI, Clerk, Appwrite, and GitHub operate under their own applicable privacy policies. The hosted verifier does not call a language model to perform its checks. Optional local model assistance is a separate CLI feature.

## Retention and deletion

Uploaded inputs stop being accessible after 24 hours. You can delete your inputs through the authenticated artifact API. Audit reports stop being accessible after one hour, and each owner retains up to eight reports, subject to global storage limits. Deleting an input does not immediately erase a report already generated from it.

Scheduled cleanup removes expired stored files and releases quota. Physical deletion can lag during outages or cleanup backlogs. Quota rows can retain the pseudonymous owner identifier after files expire. Provider backups and operational logs have their own retention; these application expiry periods do not promise deletion from every provider system. Signing out clears the browser upload cookie but does not delete uploads or end your Clerk or ChatGPT sessions.

## Contact

Use [GitHub Issues](https://github.com/Vantalim12/veriq/issues) for support or to request help deleting account-associated data. Issues are public: do not post tokens, private documents, credentials, or sensitive personal information. Ask for a private contact method before sharing such details. Publisher verification and production deployment are separate from this policy.
