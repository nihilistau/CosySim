/**
 * CosySim PM2 Ecosystem Configuration
 * =====================================
 * Declarative process definitions for all CosySim services and scenes.
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

module.exports = {
  apps: [

    // ──── Core Services ──────────────────────────────────────────────

    {
      name: 'cosysim-launcher',
      script: 'launcher.py',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: '--core',
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'launcher-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'launcher-out.log'),
      merge_logs: true,
      // Launcher manages all Flask/FastAPI services internally via threads
      // Use this for the recommended "single-process" mode
    },

    // ──── Scheduler Daemon ───────────────────────────────────────────

    {
      name: 'cosysim-scheduler',
      script: '-m',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'engine.nexus.scheduler_daemon',
      autorestart: true,
      max_restarts: 10,
      restart_delay: 10000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scheduler-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scheduler-out.log'),
      merge_logs: true,
      cron_restart: '0 4 * * *',  // Daily restart at 4 AM for clean state
    },

    // ──── TTS Server (standalone — not started by launcher) ──────────

    {
      name: 'cosysim-tts',
      script: '-c',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: '"import uvicorn; from engine.tts.qwen3_server import create_tts_app; uvicorn.run(create_tts_app(), host=\\"0.0.0.0\\", port=8600, log_level=\\"warning\\")"',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'tts-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'tts-out.log'),
      merge_logs: true,
    },

    // ──── Nexus Canvas (Node.js app) ─────────────────────────────────

    {
      name: 'cosysim-canvas',
      script: 'npm',
      args: 'run dev',
      cwd: path.join(PROJECT_ROOT, 'content', 'apps', 'notebook_canvas'),
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
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

    {
      name: 'cosysim-dashboard',
      script: '-m',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'streamlit run content/scenes/dashboard/dashboard_v2.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false --logger.level=warning',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'dashboard-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'dashboard-out.log'),
      merge_logs: true,
    },

    {
      name: 'cosysim-admin',
      script: '-m',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'streamlit run content/scenes/admin/admin_panel.py --server.port=8502 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false --logger.level=warning',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'admin-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'admin-out.log'),
      merge_logs: true,
    },

    {
      name: 'cosysim-assets',
      script: '-m',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'streamlit run content/scenes/assets/asset_generator.py --server.port=8503 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false --logger.level=warning',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'assets-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'assets-out.log'),
      merge_logs: true,
    },

    {
      name: 'cosysim-creator',
      script: '-m',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'streamlit run content/scenes/hub/scene_creator.py --server.port=8504 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false --logger.level=warning',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'creator-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'creator-out.log'),
      merge_logs: true,
    },

    // ──── Individual Scene Processes (for granular PM2 control) ──────
    // These are alternatives to running everything via the launcher.
    // Use --only flags to start specific scenes independently.

    {
      name: 'cosysim-scene-phone',
      script: 'launcher.py',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'phone',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scene-phone-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scene-phone-out.log'),
      merge_logs: true,
    },

    {
      name: 'cosysim-scene-penthouse',
      script: 'launcher.py',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'penthouse',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scene-penthouse-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scene-penthouse-out.log'),
      merge_logs: true,
    },

    {
      name: 'cosysim-scene-neoncity',
      script: 'launcher.py',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'neoncity',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scene-neoncity-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scene-neoncity-out.log'),
      merge_logs: true,
    },

    {
      name: 'cosysim-scene-intel-hub',
      script: 'launcher.py',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'intel_hub',
      autorestart: true,
      max_restarts: 5,
      restart_delay: 5000,
      watch: false,
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scene-intel-hub-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'scene-intel-hub-out.log'),
      merge_logs: true,
    },

    // ──── Cron-Style Maintenance Tasks ───────────────────────────────

    {
      name: 'cosysim-nexus-maintenance',
      script: '-m',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'engine.nexus.bridge maintain health',
      autorestart: false,
      watch: false,
      cron_restart: '0 3 * * *',  // Daily at 3 AM
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'maintenance-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'maintenance-out.log'),
      merge_logs: true,
    },

    {
      name: 'cosysim-nexus-backup',
      script: '-m',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'engine.nexus.bridge maintain dedup',
      autorestart: false,
      watch: false,
      cron_restart: '0 2 * * 0',  // Weekly Sunday at 2 AM
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'backup-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'backup-out.log'),
      merge_logs: true,
    },

    {
      name: 'cosysim-copilot-reseed',
      script: '-m',
      interpreter: 'python',
      cwd: PROJECT_ROOT,
      args: 'engine.nexus.seed_copilot_rules',
      autorestart: false,
      watch: false,
      cron_restart: '30 3 * * *',  // Daily at 3:30 AM
      env: {
        PYTHONPATH: PROJECT_ROOT,
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'reseed-error.log'),
      out_file: path.join(PROJECT_ROOT, 'logs', 'pm2', 'reseed-out.log'),
      merge_logs: true,
    },
  ],
};
