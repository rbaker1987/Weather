# Pull Request Checklist

## PR Checklist

Core validation before requesting review:

- [ ] Ran app locally: `python manage.py runserver` (no startup errors)
- [ ] Browser console clean (no uncaught errors; benign 404s reviewed)
- [ ] Python lint: `ruff check .` passes
- [ ] Python format applied: `ruff format .` (no pending diffs)
- [ ] JS lint: `npm run lint:js` passes
- [ ] JS format: `npm run format` (no pending diffs)
- [ ] Tests: `pytest` all pass
- [ ] Migrations: created & applied (`python manage.py makemigrations` if needed, then `python manage.py migrate`)
- [ ] Documentation updated (README / relevant docstrings) if feature or behavior changed
- [ ] No secrets / credentials added
- [ ] Reviewed diff for accidental large deletions / noise
- [ ] Forecast/UI components render new data (if UI-related change)

Optional considerations (tick if applicable):

- [ ] Added / updated management command
- [ ] Added new environment variable (documented in README Configuration)
- [ ] Backward compatibility confirmed (no breaking API/schema changes)
