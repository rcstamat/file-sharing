import os
import time
import socket
import argparse
from threading import Thread
from watchdog import events

from event_monitor import EventMonitor
from event_monitor import IsReadyToSync
from file_manager import FileManager
from host import Host


class Client(Thread, Host):
    def __init__(self, shared_folder, ip='0.0.0.0', port=60000):
        Thread.__init__(self)
        Host.__init__(self)
        self.ip = ip
        self.port = port
        self.socket = None
        self.sync_mode = None
        self.shared_folder = shared_folder

    def total_sync(self, fm):
        '''
        Sync the offline content with the server
        '''
        if self.sync_mode == self.SyncMode.SERVER_OVERWRITING_PRIORITY:
            for x in fm.list_to_event(fm.matched, events.EVENT_TYPE_MODIFIED):
                self.transaction_receive_modified(x, fm)
            for x in fm.list_to_event(fm.local_only, events.EVENT_TYPE_DELETED):
                self.transaction_remove(x, fm)
            for x in fm.list_to_event(fm.remote_empty_folders, events.EVENT_TYPE_CREATED, True):
                self.transaction_created_folders(x, fm)
            for x in fm.list_to_event(fm.remote_only, events.EVENT_TYPE_CREATED):
                self.transaction_receive_created(x, fm)
        elif self.sync_mode == self.SyncMode.CLIENT_OVERWRITING_PRIORITY:
            for x in fm.list_to_event(fm.matched, events.EVENT_TYPE_MODIFIED):
                self.transaction_send_modified(x, fm)
            for x in fm.list_to_event(fm.local_only, events.EVENT_TYPE_CREATED):
                self.transaction_send_created(x, fm)
        if self.sync_mode == self.SyncMode.SERVER_PRIORITY:
            for x in fm.list_to_event(fm.matched, events.EVENT_TYPE_MODIFIED):
                self.transaction_receive_modified(x, fm)
            for x in fm.list_to_event(fm.remote_only, events.EVENT_TYPE_CREATED):
                self.transaction_receive_created(x, fm)
            for x in fm.list_to_event(fm.remote_empty_folders, events.EVENT_TYPE_CREATED, True):
                self.transaction_created_folders(x, fm)
            for x in fm.list_to_event(fm.local_only, events.EVENT_TYPE_CREATED):
                self.transaction_send_created(x, fm)
        elif self.sync_mode == self.SyncMode.CLIENT_PRIORITY:
            for x in fm.list_to_event(fm.matched, events.EVENT_TYPE_MODIFIED):
                self.transaction_send_modified(x, fm)
            for x in fm.list_to_event(fm.remote_only, events.EVENT_TYPE_CREATED):
                self.transaction_receive_created(x, fm)
            for x in fm.list_to_event(fm.remote_empty_folders, events.EVENT_TYPE_CREATED, True):
                self.transaction_created_folders(x, fm)
            for x in fm.list_to_event(fm.local_only, events.EVENT_TYPE_CREATED):
                self.transaction_send_created(x, fm)

    def run(self):
        self.socket = socket.socket()
        try:
            self.socket.connect((self.ip, self.port))
            print("Connected to server")
        except socket.error as e:
            print("Could not connect to server", str(e))

        self.sync_mode = int(self.receive_fixed_string_size())
        event_list = []

        # send file list
        fm = FileManager(self.shared_folder)
        fm.remote_rel_paths = self.receive_object()
        self.send_object(fm.local_rel_paths)
        fm.remote_empty_folders = self.receive_object()
        self.send_object(fm.local_empty_folder)
        fm.calc_matched_files()
        self.total_sync(fm)
        fm.clear_exceptions()

        print("Shared folder is now in sync")
        watchdog = EventMonitor(self.shared_folder)
        watchdog.start()

        msg = self.Msg.e
        while True:
            msg = self.receive_fixed_string_size()
            if watchdog.q.empty():
                self.send_fixed_string_size(str(msg))
            else:
                if IsReadyToSync.ready:
                    event_list = self.filter_queue(watchdog.q, fm)
                    if msg == self.Msg.s:
                        if self.sync_mode == self.SyncMode.CLIENT_PRIORITY or self.sync_mode == self.SyncMode.CLIENT_OVERWRITING_PRIORITY:
                            msg = self.Msg.cs
                        elif self.sync_mode == self.SyncMode.SERVER_PRIORITY or self.sync_mode == self.SyncMode.SERVER_OVERWRITING_PRIORITY:
                            msg = self.Msg.sc
                    else:
                        if event_list:
                            msg = self.Msg.c
                self.send_fixed_string_size(str(msg))

            time.sleep(1)
            if msg == self.Msg.e:
                print(".", end='', flush=True)
            elif msg == self.Msg.s:
                print("* server sync")
                self.receive_all_data(fm)
            elif msg == self.Msg.c:
                print("* client sync")
                self.send_all_data(event_list, fm)
            elif msg == self.Msg.sc:
                print("* server followed by client sync")
                self.receive_all_data(fm)
                self.send_all_data(event_list, fm)
            elif msg == self.Msg.cs:
                print("* client ollowed by server sync")
                self.receive_all_data(fm)
                self.send_all_data(event_list, fm)
            elif msg == self.Msg.x:
                self.socket.close()
            else:
                print("Fatal exception, message incorrect", msg)
                self.socket.close()
            msg = self.Msg.e


def main(args):
    if not args.shared_folder.endswith(os.sep):
        args.shared_folder = args.shared_folder + os.sep
    shared_folder = os.path.join(os.path.abspath(os.curdir), args.shared_folder)
    Client(shared_folder, args.ip, args.port).start()


def dir_path(string):
    if os.path.isdir(string):
        return string
    else:
        raise SystemExit("Not a valid directory path for shared folder: " + string)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument('shared_folder', type=dir_path,
                        help='shared folder path')
    parser.add_argument('--ip', dest='ip', type=str,
                        help='ip', default='0.0.0.0', nargs='?')
    parser.add_argument('--port', dest='port', type=int,
                        help='port number', default=50000, nargs='?')

    args = parser.parse_args()
    main(args)
