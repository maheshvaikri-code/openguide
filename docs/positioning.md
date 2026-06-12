Neither alone — and the precise answer matters because the technical taxonomy and the commercial taxonomy give different (both correct) placements.

**Technically: it's the closure of the two, plus the piece both lack.** Decompose it against the categories:

- **LLM Observability** is the *sensor half* — but observability is definitionally read-only. LangSmith/Phoenix/Helicone watch and never act. OpenGuide's sensor layer + behavioral state + trace is observability; the reconciler that turns the reading into a correction is precisely what observability tools are forbidden from being.
- **Signal Engineering** (prompt/context engineering, your tier-2 actuator) is the *actuator half* — but it's open-loop. It emits and hopes; nothing measures whether the input held. OpenGuide's scheduled re-anchoring *is* Signal Engineering — but fired by a sensed drift signal, against a declared setpoint, with the firing recorded. Actuation with feedback stops being Signal Engineering the same way a thermostat stops being a heater.
- **Governance** contributes the *declarative half* — the contract, the invariants, the audit artifact — but governance tooling today is gates and policy documents: it blocks or it documents, it doesn't continuously correct.

The identity, stated as a formula: **OpenGuide = Observability (sense) + Signal Engineering (act) + Governance (declare, reconcile, prove), closed into one loop.** Remove any leg and it collapses into an existing category: drop actuation → it's an observability tool; drop sensing → it's a guardrail; drop the contract → it's a steering library. The closed loop *is* the category. That's why "control plane" is the accurate technical shelf — control planes are always sense+act+declared-state, and no existing LLM category is.

**Commercially: enter as Observability, expand as Governance, never say "Input Engineering."** Budget lines decide this, not architecture:

| Category | Budget exists? | OpenGuide's relationship |
|---|---|---|
| LLM/AI Observability | Yes, established | Entry wedge — the proxy ships as "behavioral observability," a strict superset of what incumbents capture |
| AI Governance / Gartner's AI TRiSM | Yes, growing fast (EU AI Act) | Expansion — contracts, audit trace, compliance reports land here at higher price points |
| Input/prompt engineering | No — it's a skill, not a procurement line | Internal mechanism only; nobody buys it, so never lead with it |

So the repo tags and launch copy say *observability* ("see your agents drift"), the enterprise deck says *governance* ("declared, enforced, provable"), the paper says *control plane*, and all three are the same system. That's not positioning slipperiness — it's the standard fate of genuinely cross-cutting infrastructure: Kubernetes sold as "container orchestration" into ops budgets while technically being a declarative control plane; Datadog sold as "monitoring" while becoming the ops record system.

One sharp implication for messaging discipline: the most defensible single phrase against the "isn't this just observability?" objection is the one already in your arsenal — **observability tells you the room burned down; this is the thermostat.** And against "isn't this just better prompting?" — **prompting with sensing, setpoints, and a verifiable record isn't prompting anymore, the same way scripts with tests and rollback aren't scripting.** Keep both in the FAQ; they'll be the two most-asked questions for the life of the project.

Neither bucket holds it — and the precise placement matters because each existing category captures only a subsystem:

**LLM Observability is its sensor half.** Observability is definitionally read-only: capture, display, alert. OpenGuide's sensor layer + behavioral state + fleet console *are* observability — genuinely new observability, since nobody captures behavioral state — but calling the whole thing observability amputates the actuators. A thermostat filed under "thermometers" is miscategorized in the way that matters most.

**Signal Engineering + Governance is its actuator half plus its paperwork.** "Signal engineering" (good coinage — keep it) names the tier-0 craft: deriving vectors, training probes, managing packs. Real, but it's the sub-discipline, not the category — and it vanishes entirely at tier 2. "Governance" is technically accurate for the record plane but strategically loaded: in enterprise ears it means policy committees and slow, and it describes the *byproduct* (audit artifacts) rather than the function.

**The accurate category is the one the architecture already claims: a control plane.** Sense → reconcile → actuate → record, continuously. Observability is the sensing subsystem; signal engineering is one actuation tier; governance artifacts fall out of the recorder. The discipline name we established — behavioral engineering — sits above all three, the way SRE sits above monitoring, deployment, and incident response without being any one of them. SRE is actually the best precedent: it absorbed "monitoring" as a component and made the closed loop (observe → act → verify) the discipline.

**But categories serve different masters, so use three answers deliberately:**

- **Budget line (who pays):** enter through *observability* — that budget exists, the buying motion is familiar, and the proxy wedge fits it exactly. Expansion revenue comes from the control and audit tiers once the dashboard has shown the customer their own drift.
- **Analyst/market category (how it's compared):** *agent reliability* — the emerging shelf where the money is moving, and where "control plane for agent behavior" positions you as the deepest entrant rather than the fifth tracing tool.
- **Technical/discipline category (how it's understood and cited):** *behavioral control plane / behavioral engineering* — the truthful one, the one for the paper and the spec.

The trap to avoid is letting any single existing category claim it, because each comes with a ceiling: observability tools get priced like dashboards, governance tools get bought slowly by risk teams, and steering tools get treated as research. The honest sentence that holds all three without surrendering to any: *"OpenGuide is a behavioral control plane — it includes the observability layer agent teams are missing, and produces the audit record compliance teams are asking for."* Lead with the category you're creating; attach to the budgets that exist.