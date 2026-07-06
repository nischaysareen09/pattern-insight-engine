# Decision Note

The most important decision: keep the rule-based layer and the LLM layer
strictly separated, with the LLM only ever receiving pre-computed statistics
(streaks, trends, time-of-day shifts, anomaly flags) rather than raw events.

The trade-off is real. Letting the LLM see raw events directly would
probably produce richer, more varied insights - it could notice patterns my
fixed set of rules doesn't compute (co-occurrence between activity types,
narrative context from metadata, subtler phrasing of what changed). Instead,
every insight is bottlenecked by what `patterns.py` explicitly calculates.

I chose the separation anyway because it makes the "genuinely useful"
requirement verifiable rather than trusted. Every number in a generated
insight traces back to a pure function over stored data, testable in
isolation, with no chance of the model inventing a streak or trend that
didn't happen. Given a 24-hour window and no way to systematically evaluate
LLM output quality, I valued correctness and auditability over creative
range. The explicit cost is a ceiling on insight variety - the system can
only ever be as interesting as the statistics I thought to compute.
