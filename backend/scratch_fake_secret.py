# Deliberately fake secret, committed on purpose to prove gitleaks / CI
# catches it — phase1.txt Step 12 PROVE IT. Never merged; this branch is
# deleted immediately after the CI run confirms the failure.
#
# NOTE: an earlier version of this file used the literal AWS documentation
# example key (AKIAIOSFODNN7EXAMPLE) — gitleaks' default ruleset
# deliberately allowlists that exact string (and a few other well-known
# copy-pasted tutorial examples) to cut false positives, so it correctly
# did NOT flag it. That's gitleaks working as designed, not a CI bug —
# switched to a random-looking token instead, which isn't on any
# allowlist.
GITHUB_TOKEN = "ghp_7KzR3mQpN9vXeT2sYbL8wF4dC6hJ1aG5nZ0u"
