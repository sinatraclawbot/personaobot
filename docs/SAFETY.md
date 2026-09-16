# Safety, privacy and operator controls

The permitted service is lawful, consensual, non-sexual social companionship between adults. No sexual-service facilitation, sexual-service pricing, sourcing people, trafficking, exploitation, coercion, minors or illegal activity is supported. The application cannot override local law, verify a person's identity automatically, or guarantee that a probabilistic classifier understands every language, euphemism or adversarial input.

## Enforcement

- Profiles start disabled and in approval mode. An operator must review the profile's lawful adult scope and configure boundaries before enabling replies.
- Routine replies do not require manual adulthood/consent checkboxes. This does not establish adulthood or consent: explicit minor-related or coercive requests remain blocked, opt-outs stop replies, and actual uncertainty is held by semantic safety checks.
- The AI policy overrides all profile customizations, memories and client text. Those are explicitly untrusted data. No external retrieval or tools are exposed to the model.
- Deterministic text gates flag obvious high-risk input even while automation is paused. Exact opt-out phrases revoke consent. Semantic policy review handles broader and multilingual intent. Prompt injection cannot access other profiles because their data is not in the model request.
- OpenAI moderation runs on input and output. Structured semantic decisions cover service-specific risks not necessarily flagged by general moderation, including sexual-service solicitation, consent uncertainty and booking commitments.
- Every outgoing candidate, including approved or manual text, is independently rechecked before send. Provider failure, malformed/refused/incomplete outputs and uncertain safety decisions stop delivery.
- Unsupported media is escalated without downloading, forwarding, analyzing or echoing it. AI disclosures are instructed in the non-overridable policy; operators must preserve this disclosure in manual replies.
- Blocked conversations cannot be resumed in the dashboard. Escalated/paused ones require an operator review note before resume. Owner replies in Telegram pause automation automatically.
- Automated bookings, overnight/private meetings, payments, financial commitments and collection of addresses/identity documents are outside the implemented product. A human handles any lawful next step outside the automated reply engine.

This MVP blocks rather than sending an automatic refusal into a high-risk conversation. Operators see the state and reason in the inbox. Escalation notifications are dashboard-based; external email/SMS/push alerts are not implemented.

## Privacy

Each AI request contains only one profile's configuration and one client's conversation/notes. `store=false` prevents Responses API application-state storage; it does not automatically eliminate provider abuse-monitoring logs. Review the AI provider's data controls and required notices before using real client content.

Content is stored in the database, not application logs. Encrypt database volumes and backups, use TLS connections in production and restrict DB access. The MVP does not implement application-level field encryption. Telegram remains a separate copy of the conversation; erasing this application's data does not delete Telegram or provider records.

Hourly maintenance clears conversations inactive for `RETENTION_DAYS` (default 30), message text, drafts and memory; it pauses erased conversations and clears verification. Raw inbox payloads are cleared after successful processing and aged out during maintenance. Minimal IDs/tombstones remain to prevent reprocessing and resurrection. Audit records retain no message content and expire after one year. Configure shorter retention if needed; backups have their own rotation and deletion process.

## Launch evaluation

Keep approval mode until a human-reviewed evaluation has passed in every enabled language. Include benign public social meetings, ambiguous euphemisms, explicit solicitation, age uncertainty, underage statements, coercion, trafficking, prompt injection, requests for secrets/other profiles, opt-outs, private/overnight meetings and requests for a human. Evaluate complete multi-turn conversations, not just keywords.

The automated tests validate control flow with deterministic provider responses and local rules. They are not evidence of measured real-model classification accuracy. `safety-cases.jsonl` provides a starting corpus; expand it with native-speaker reviewers. Stop automatic mode if a prohibited request is classified as allowed. Rate-limit provider use, monitor false positives and reassess after model changes.

Official AI references:

- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Moderation](https://developers.openai.com/api/docs/guides/moderation)
