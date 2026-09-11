"""Uvicorn entrypoint for the Docker deployment."""

import os

import uvicorn

from .app import create_app


def main() -> None:
    uvicorn.run(
        create_app(
            recovery_interval=float(os.environ.get("TG_IFTTT_RECOVERY_INTERVAL", "2")),
            scheduler_interval=float(os.environ.get("TG_IFTTT_SCHEDULER_INTERVAL", "20")),
            event_poll_interval=float(os.environ.get("TG_IFTTT_EVENT_POLL_INTERVAL", "5")),
        ),
        host=os.environ.get("TG_IFTTT_HOST", "0.0.0.0"),
        port=int(os.environ.get("TG_IFTTT_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
