---
description: 'CosySim frontend conventions — Jinja2 templates, vanilla JS, Socket.IO real-time, CSS styling, no build tools'
applyTo: 'content/scenes/**/templates/**,content/scenes/**/static/**'
---

# Frontend Conventions

## Templates (Jinja2)
- HTML5 with semantic elements
- Double quotes for HTML attributes
- Template variables: `{{ variable }}`
- Template blocks: `{% block content %}{% endblock %}`
- Include Socket.IO client for real-time updates

## JavaScript
- Vanilla JS (no React/Vue/Angular — no build step)
- 2-space indentation
- Single quotes for strings
- Use `const` and `let`, never `var`
- Use `fetch()` for API calls, never XMLHttpRequest
- Connect to Socket.IO: `const socket = io()`
- Handle connection errors gracefully

## CSS
- 2-space indentation
- Use CSS custom properties for theming: `--primary-color`, `--bg-color`
- Mobile-responsive with media queries
- Prefer flexbox/grid over floats
- Class naming: kebab-case (`game-panel`, `chat-message`)

## Socket.IO Events
- Emit user actions: `socket.emit('action', {type: '...', data: {...}})`
- Listen for updates: `socket.on('state_update', (data) => {...})`
- Listen for messages: `socket.on('message', (msg) => {...})`
- Handle reconnection: `socket.on('reconnect', () => {...})`

## Asset Paths
- Static files served from scene's `static/` directory
- Reference: `{{ url_for('static', filename='scene.css') }}`
- Images in `static/img/`, scripts in `static/js/`
