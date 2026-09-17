## What does this change?

<!-- A short description of the change and why it is needed. -->

## Type of change

- [ ] Bug fix
- [ ] New entity or feature
- [ ] Update to the bundled OpenAPI spec
- [ ] Documentation
- [ ] CI / tooling

## Checklist

- [ ] `python -m pytest` passes
- [ ] `pre-commit run --all-files` passes
- [ ] New or changed entities have translations in `translations/en.json`
- [ ] If `resources/openapi.json` changed, `scripts/generate_enums.py` and
      `scripts/generate_translations.py` were re-run and the result committed
- [ ] No credentials, VINs, GPS coordinates or other personal data appear in
      the diff, in test fixtures, or in log output

## API impact

<!-- Does this change how many requests a poll costs? The Data Portal allows
     around 10,000 requests per day. Note any change to the request budget. -->

## Testing

<!-- How was this verified? Mention the Home Assistant version if relevant. -->
