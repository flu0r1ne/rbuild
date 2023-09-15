# Docker Auto Rebuild Script (`rbuild`)

> Note: This script is experimental. Contributions are welcome.

This short Python script automatically rebuilds Docker Compose deployments to apply security updates
and pull new images, ideally from a stable release if the application is well containerized. Docker
Compose is frequently used for small one-off deployments in CI/CD pipelines, small to medium businesses,
and self-hosted services. In such scenarios, utilizing a full-fledged container registry and monitoring
service like `Watchtower` might be excessive. This is a lightweight, zero-dependency script that can be
scheduled using `cron` or a similar task scheduler. It triggers a rebuild if `BUILD_TTL` seconds have passed,
if the configuration file changes, or if the `--force-rebuild` flag is set. The script also cleans up old containers
after rebuilding. It assumes that security updates will be applied during the build process and invalidates the image
cache to ensure a rebuild.

However, this script has *numerous limitations*. It is not suitable for environments requiring high availability, as
it lacks support for rolling updates and rollbacks in the event of container failures. Additionally, it doesn't offer
auto-scaling capabilities. For those requirements, consider using Kubernetes or a similar orchestration platform.

> Initially, my ambition was to design a system that could automatically roll back if an image failed after an update.
In fact, I planned to implement a rollback policy akin to Docker's own `restart-policy`. If I was going to take this on,
I wanted to do it right. That meant the program would need to daemonize itself, listen for `docker events` to catch any
container failures, and use a timer to trigger rebuilds. Things quickly became complicated as I considered the state management
needed for each service—each potentially having fallback images, active images, and newly built images. I also considered
questions like how the daemon would maintain its state across restarts, and what the consequences might be if a human operator
were to accidentally remove images. These are all legitimate questions with viable solutions, but as I stared at the escalating
complexity of the required state machine, I realized this wasn't something I could knock out in a single night. While it's still
on my radar, it's taken a backseat since this simpler version fulfills my current needs.

## How to Use

### Cron

To schedule the script to run every 30 minutes on an Ubuntu host, follow these steps:

1. Make the script executable:

	```
	chmod +x rbuild.py
	mv rbuild.py /usr/local/bin/
	```

2. Open the crontab editor:

	```
	crontab -e
	```

3. Add the following line to run the script every 30 minutes:

	```
	*/30 * * * * /usr/local/bin/rbuild.py /path/to/your/compose.yml
	```

### systemd

Rebuild the site at 3 AM.

```
[Unit]
Description=Rebuild site

[Service]
ExecStart=/usr/local/bin/rbuild.py /path/to/your/compose.yml --force-rebuild
```

```
[Unit]
Description=Rebuild site at 3AM

[Timer]
OnBootSec=3min
# 3AM
OnCalendar=*-*-* 3:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### Environment Variables

- `BUILD_PERIOD`: Time (in seconds) after which the script triggers a rebuild. Defaults to 86400 (1 day).
- `UP_TIMEOUT_PERIOD`: Time (in seconds) that the script will wait while bringing up containers. Defaults to 60 seconds.

## Usage

```
usage: rbuild.py [-h] [--build-period BUILD_PERIOD] [--up-timeout-period UP_TIMEOUT_PERIOD] [--force-rebuild] [--remove-images] filename [filename ...]

Automatically rebuild a series of containers with docker compose.

positional arguments:
  filename              The docker-compose file to use.

options:
  -h, --help            show this help message and exit
  --build-period BUILD_PERIOD
                        Time images are allowed to live (in seconds.)
  --up-timeout-period UP_TIMEOUT_PERIOD
                        Up timeout period in seconds.
  --force-rebuild       Force all containers to be rebuilt
  --remove-images       Remove all images
```

## License

MIT
