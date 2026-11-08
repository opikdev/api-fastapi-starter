# 006. Keep a fixed import package name

- **Status**: accepted
- **Context**: `pik new` renames a project by replacing text in files, and can't rename folders. A package named after the project would keep the starter's name in every generated project.
- **Decision**: Name the import package `app` in every project, as many FastAPI projects do, and rename only the distribution, the command, and the service name.
- **Consequences**:
  - A generated project runs with no folder renames.
  - The package isn't meant for PyPI, where `app` would clash. Publish the generated client instead, if you need a package.
  - To rename it, move `src/app`, and update `module-name` in `pyproject.toml`, the imports, and `alembic.ini`.
