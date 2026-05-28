/**
 * PM2 ecosystem config for Roundtable Web Viewer.
 *
 * Usage:
 *   pm2 start ecosystem.config.cjs -- --port 8199 --data-dir /tmp/roundtable_web
 *
 * One shared instance serves all discussions under --data-dir.
 */
module.exports = {
  apps: [
    {
      name: "roundtable-web",
      script: "./server.mjs",
      interpreter: "node",
      instances: 1,
      autorestart: true,
      max_restarts: 5,
      restart_delay: 2000,
      watch: false,
      max_memory_restart: "256M",
      env: {
        NODE_ENV: "production",
      },
    },
  ],
};
