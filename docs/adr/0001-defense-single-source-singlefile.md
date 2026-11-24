---
status: accepted
---

# Rebuild defense/ as a single-source Vite + singlefile package

Rebuild `defense/` as a standalone TypeScript + React 18 + Vite + Vitest package (isolated from `web/`) backed by a single typed `deck.ts` source of truth, compiled via `vite-plugin-singlefile` into a self-contained `dist/index.html` plus generated `speech_script.md` and `demo_guide.md`.

## Considered Options

- **Keep hand-edited monolithic `defense/index.html` + separate Markdown files**: Zero build step, but copy changes across slides, speaker console, `speech_script.md`, and `demo_guide.md` drift silently and cannot be unit-tested.
- **Standard multi-file Vite ES module bundle**: Clean modular build, but double-clicking `dist/index.html` over `file://` from a USB stick during an internet-less defense triggers browser CORS errors on `<script type="module">` imports.
- **Standalone TS + Vite + `vite-plugin-singlefile` + doc generator**: Preserves offline `file://` USB portability and identical `https://ppt.acgurl.cn/` hosting while enabling modular components, Vitest testing, and zero-drift doc generation.

## Consequences

- `defense/` remains completely decoupled from `web/` dependencies and build lifecycle.
- Every production build outputs a portable single HTML file (`defense/dist/index.html`) that works over both HTTPS and `file://`, alongside `./assets/` images (`xiaozhi.png`, `airi.png`).
