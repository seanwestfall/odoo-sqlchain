# Pilot register and measurement rules

As of 2026-10-20:

| Cohort | Verified users | Evidence |
|---|---:|---|
| Independent business users | 0 | No participating business/cases supplied |
| Founder's business using genuine books | 0 | Not established; do not infer this from the founder developing/testing |
| Founder/developer sample evaluation | 1 | Local demonstration; not a customer/revenue claim |
| Independent developers completing installation | 0 | Automated fresh installation passed on the development host; independent reproduction outstanding |

The founder has reviewed the development UI. This does not establish completion of a real-business workflow. No real invoice, customer attachment or customer identity belongs in this public register.

For each consenting pilot, keep a private case record containing: opaque case ID, organization consent and publication scope, participant role, whether it is the founder's own business, exact business task, expected human choice, evidence/version references, policy outcome, amount/network units, review actions, outcome and participant signoff. An agent recommendation is not a human signoff. Export only aggregates or explicitly approved redacted cases. Use testnet settlement; test tokens are never revenue.

Record queue-to-first-claim delay, pending queue age, uncertain attempt count, company-level reservations grouped by network/interface, dispatch-to-observation lag, failed/pending resource deliveries and delivered resources using `scripts/metrics.py`. Missing timing samples are null, not zero. Averages alone do not establish an SLA.

Three measures require explicit operator evidence because the current SQL history does not automatically capture all of them: duplicate suppression, human intervention, and useful work completed. Record a unique opaque evidence ID using `scripts/events.py`; repeating it does not increment the count. `useful_work_completed` means the participant confirmed their chosen task was completed, not that a receipt arrived. Select the matching dataset and database when exporting. These are operator-attested counters, not tamper-proof automatic telemetry. Until an event ledger is supplied, these metrics are null. Keep the ledger private and back it up.

Example for a genuine pilot (only after the action actually occurs):

```sh
python milestone7/scripts/events.py --ledger .local/pilot/events.sqlite --event-id CASE_ID-human-review-1 --dataset testnet-pilot --database chainsql_release --kind human_intervention
python milestone7/scripts/metrics.py --dataset testnet-pilot --event-ledger .local/pilot/events.sqlite --output .local/pilot/metrics.json
```

Before a release claim: a second developer installs from the package on a clean supported host; a consenting real user completes a documented task; an operator demonstrates paused restore/reconciliation with the pilot's actual journals; and a reviewer follows the walkthrough without founder narration. Record failures as well as successful cases. Ongoing observation is not scheduled or claimed by these scripts.
