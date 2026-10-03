# Bug record template

Use this for every significant bug ([Part I §17](../platform/DEVELOPMENT_RULES.md#17-bug-policy)).
Put the record in [known issues](KNOWN_ISSUES.md) while it is open; move the
evidence into a [dated record](records/README.md) when it is resolved.
Separate observations from hypotheses: a guess is not a root cause.

```markdown
## <Short description of the observable problem>

- **Problem:** what observable behavior is wrong?
- **Expected behavior:** what should happen?
- **Reproduction:** exact steps, revision, device or test command, how often it fails.
- **Evidence:** logs (`launcher.log`, `launch-gate.log`, journal), daemon state or
  trace, test output, or hardware observation — with paths or excerpts.
- **Root cause:** which invariant or component failed, and the evidence that
  proves it. Until proven, write "Hypothesis:" instead.
- **Fix:** what changed (files, behavior).
- **Regression test:** test name; negative control result (fails without the fix);
  repeat count for timing tests.
- **Hardware validation:** required / performed (device, build) / not performed.
- **Compatibility:** could existing apps, settings or installations be affected?
```

Keep credentials, private messages and personal data out of bug records.
