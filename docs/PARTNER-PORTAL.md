# Partner portal — contract for future phases

Not implemented in Phase 1. Use the existing Vue application and Django session
authentication under `/partner` and `/api/partner/` when phases 6–8 begin.

AgencyMembership links Django users to one Agency with an active flag and
owner/manager/agent/viewer role. Every partner query is membership-scoped on the
server. Dashboard totals, inventory, crawler health, interest and leads must not
expose another agency's private data. An ordinary buyer cannot access these APIs.

Property interest is aggregated across offers in the same city-scoped property
group. Label it as market interest, not buyers choosing that specific agency.
Favorites reveal no buyer identities. Agency-directed leads are separate counts
and contain contact details only after explicit consent for that agency.

The lead inbox will use LeadRequest plus AgencyLead, a stable referral code,
viewed/responded timestamps and logged status changes. Portal delivery is primary;
email notifications and digests are optional later. No notification is sent for
each favorite, and no agency is contacted during Phase 1.
