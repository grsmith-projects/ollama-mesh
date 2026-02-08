# Heartbeat Schedule

Periodic tasks this agent runs autonomously. Uses cron-like syntax.

## Tasks

### system-health
- **schedule**: */5 * * * *
- **prompt**: Check system load, memory, and disk usage. Report anything unusual.
- **broadcast**: false

### peer-rollcall
- **schedule**: */15 * * * *
- **prompt**: Ping all known peers and summarize which are online and what skills they offer.
- **broadcast**: false

### daily-summary
- **schedule**: 0 9 * * *
- **prompt**: Produce a brief summary of yesterday's peer interactions and any notable events.
- **broadcast**: true
