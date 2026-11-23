"""Lifecycle wrapper for the existing watchdog engine, intended for Streamlit."""

from __future__ import annotations

from watch_folder import WatchFolderService


class WatchController:
    def __init__(self, organizer, **kwargs):
        self.service = WatchFolderService(organizer, **kwargs)
        self.observer = None

    def start(self):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        if self.observer is not None:
            raise RuntimeError("Watcher already started.")

        service = self.service

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    service.submit(event.src_path)

            def on_modified(self, event):
                if not event.is_directory:
                    service.submit(event.src_path)

            def on_moved(self, event):
                if not event.is_directory:
                    service.submit(event.dest_path)

            def on_closed(self, event):
                if not event.is_directory:
                    service.submit(event.src_path)

        observer = Observer()
        observer.schedule(Handler(), str(service.root), recursive=True)
        observer.start()
        self.observer = observer

    def stats(self):
        with self.service._state_lock:
            return dict(self.service._stats)

    def stop(self):
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        return self.service.shutdown(wait=True)
