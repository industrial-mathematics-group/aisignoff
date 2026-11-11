# Development

```bash
git clone https://github.com/industrial-mathematics-group/aisignoff
cd aisignoff
pip install -e . pytest
pytest
aisignoff lint      # the tool declares its own files, too (see SIGNOFF.toml)
```

With [uv](https://docs.astral.sh/uv/), `uv run pytest` installs the package and pytest (the `dev` dependency group) into `.venv` first.

Contributions follow the [contributing guidelines](https://github.com/industrial-mathematics-group/.github/blob/main/.github/CONTRIBUTING.md) of the Industrial Mathematics Group, including the AI declaration in each pull request. Update `SIGNOFF.toml` in the same pull request when a change alters how a file was created or reviewed.

## Documentation

The documentation is built with [Zensical](https://zensical.org), from the Markdown files in `docs/`. The page order, theme and Markdown extensions are set in `zensical.toml`.

```bash
pip install -r docs/requirements.txt
zensical serve            # preview at http://localhost:8000, reloads on every change
zensical build --strict   # what CI runs: fails on broken links and anchors
```

The *Docs* workflow builds the site on every pull request and publishes it to GitHub Pages on every push to `main`.

## Releasing

1. Bump the version with `uv version --bump patch` (or `minor`, `major`). This updates `pyproject.toml` and `uv.lock`; the package reads its version from there, so there is no other copy.
2. Merge that to `main`.
3. Publish a GitHub release with the tag `vX.Y.Z`, e.g. `gh release create v0.4.3 --generate-notes`.

The *Publish to PyPI* workflow checks that the tag matches the version, runs the tests, builds the package and uploads it through PyPI's trusted publishing. No token is stored in the repository.
