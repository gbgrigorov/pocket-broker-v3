# Data and privacy boundaries

Phase 1 adds geographic metadata and public filters. It adds no buyer accounts,
favorites, telemetry, contact collection or agency access. Existing Django admin
and session/CSRF protections remain. Restored validation databases and DB dumps
contain the original application's data; keep them private and outside served
media directories. Never commit credentials, dumps or raw source evidence.

Future phases must preserve these distinctions:

- VIEW: an intentionally recorded property visit; minimize retained identifiers.
- FAVORITE: a save, visible to agencies only as aggregate property interest.
- LEAD: a user's explicit, consented request to contact a named agency.
- MATCH: deterministic match against a city-scoped saved search.
- REFERRAL: the stable attribution of a lead to its selected agency.

A heart click is never permission to disclose name, email or phone. Contact
forms must name recipients, collect consent, and create only those AgencyLead
recipients the user selected. Partner API authorization must use the logged-in
user's active AgencyMembership, never a trusted request-supplied agency ID.
Partners do not receive Django staff/admin access. Enforce these rules with
cross-agency permission and consent tests before those features launch.
