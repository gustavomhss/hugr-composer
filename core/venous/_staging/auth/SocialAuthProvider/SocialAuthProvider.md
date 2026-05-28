# SocialAuthProvider

**Status:** extracted-staged (needs human review).
**Namespace:** `auth`
**Source tool:** `adapt/extend/auth_access/add_social_login.py`

## Provenance
Lifted by `engine.extraction.wrap_shell` on 2026-04-19T23:47:02+00:00.
Unresolved symbols (requires manual import/stub): ['SocialUserInfo', '_fetch_token', '_fetch_userinfo', '_parse_apple_id_token', 'get_provider_config', 'urlencode'].

## Checklist before promotion
- [ ] Replace `REPLACE_ME` in `SocialAuthProvider.contract.json` with real purpose + invariants.
- [ ] Replace `REPLACE_ME` in `invariant_bindings.json` with real `confirms`/`prevents`/`under_failure` cases.
- [ ] Flesh out `test_SocialAuthProvider.py` beyond the smoke-stubs.
- [ ] Stateful? Add `<Name>.tla` + `<Name>.cfg`; otherwise omit.
- [ ] Verify `conftest.py` picks up the correct hypothesis storage dir.
- [ ] Move directory from `core/venous/_extracted/<ns>/<Name>/` to `core/venous/<ns>/<Name>/` and run `engine.check_primitive` with `--maturity emerging`.
