# DGX Spark vLLM Runtime Dashboard Plan

## Goal

Build a polished local web dashboard for managing and presenting the vLLM recipe runtimes on the DGX Spark.

The dashboard should help a non-specialist manager quickly see:

- Which model recipes are available.
- Which recipes are running now.
- How much GPU and system memory they use.
- Which API ports and endpoints are active.
- Which capabilities are ready to demo.
- How to start a recipe safely from the browser.

The experience should feel like an executive AI operations console, not a terminal wrapper. It should still be technically accurate and safe.

## Project Location

Create the dashboard inside the existing project:

```text
~/Documents/spark-vllm-docker/dashboard/
```

The dashboard must use the existing launcher:

```bash
./run-recipe.sh translategemma-4b-it --solo --port 8001
```

Do not rewrite the recipe runner. The dashboard should wrap it through a small backend API.

## Product Principles

- Keep the first screen useful. Do not make a marketing landing page.
- Make it look modern, dark, calm, and high quality.
- Avoid a raw "developer tool" look.
- Use clear B2-level English.
- Prefer short labels and clear action names.
- Use the same names for links, page headers, browser titles, and breadcrumbs.
- Every page reached through a link must have a matching page header.
- If product pages are added, each product page must describe exactly one product or runtime.
- Keep operational details available, but place advanced details behind disclosure controls.
- Make the dashboard suitable for live demos and internal management reviews.

## Recommended Stack

Use native browser and platform features as much as possible.

Preferred frontend:

- HTML5
- CSS3
- Native JavaScript only where needed
- Web Components only if they reduce repeated code
- No heavy frontend framework unless the project clearly needs it later

Preferred backend:

- Python FastAPI, or Flask if a smaller dependency footprint is preferred
- PyYAML for reading recipe files
- Standard library subprocess APIs for controlled commands
- Server-sent events or simple polling for live updates

Preferred runtime:

- Local web server on the DGX Spark
- Network access limited to trusted local network users
- Optional login token or simple password for manager-facing use

## Main User Roles

### Manager

Needs a clean overview of what is running, what is ready, and what the system can demonstrate.

### Operator

Needs to start, stop, inspect, and troubleshoot recipe runtimes without typing commands.

### Developer

Needs accurate command previews, logs, dry runs, and safe access to advanced flags.

## Information Architecture

Use consistent page names everywhere.

### Pages

- Overview
- Recipes
- Runtime
- Launch
- Logs
- Settings

### Naming Rule

If a navigation link says `Recipes`, the page heading must also say `Recipes`.

If a link says `Runtime`, the page heading must also say `Runtime`.

Do not use near-synonyms such as `Models`, `Recipe Library`, and `Available Recipes` for the same destination. Pick one name and use it everywhere.

## Semantic Layout

Use semantic HTML5 structure.

Each page should follow this shape:

```html
<body>
  <header>
    <nav aria-label="Main navigation"></nav>
  </header>
  <main>
    <section aria-labelledby="page-title"></section>
  </main>
  <aside aria-label="Runtime summary"></aside>
  <footer></footer>
</body>
```

Use:

- `main` for primary page content.
- `section` for major content groups.
- `article` for one recipe card or one runtime card.
- `aside` for supporting status, filters, tips, or summaries.
- `nav` for navigation only.
- `dialog` for launch confirmation and destructive actions.
- Native `button`, `input`, `select`, `textarea`, `details`, `summary`, `meter`, and `progress` elements where they fit.

Do not build clickable `div` elements.

## Core Screens

### Overview

Purpose: show the current operational state at a glance.

Content:

- Page header: `Overview`
- Running runtimes count.
- Available recipes count.
- GPU memory usage.
- System memory usage.
- Active ports.
- Healthy endpoints.
- Recent launch events.
- Demo-ready capabilities.

Visual style:

- Dark background.
- Clear status colors.
- Large readable values.
- Executive-friendly language.

Example labels:

- `Running`
- `Starting`
- `Ready`
- `Stopped`
- `Needs Attention`

### Recipes

Purpose: browse available recipe files from `recipes/*.yaml`.

Content:

- Page header: `Recipes`
- Recipe name.
- Description.
- Model ID.
- Container image.
- Solo or cluster support.
- Default port.
- Default GPU memory target.
- Max model length.
- Mods used.
- Launch action.

Filters:

- `All`
- `Solo`
- `Cluster`
- `Running`
- `Ready to Launch`

