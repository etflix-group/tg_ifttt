# React Workflow Editor Plan

## Goal

Deliver a browser editor for the canonical workflow JSON used by the Docker API. The primary interaction is a drag-and-drop node canvas; advanced users can switch to YAML/JSON import/export without creating a second workflow format.

## Tasks

- [x] Define Vite/React dependency surface and an API client using bearer auth.
- [x] Build a split-pane editor with node palette, React Flow canvas, inspector, validation/error states, and save/run actions.
- [x] Add canonical JSON import/export and local draft persistence for accidental reload recovery.
- [x] Add accounts/runs navigation surfaces and responsive mobile fallback.
- [x] Verify production build and keep frontend deployable as static assets.

## Design constraints

- Single neutral graphite palette with one desaturated mint accent.
- No secrets in local storage; only an unsaved workflow draft may be cached.
- Node configs remain JSON-compatible and map directly to the backend schema.
- Avoid arbitrary code/expression editors; expose only safe node configuration fields.

