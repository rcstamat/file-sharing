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


class Server:
    def __init__(self, shared_folder='', sync_mode=0, port=60000):
        self.ip = '0.0.0.0'
        self.port = port
        self.server_socket = None
        self.sync_mode = sync_mode
        self.shared_folder = shared_folder

    def server_start(self):
        print("Starting server on port:", self.port)
        print("Shared folder:", self.shared_folder)
        print("Sync mode:", self.sync_mode)
        try:
            self.server_socket = socket.socket()
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.ip, self.port))
            self.server_socket.listen(1)
        except socket.error as e:
            print("Could not establish server", e)

        while True:
            client_socket, client_address = self.server_socket.accept()
            print('Connected to: ' + client_address[0] + ':' + str(client_address[1]))
            ServerConn(client_socket, self.shared_folder, self.sync_mode).start()


class ServerConn(Thread, Host):
    def __init__(self, server_socket, shared_folder, sync_mode):
        Thread.__init__(self)
        Host.__init__(self)
        self.shared_folder = shared_folder
        self.socket = server_socket
        self.sync_mode = sync_mode

    def total_sync(self, fm):
        '''
        Sync the offline content with the client
        '''
        if self.sync_mode == self.SyncMode.SERVER_OVERWRITING_PRIORITY:
            for x in fm.list_to_event(fm.matched, events.EVENT_TYPE_MODIFIED):
                self.transaction_send_modified(x, fm)
            for x in fm.list_to_event(fm.local_only, events.EVENT_TYPE_CREATED):
                self.transaction_send_created(x, fm)
        elif self.sync_mode == self.SyncMode.CLIENT_OVERWRITING_PRIORITY:
            for x in fm.list_to_event(fm.matched, events.EVENT_TYPE_MODIFIED):
                self.transaction_receive_modified(x, fm)
            for x in fm.list_to_event(fm.local_only, events.EVENT_TYPE_DELETED):
                self.transaction_remove(x, fm)
            for x in fm.list_to_event(fm.remote_empty_folders, events.EVENT_TYPE_CREATED, True):
                self.transaction_created_folders(x, fm)
            for x in fm.list_to_event(fm.remote_only, events.EVENT_TYPE_CREATED):
                self.transaction_receive_created(x, fm)
        elif self.sync_mode == self.SyncMode.SERVER_PRIORITY:
            for x in fm.list_to_event(fm.matched, events.EVENT_TYPE_MODIFIED):
                self.transaction_send_modified(x, fm)
            for x in fm.list_to_event(fm.local_only, events.EVENT_TYPE_CREATED):
                self.transaction_send_created(x, fm)
            for x in fm.list_to_event(fm.remote_empty_folders, events.EVENT_TYPE_CREATED, True):
                self.transaction_created_folders(x, fm)
            for x in fm.list_to_event(fm.remote_only, events.EVENT_TYPE_CREATED):
                self.transaction_receive_created(x, fm)
        elif self.sync_mode == self.SyncMode.CLIENT_PRIORITY:
            for x in fm.list_to_event(fm.matched, events.EVENT_TYPE_MODIFIED):
                self.transaction_receive_modified(x, fm)
            for x in fm.list_to_event(fm.local_only, events.EVENT_TYPE_CREATED):
                self.transaction_send_created(x, fm)
            for x in fm.list_to_event(fm.remote_empty_folders, events.EVENT_TYPE_CREATED, True):
                self.transaction_created_folders(x, fm)
            for x in fm.list_to_event(fm.remote_only, events.EVENT_TYPE_CREATED):
                self.transaction_receive_created(x, fm)

    def run(self):

        event_list = []
        self.sync_mode = self.sync_mode
        self.send_fixed_string_size(str(self.sync_mode))

        # send file list
        fm = FileManager(self.shared_folder)
        self.send_object(fm.local_rel_paths)
        fm.remote_rel_paths = self.receive_object()
        self.send_object(fm.local_empty_folder)
        fm.remote_empty_folders = self.receive_object()
        fm.calc_matched_files()
        self.total_sync(fm)
        fm.clear_exceptions()

        print("Shared folder is now in sync")
        watchdog = EventMonitor(self.shared_folder)
        watchdog.start()

        msg = self.Msg.e
        while True:
            if watchdog.q.empty():
                self.send_fixed_string_size(str(msg))
                msg = self.receive_fixed_string_size()
            else:
                if IsReadyToSync.ready:
                    msg = self.Msg.s
                    event_list = self.filter_queue(watchdog.q, fm)
                    self.send_fixed_string_size(str(msg))
                    msg = self.receive_fixed_string_size()
                    if msg == self.Msg.c:
                        if self.sync_mode == self.SyncMode.CLIENT_PRIORITY or self.sync_mode == self.SyncMode.CLIENT_OVERWRITING_PRIORITY:
                            msg = self.Msg.cs
                        elif self.sync_mode == self.SyncMode.SERVER_PRIORITY or self.sync_mode == self.SyncMode.SERVER_OVERWRITING_PRIORITY:
                            msg = self.Msg.sc

                else:
                    msg = self.Msg.e
                    self.send_fixed_string_size(str(msg))
                    msg = self.receive_fixed_string_size()

            time.sleep(1)
            if msg == self.Msg.e:
                print(".", end='', flush=True)
            elif msg == self.Msg.s:
                print("* server sync")
                self.send_all_data(event_list, fm)
            elif msg == self.Msg.c:
                print("* client sync")
                self.receive_all_data(fm)
            elif msg == self.Msg.sc:
                print("* server followed by client sync")
                self.receive_all_data(fm)
                self.send_all_data(event_list, fm)
            elif msg == self.Msg.cs:
                print("* client followed by server sync")
                self.send_all_data(event_list, fm)
                self.receive_all_data(fm)
            elif msg == self.Msg.x:
                self.socket.close()
            else:
                print("Fatal exception, message incorrect", msg)
                self.socket.close()
            msg = self.Msg.e


def main(args):
    if not args.shared_folder.endswith(os.sep):
        args.shared_folder = args.shared_folder + os.sep
    if args.sync_mode < 0 or args.sync_mode > 3:
        raise ValueError("Sync mode can only be between 0 and 3")
    shared_folder = os.path.join(os.path.abspath(os.curdir), args.shared_folder)
    s = Server(shared_folder, args.sync_mode, args.port)
    s.server_start()


def dir_path(string):
    if os.path.isdir(string):
        return string
    else:
        raise SystemExit("Not a valid directory path for shared folder: " + string)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('shared_folder', type=dir_path,
                        help='shared folder path')
    parser.add_argument('--mode', dest='sync_mode', type=int,
                        help='sync mode', default='0')
    parser.add_argument('--port', dest='port', type=int,
                        help='port number', default='50000')
    args = parser.parse_args()
    main(args)