Each recipe card should use one consistent name. Prefer the recipe `name` field from YAML. If a shorter display name is needed, define it in one place and reuse it everywhere.

### Launch

Purpose: start a selected recipe with safe settings.

Content:

- Page header: `Launch`
- Selected recipe summary.
- Mode selector: `Solo` or `Cluster`.
- Port input.
- Host input.
- GPU memory utilization slider.
- Max model length input.
- Tensor parallel input when relevant.
- Setup toggle.
- Dry run toggle.
- Advanced settings in a `details` element.
- Generated command preview.
- Launch button.

The main launch action should construct an argument list. It must not execute raw shell text from the browser.

Example safe backend command:

```python
[
    "./run-recipe.sh",
    "translategemma-4b-it",
    "--solo",
    "--port",
    "8001",
]
```

### Runtime

Purpose: inspect and manage one running runtime.

Content:

- Page header: `Runtime`
- Runtime name.
- Recipe name.
- Status.
- Uptime.
- Port.
- API base URL.
- GPU memory.
- CPU memory.
- Container name.
- Last health check.
- Start, stop, restart actions.
- Link to logs.

If there are many runtimes later, use a list page named `Runtimes` and a detail page named `Runtime`. Keep this distinction consistent.

### Logs

Purpose: show clean and raw runtime logs.

Content:

- Page header: `Logs`
- Runtime selector.
- Clean event list.
- Raw log view in a scrollable region.
- Copy logs button.
- Refresh button.

Accessibility:

- Do not auto-scroll if the user has scrolled up.
- Announce new critical events through an ARIA live region.
- Avoid motion-heavy log effects.

### Settings

Purpose: configure dashboard-level behavior.

Content:

- Page header: `Settings`
- Project path.
- Recipe path.
- Default port range.
- Refresh interval.
- Demo mode toggle.
- Authentication token status.
- Health check timeout.

## Backend API Plan

### `GET /api/recipes`

Reads recipe YAML files from:

```text
~/Documents/spark-vllm-docker/recipes/
```

Returns:

- Recipe slug.
- Recipe name.
- Description.
- Model ID.
- Container.
- Defaults.
- Mods.
- Environment variables.
- Solo-only or cluster-only flags.

### `GET /api/runtimes`

Returns the detected current runtimes.

Detection sources:

- Docker containers.
- vLLM-related processes.
- Known dashboard launch registry.
- Active ports.
- vLLM health endpoint when available.

### `POST /api/runtimes`

Starts a recipe.

Input:

- Recipe slug.
- Mode.
- Port.
- Host.
- Safe supported overrides.
- Setup or dry-run mode.

Rules:

- Validate recipe slug against known recipes.
- Validate all flags against an allowlist.
- Validate port range.
- Reject arbitrary command strings.
- Store launch metadata.
- Return launch ID and status.

### `POST /api/runtimes/{id}/stop`

Stops a runtime.

Rules:

- Stop only a runtime that the dashboard can identify.
- Prefer container labels or known container names.
- Ask for confirmation in the UI.

### `GET /api/gpu`

Reads GPU status.

Suggested source:

```bash
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw --format=csv,noheader,nounits
```

### `GET /api/system`

Reads host memory, disk, and uptime.

Use native Linux sources such as:

- `/proc/meminfo`
- `/proc/uptime`
- `df`

### `GET /api/logs/{id}`

Returns recent logs for one runtime.

Support:

- Last N lines.
- Polling.
- Optional server-sent events later.

## Runtime Tracking

Use a dashboard launch registry file:

```text
dashboard/state/runtimes.json
```

Each record should include:

- Runtime ID.
- Recipe slug.
- Recipe name.
- Command arguments.
- Port.
- Mode.
- Start time.
- Container name if known.
- Process ID if known.
- Last known status.

If possible, add stable container names through the existing `--name` flag.

Example:

```bash
./run-recipe.sh translategemma-4b-it --solo --port 8001 --name vllm-translategemma-4b-it-8001
```

## Visual Design Direction

Style:

- Dark mode first.
- CGI-inspired depth and lighting.
- Professional, not flashy.
- Calm dashboard layout.
- Strong contrast.
- No low-contrast text.
- No decorative clutter.

Suggested palette:

- Background: near black.
- Surface: dark neutral.
- Text: white and cool gray.
- Primary accent: cyan.
- Success: green.
- Warning: amber.
- Error: red.

