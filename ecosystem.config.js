/**
 * CosySim PM2 Ecosystem Configuration
 * =====================================
 * Declarative process definitions for all CosySim services and scenes.
 *
 * WINDOWS COMPATIBILITY:
 *   - Python `-m module` entries use wrapper scripts in scripts/pm2/
 *     because PM2 treats `script: '-m'` as a literal filename on Windows.
 *   - Python `-c` entries are replaced by dedicated wrapper scripts.
 *   - Node.js services use direct paths (not npx) to avoid cmd.exe windows.
 *   - All subprocess calls should use CREATE_NO_WINDOW on Windows.
 *
 * Usage:
 *   pm2 start ecosystem.config.js           # Start all enabled processes
 *   pm2 start ecosystem.config.js --only hub # Start specific process
 *   pm2 stop all                             # Stop everything
 *   pm2 restart cosysim-hub                  # Restart specific process
 *   pm2 save                                 # Persist process list
 *   pm2 resurrect                            # Restore after reboot
 *
 * Process naming convention: cosysim-{target_id}
 * All ports sourced from engine/port_registry.py via control_plane_registry.py
 */

const path = require('path');
const PROJECT_ROOT = __dirname;

// Helper: build a Python service entry using a wrapper script
function pyService(name, script, opts = {}) {
  return {
    name: `cosysim-${name}`,
    script: script,
    interpreter: 'python',
    cwd: PROJECT_ROOT,
    autorestart: opts.autorestart !== undefined ? opts.autorestart : true,
    max_restarts: opts.max_restarts || 10,
    restart_delay: opts.restart_delay || 5000,
    watch: false,
    windowsHide: true,
    env: {
      PYTHONPATH: PROJECT_ROOT,
      PYTHONUNBUFFERED: '1',
      ...(opts.env || {}),
    },
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', `${name}-error.log`),
    out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', `${name}-out.log`),
    merge_logs: true,
    ...(opts.args ? { args: opts.args } : {}),
    ...(opts.cron_restart ? { cron_restart: opts.cron_restart } : {}),
  };
}

// Helper: build a scene entry (all scenes use launcher.py with scene name arg)
function sceneService(sceneName, pmName) {
  return pyService(pmName || `scene-${sceneName}`, 'launcher.py', {
    args: sceneName,
    max_restarts: 5,
  });
}

module.exports = {
  apps: [

    // ──── Nexus KMS (must start before all CosySim services) ────────

    pyService('nexus-kms', path.join('scripts', 'pm2', 'start_nexus_kms.py'), {
      max_restarts: 10,
      restart_delay: 5000,
    }),

    // ──── Core Services ──────────────────────────────────────────────

    pyService('launcher', 'launcher.py', {
      args: '--core',
      // Launcher manages all Flask/FastAPI services internally via threads.
      // Use this for the recommended "single-process" mode.
    }),

    // ──── Scheduler Daemon ───────────────────────────────────────────

    pyService('scheduler', path.join('scripts', 'pm2', 'scheduler.py'), {
      restart_delay: 10000,
      cron_restart: '0 4 * * *',  // Daily restart at 4 AM for clean state
    }),

    // ──── TTS Server (standalone — not started by launcher) ──────────

    pyService('tts', path.join('scripts', 'pm2', 'start_tts.py'), {
      max_restarts: 5,
    }),

    // ──── Nexus Canvas (Node.js app) ─────────────────────────────────

    {
      name: 'cosysim-canvas',
      script: path.join('node_modules', '.bin', 'tsx.cmd'),
      args: 'server.ts',
      cwd: path.join(PROJECT_ROOT, 'content', 'apps', 'notebook_canvas'),
      interpreter: 'none',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      windowsHide: true,
      env: {
        NODE_ENV: 'production',
        PORT: '5590',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'canvas-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'canvas-out.log'),
      merge_logs: true,
    },

    // ──── Streamlit Services ─────────────────────────────────────────
    // All Streamlit entries use the wrapper to avoid PM2 -m flag issues.

    pyService('dashboard', path.join('scripts', 'pm2', 'start_streamlit.py'), {
      args: 'content/scenes/dashboard/dashboard_v2.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false --logger.level=warning',
      max_restarts: 5,
    }),

    pyService('admin', path.join('scripts', 'pm2', 'start_streamlit.py'), {
      args: 'content/scenes/admin/admin_panel.py --server.port=8502 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false --logger.level=warning',
      max_restarts: 5,
    }),

    pyService('assets', path.join('scripts', 'pm2', 'start_streamlit.py'), {
      args: 'content/scenes/assets/asset_generator.py --server.port=8503 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false --logger.level=warning',
      max_restarts: 5,
    }),

    pyService('creator', path.join('scripts', 'pm2', 'start_streamlit.py'), {
      args: 'content/scenes/hub/scene_creator.py --server.port=8504 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false --logger.level=warning',
      max_restarts: 5,
    }),

    // ──── Individual Scene Processes (for granular PM2 control) ──────
    // These are alternatives to running everything via the launcher.
    // Use --only flags to start specific scenes independently.

    sceneService('phone'),
    sceneService('penthouse'),
    sceneService('neoncity'),
    sceneService('intel_hub', 'scene-intel-hub'),

    // ──── Cron-Style Maintenance Tasks ───────────────────────────────

    pyService('nexus-maintenance', path.join('scripts', 'pm2', 'nexus_maintenance.py'), {
      autorestart: false,
      cron_restart: '0 3 * * *',  // Daily at 3 AM
    }),

    pyService('nexus-backup', path.join('scripts', 'pm2', 'nexus_dedup.py'), {
      autorestart: false,
      cron_restart: '0 2 * * 0',  // Weekly Sunday at 2 AM
    }),

    pyService('copilot-reseed', path.join('scripts', 'pm2', 'copilot_reseed.py'), {
      autorestart: false,
      cron_restart: '30 3 * * *',  // Daily at 3:30 AM
    }),
  ],
};

