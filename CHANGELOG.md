# Unreleased
Fields the PVS does not report are now `None` instead of `0`/`0.0` (and
`ct_scale_factor` instead of `1.0`). Model annotations are `Optional`
accordingly; callers that relied on zero should default it themselves.

# v0.1.3
Prepared for PyPi publishing

# v0.1

Initial public revision