Avoid a one-color theme. Use status colors with meaning.

Layout:

- Clear grid.
- Stable card sizes.
- No layout shift on refresh.
- Responsive from laptop to large demo display.
- Mobile support required, but desktop is the main target.

Typography:

- Use system fonts.
- Do not scale text with viewport width.
- Keep letter spacing normal.
- Use readable line lengths.

## Accessibility Requirements

Target: WCAG 2.2 AA.

Minimum requirements:

- All text must meet AA contrast.
- Interactive controls must be keyboard accessible.
- Focus states must be visible.
- Page must work at 200% zoom.
- Page must work with reduced motion enabled.
- No information may rely on color alone.
- Forms must have real labels.
- Buttons must have clear accessible names.
- Icons need labels or `aria-hidden="true"` when decorative.
- Status updates need polite ARIA live regions.
- Destructive actions need confirmation.
- Tables need captions or clear labels.
- Cards must have semantic headings.
- Use skip links.
- Use landmarks correctly.

Testing:

- Keyboard-only navigation.
- Screen reader smoke test.
- Browser zoom at 200%.
- High contrast mode where available.
- Lighthouse accessibility score should be green.

## Security Requirements

Target: Mozilla Observatory A+.

Use secure defaults even on a local dashboard.

HTTP headers:

