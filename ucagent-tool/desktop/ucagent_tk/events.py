"""Bounded SSE handoff with UI-consumed cursors and cooperative reader shutdown."""

import queue
import threading


class EventFeed:
    """Reconnect a single run stream without performing any Tk operations in a worker."""

    def __init__(self, client, run_id, cursor=0):
        """Start a daemon reader; the UI owns acknowledgement and cursor persistence."""
        self.client = client
        self.run_id = run_id
        self.cursor = cursor
        self.cancel = threading.Event()
        self.messages = queue.Queue(maxsize=1000)
        threading.Thread(target=self._read, name="desktop-events", daemon=True).start()

    def _put(self, kind, value):
        """Apply backpressure without dropping evidence or blocking shutdown."""
        while not self.cancel.is_set():
            try:
                self.messages.put((kind, value), timeout=0.2)
                return True
            except queue.Full:
                continue
        return False

    def _read(self):
        """Resume from the last queued event while the UI separately persists consumed ids."""
        received = self.cursor
        while not self.cancel.is_set():
            self._put("status", "stream_connecting")
            try:
                for event in self.client.events(self.run_id, received, self.cancel):
                    if not self._put("event", event):
                        return
                    received = event["sequence"]
                self._put("status", "stream_retry")
            except Exception as exc:
                self._put("error", str(exc)[:1000])
            if self.cancel.wait(1.5):
                return

    def close(self):
        """Cancel this local reader without cancelling the remote run."""
        self.cancel.set()
