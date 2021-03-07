from queue import Queue
from threading import Thread, Timer, Lock
from datetime import timedelta
import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class IsReadyToSync:
    ready = False


class EventMonitor(Thread):
    '''
    Thread for generating file events into a queue
    '''

    def __init__(self, path):
        Thread.__init__(self)
        self.path = path
        self.ready = False
        self.q = Queue()

    def run(self):

        event_handler = MyEvent(self.q)
        observer = Observer()
        observer.schedule(event_handler, self.path, recursive=True)
        observer.start()
        try:
            while True:
                time.sleep(1)
        finally:
            observer.stop()
            observer.join()


class MyEvent(FileSystemEventHandler):
    def __init__(self, q):
        self.last_modified_time = time.perf_counter()
        self.timer = None
        self.mutex = Lock()
        self.q = q

    def on_any_event(self, event):
        super().on_any_event(event)
        self.last_modified_time = time.perf_counter()
        IsReadyToSync.ready = False
        self.mutex.acquire()
        if not self.timer:
            self.timer = True
            self.mutex.release()
            Timer(2, self.event_timer).start()
        else:
            self.mutex.release()

    def on_created(self, event):
        super().on_created(event)
        self.q.put(event)

    def on_modified(self, event):
        super().on_modified(event)
        if not event.is_directory:
            self.q.put(event)

    def on_moved(self, event):
        super().on_moved(event)
        self.q.put(event)

    def on_deleted(self, event):
        super().on_deleted(event)
        self.q.put(event)

    def event_timer(self):
        """
        Announces when there haven't been any new events for 2 seconds
        """
        while True:
            if (time.perf_counter() - self.last_modified_time) > timedelta(seconds=2).seconds:
                IsReadyToSync.ready = True
                self.mutex.acquire()
                self.timer = False
                self.mutex.release()
                return
            else:
                time.sleep(1)