- `Content-Security-Policy`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy`
- `Cross-Origin-Opener-Policy`
- `Cross-Origin-Resource-Policy`
- `Cross-Origin-Embedder-Policy` if compatible
- `Strict-Transport-Security` when served over HTTPS

Content Security Policy:

- No inline scripts.
- No inline event handlers.
- No remote third-party scripts.
- Restrict images, styles, fonts, and connections.
- Prefer local assets only.

Authentication:

- Require a local token or password before launch and stop actions.
- Do not expose launch controls publicly.
- Protect state-changing endpoints against cross-site requests.

Command safety:

- Use subprocess argument arrays.
- Never pass browser input into a shell string.
- Allow only known flags.
- Validate recipe names against discovered files.
- Validate numeric ranges.
- Log every launch and stop action.

Secrets:

- Do not show full environment secrets in the UI.
- Mask tokens.
- Do not write secrets to frontend files.

## Performance Requirements

Target: Google Lighthouse all green.

Categories:

- Performance: green.
- Accessibility: green.
- Best Practices: green.
- SEO: green where relevant.
- PWA: green.

Performance rules:

- Use minimal JavaScript.
- Use no heavy UI framework unless later justified.
- Use local CSS.
- Avoid large background images.
- Avoid blocking scripts.
- Use `defer` for scripts.
- Keep initial payload small.
- Poll at reasonable intervals.
- Cache static assets.
- Avoid layout shift.

## Progressive Web App Requirements

The dashboard must be installable as a PWA.

Add:

- `manifest.webmanifest`
- Service worker
- App icon set
- Offline fallback page
- Cache for static shell assets
- Theme color
- Display mode: `standalone`

PWA behavior:

- The app should open to `Overview`.
- If offline, show cached shell and a clear status message.
- Runtime controls should be disabled while backend connection is unavailable.
- Do not pretend stale runtime data is live.

## Coding Best Practices

### General

- Keep changes small and focused.
- Prefer existing project patterns.
- Use clear names.
- Avoid clever code.
- Avoid global state unless it is intentional and documented.
- Keep modules small.
- Separate reading state from changing state.
- Treat frontend and backend validation as separate layers.
- Use structured data instead of parsing display text.
- Prefer standard library features when they are enough.

### Python

- Use type hints for API models and core functions.
- Use `pathlib.Path` for paths.
- Use `subprocess.Popen` or `subprocess.run` with argument lists.
- Do not use `shell=True`.
- Handle timeouts.
- Return clear errors.
- Log important actions.
- Keep filesystem paths configurable but safe.
- Normalize and validate paths before use.

### JavaScript

- Use modules.
- Keep DOM selection local and explicit.
- Do not create HTML from untrusted strings.
- Use `textContent` for user-visible dynamic text.
- Use `fetch` wrappers for consistent error handling.
- Use event delegation only where it stays clear.
- Keep state shape simple and documented.

### CSS

- Use CSS custom properties for tokens.
- Use semantic class names.
- Keep component styles grouped.
- Respect `prefers-reduced-motion`.
- Respect `prefers-color-scheme`, but default to dark.
- Avoid fixed pixel heights for text containers.
- Use responsive grid and flex layouts.
- Avoid text overlap at small widths.

### HTML

- Use one `h1` per page.
- Keep heading order logical.
- Use real form controls.
- Use native validation where useful.
- Use `fieldset` and `legend` for grouped controls.
- Use `label` for every input.
- Use `output`, `meter`, and `progress` when meaningful.

### Testing

- Add backend tests for recipe parsing.
- Add backend tests for command construction.
- Add backend tests for validation failures.
- Add accessibility checks with Lighthouse or axe.
- Add manual keyboard test notes.
- Test with at least one real recipe:

```bash
./run-recipe.sh translategemma-4b-it --solo --port 8001
```

Use dry run first:

```bash
./run-recipe.sh translategemma-4b-it --solo --port 8001 --dry-run
```

## Implementation Phases

### Phase 1: Read-Only Dashboard

Build:

- Backend server.
- Static frontend shell.
- `GET /api/recipes`.
- `GET /api/gpu`.
- `GET /api/system`.
- `GET /api/runtimes`.
- Overview page.
- Recipes page.

Done when:

- Recipes are listed from YAML files.
- GPU memory is visible.
- Running containers or processes are visible.
- UI passes keyboard navigation smoke test.

### Phase 2: Safe Launch Flow

Build:

- Launch page.
- Recipe-specific launch form.
- Command preview.
- Dry-run action.
- Real launch action.
- Launch registry.

Done when:

- `translategemma-4b-it` can be launched with `--solo --port 8001`.
- Invalid ports are rejected.
- Unknown recipes are rejected.
- No raw shell command is accepted.

### Phase 3: Runtime Management

Build:

- Runtime detail page.
- Stop action.
- Restart action.
- Logs page.
- Health checks.
- Runtime status transitions.

Done when:

- A dashboard-launched runtime can be stopped.
- Logs are visible.
- Health status updates without page reload.
- Destructive actions ask for confirmation.

### Phase 4: Executive Demo Mode

Build:

- Demo-friendly Overview state.
- Capability labels.
- Cleaner summary copy.
- Optional full-screen mode.
- Optional exportable status summary.

Done when:

- A manager can understand the system state in under 30 seconds.
- Advanced technical details do not dominate the first screen.
- Live operational data is still accurate.

### Phase 5: Hardening

Build:

- Authentication for control actions.
- Security headers.
- PWA install support.
- Offline fallback.
- Lighthouse checks.
- Mozilla Observatory checks.
- Basic CI checks if the repo uses CI.

Done when:

- Lighthouse is green.
- WCAG AA checks pass.
- Mozilla Observatory reaches A+ or has documented local-environment exceptions.
- The app is installable as a PWA.

## Acceptance Criteria

The project is ready when:

- The dashboard opens locally in a browser.
- `Overview`, `Recipes`, `Launch`, `Runtime`, `Logs`, and `Settings` use consistent names.
- Recipes are read from `~/Documents/spark-vllm-docker/recipes`.
- At least one recipe can be launched from the UI.
- The UI can launch `translategemma-4b-it` in solo mode on port `8001`.
- GPU memory usage is visible.
- Running runtimes are visible.
- Logs are available.
- Stop action works for dashboard-launched runtimes.
- All state-changing actions are protected.
- The frontend is WCAG AA compliant.
- Lighthouse is green.
- The app is a valid PWA.
- Mozilla Observatory target is A+.
- Text is written in clear B2-level English.
- The frontend uses native browser features as much as practical.

## Open Decisions

- Use FastAPI or Flask for the backend.
- Use plain HTML templates or static HTML with API-driven JavaScript.
- Decide whether launch controls require a password, token, or local-only access.
- Decide whether the dashboard should support cluster launch in the first version or after solo launch works.
- Decide whether runtime detection should rely mainly on Docker labels, container names, or a dashboard registry.

## Preferred First Build

Start with this narrow slice:

1. Create backend and static frontend.
2. Read recipes from YAML.
3. Show the Overview and Recipes pages.
4. Show GPU memory from `nvidia-smi`.
5. Add a Launch page for `translategemma-4b-it`.
6. Support dry run.
7. Support real launch with `--solo --port 8001`.
8. Add basic runtime tracking.

This gives a useful demo quickly while keeping the foundation safe and clean.
