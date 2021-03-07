import os
import pickle
import shutil
from pathlib import Path

from watchdog import events
from hash import Hash


class Host:
    '''
    Base class for client and server
    '''
    MSG_LEN = 256

    class SyncMode:
        CLIENT_PRIORITY = 0
        SERVER_PRIORITY = 1
        CLIENT_OVERWRITING_PRIORITY = 2
        SERVER_OVERWRITING_PRIORITY = 3

    class ReturnCode:
        SUCCESS = "-1"
        FAILURE = "-2"

    class Msg:
        x = 'x'  # exit
        e = 'e'  # empty
        s = 's'  # server only
        c = 'c'  # client only
        sc = 'sc'  # server first, then client
        cs = 'cs'  # client first, then server

    def __init__(self):
        self.socket = None
        self.hash = Hash()

    def send_fixed_string_size(self, string=""):
        """
        Sends the bytearray of size MSG_LEN containing the string
        """
        if len(string) > self.MSG_LEN:
            raise RuntimeError("Input string size is bigger than the MSG_LEN")
        send_msg = bytes(string, encoding='utf-8') + b' ' * (self.MSG_LEN - len(string))
        self.socket.sendall(send_msg)

    def receive_fixed_string_size(self):
        """
        Reads bytes of size MSG_LEN and returns a string
        """
        total_bytes_rcv = 0
        string = b""
        while total_bytes_rcv < self.MSG_LEN:
            bytes_rcv = self.socket.recv(self.MSG_LEN)
            if bytes_rcv == b"":
                return ''
            if string == b"":
                string = bytes_rcv
            else:
                string = bytes_rcv + bytes(string, encoding='utf-8')
            total_bytes_rcv = total_bytes_rcv + len(bytes_rcv)
            try:
                string = string.decode("utf-8")
            except UnicodeDecodeError:
                raise OSError
        if string == b"":
            return ''
        else:
            return string.rstrip()

    def send_object(self, obj):
        """
        Send serialised object
        """
        serialized = pickle.dumps(obj)
        self.send_fixed_string_size(str(len(serialized)))
        self.receive_fixed_string_size()
        self.socket.sendall(serialized)
        self.receive_fixed_string_size()

    def receive_object(self):
        """
        Receive serialised object
        """
        files_len = self.receive_fixed_string_size()
        self.send_fixed_string_size("")
        data_rcv = b""
        while len(data_rcv) < int(files_len):
            data = self.socket.recv(8192)
            data_rcv = data_rcv + data
        self.send_fixed_string_size("")
        obj = pickle.loads(data_rcv)
        return obj

    def send_file(self, file_path):
        """
        Send file through socket.
        """
        size = 0
        try:
            size = str(os.path.getsize(file_path))
            self.send_fixed_string_size(self.ReturnCode.SUCCESS)
        except IOError:
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
            return
        self.send_fixed_string_size(str(size))
        if int(size) == 0:
            return

        try:
            with open(os.path.join(file_path), 'rb') as file:
                self.send_fixed_string_size(self.ReturnCode.SUCCESS)
                if self.receive_fixed_string_size() == self.ReturnCode.SUCCESS:
                    data = file.read(8192)
                    while data:
                        self.socket.send(data)
                        data = file.read(8192)
            self.receive_fixed_string_size()
        except IOError:
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
            self.receive_fixed_string_size()

    def receive_file(self, path):
        """
        Send file through socket
        """
        if self.receive_fixed_string_size() == self.ReturnCode.FAILURE:
            return self.ReturnCode.FAILURE
        length = int(self.receive_fixed_string_size())
        if length != 0:
            length = int(length)
            Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
            try:
                with open(path, 'wb+') as file:
                    if self.receive_fixed_string_size() == self.ReturnCode.SUCCESS:
                        self.send_fixed_string_size(self.ReturnCode.SUCCESS)
                        file.seek(0)
                        while length > 0:
                            data = self.socket.recv(8192)
                            if data == b"":
                                break
                            length = length - len(data)
                            file.write(bytearray(data))
                        self.send_fixed_string_size("")
                    else:
                        self.send_fixed_string_size(self.ReturnCode.FAILURE)
                        return self.ReturnCode.FAILURE

            except IOError:
                self.receive_fixed_string_size()
                self.send_fixed_string_size(self.ReturnCode.FAILURE)
                return self.ReturnCode.FAILURE

        # empty file
        else:
            if not os.path.exists(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with open(path, 'wb+') as file:
                file.write(b"")
        return self.ReturnCode.SUCCESS

    # ____________

    def reconstruct_file(self, file):
        """
        Reconstruct file using delta_1 and delta_2
        """
        abs_path = os.path.join(self.shared_folder, file)
        if not os.path.exists(abs_path):
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
            return self.ReturnCode.FAILURE
        try:
            # check checksum, quick exit if matched
            file_checksum = self.hash.get_file_checksum(abs_path)
            self.send_fixed_string_size(self.ReturnCode.SUCCESS)
            self.send_object((file, file_checksum))
            if self.receive_fixed_string_size() == file_checksum:
                return self.ReturnCode.SUCCESS
        except IOError:
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
            return self.ReturnCode.FAILURE

        try:
            data_list = self.hash.get_file_bytes(abs_path)
            weak, strong = self.hash.get_file_hashes(abs_path)
            delta_1_hash_dict = self.create_dict(weak, strong)
            self.send_fixed_string_size(self.ReturnCode.SUCCESS)
        except IOError:
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
            return self.ReturnCode.FAILURE
        return self.send_delta_1(data_list, file, delta_1_hash_dict)

    def send_delta_1(self, data_list, file_name, delta_1_hash_dict):
        """
        Sends the local delta_1 hashes, receives the remote delta_2 and
        reconstructs the files
        """
        # send delta_1
        delta_1_data = delta_1_hash_dict
        delta_1_size = str(len(pickle.dumps(delta_1_data)))
        self.send_fixed_string_size(delta_1_size)
        self.socket.send(pickle.dumps(delta_1_data))

        # receive delta_2
        if self.receive_fixed_string_size() == self.ReturnCode.SUCCESS:
            delta_2_size = self.receive_fixed_string_size()
            delta_2_obj = b""
            while len(delta_2_obj) < int(delta_2_size):
                tmp = self.socket.recv(8192)
                delta_2_obj = delta_2_obj + tmp
            delta_2_data = pickle.loads(delta_2_obj)
            delta_2_file_name, delta_2_data = delta_2_data

            # only indexes means that local file == remote file
            complete = True
            for x in range(0, len(delta_2_data)):
                if not isinstance(delta_2_data[x], int):
                    if x != delta_2_data[x]:
                        complete = False
            # no need to write
            if complete:
                self.send_fixed_string_size(self.ReturnCode.SUCCESS)
                return self.ReturnCode.SUCCESS

            # remake the file using old data and delta_2
            new_file = os.path.join(self.shared_folder, file_name)
            try:
                with open(new_file, "wb+") as f:
                    for x in range(0, len(delta_2_data)):
                        if isinstance(delta_2_data[x], bytes):
                            f.write(delta_2_data[x])
                        elif isinstance(delta_2_data[x], int):
                            f.write(data_list[delta_2_data[x]])
                        else:
                            raise RuntimeError("Data has been corrupted")
                self.send_fixed_string_size(self.ReturnCode.SUCCESS)
            except IOError:
                self.send_fixed_string_size(self.ReturnCode.FAILURE)
                return self.ReturnCode.FAILURE
            return self.ReturnCode.SUCCESS
        else:
            return self.ReturnCode.FAILURE

    def receive_delta_1(self):
        """
        Received the hashes for delta_1
        """
        delta_1_size = self.receive_fixed_string_size()
        delta_1_obj = b""
        while len(delta_1_obj) < int(delta_1_size):
            tmp = self.socket.recv(8192)
            delta_1_obj = delta_1_obj + tmp
        delta_1_data = pickle.loads(delta_1_obj)
        return delta_1_data

    def send_delta2_file(self):
        """
        Create delta2 based on delta1
        """
        # file checksum check, quick exit if they match
        if self.receive_fixed_string_size() == self.ReturnCode.SUCCESS:
            try:
                remote_rel_path, remote_file_checksum = self.receive_object()
                delta_2_file_name = os.path.join(self.shared_folder, remote_rel_path)
                local_file_checksum = self.hash.get_file_checksum(delta_2_file_name)
                self.send_fixed_string_size(local_file_checksum)
                if remote_file_checksum == local_file_checksum:
                    return self.ReturnCode.SUCCESS
            except IOError:
                self.send_fixed_string_size(self.ReturnCode.FAILURE)
        else:
            return self.ReturnCode.FAILURE

        if self.receive_fixed_string_size() == self.ReturnCode.SUCCESS:
            delta_1_data = self.receive_delta_1()
            delta_1_hash_dict = delta_1_data

            delta_2_data = self.compute_delta_2(delta_2_file_name, delta_1_hash_dict)
            if delta_2_data == self.ReturnCode.FAILURE:
                return self.ReturnCode.FAILURE
            delta_2_obj = pickle.dumps((delta_2_file_name, delta_2_data))
            delta_2_size = str(len(delta_2_obj))
            self.send_fixed_string_size(delta_2_size)
            self.socket.sendall(delta_2_obj)
            if self.receive_fixed_string_size() == self.ReturnCode.SUCCESS:
                return self.ReturnCode.SUCCESS
            else:
                return self.ReturnCode.FAILURE
        else:
            return self.ReturnCode.FAILURE

    def compute_delta_2(self, file, delta_1_hash_dict):
        """
        Calculates the delta_2 hashes based on the remote delta_1 using a rolling checksum algorithm
        """
        delta_2_list = []
        try:
            with open(file, "rb") as f:
                file_bytes = f.read(1)
                windows_hash = 0
                prefix = b""
                window = b""
                found = False

                while file_bytes != b"":
                    if len(window) < self.hash.HASH_BLOCK_SIZE:
                        windows_hash = windows_hash + ord(file_bytes) * 5
                        window = window + file_bytes

                    elif len(window) == self.hash.HASH_BLOCK_SIZE:
                        found = False
                        if windows_hash in delta_1_hash_dict:
                            if isinstance(delta_1_hash_dict[windows_hash], tuple):
                                if self.hash.get_byte_strong_hash(window) == delta_1_hash_dict[windows_hash][0]:
                                    if prefix != b"":
                                        delta_2_list.append(prefix)
                                        prefix = b""
                                    delta_2_list.append(delta_1_hash_dict[windows_hash][1])
                                    window = b""
                                    windows_hash = 0
                                    found = True
                                    continue
                            # multiple elems
                            else:
                                for elem in delta_1_hash_dict[windows_hash]:
                                    if self.hash.get_byte_strong_hash(window) == elem[0]:
                                        if prefix != b"":
                                            delta_2_list.append(prefix)
                                            prefix = b""
                                        delta_2_list.append(elem[1])
                                        window = file_bytes
                                        windows_hash = ord(file_bytes) * 5
                                        found = True
                                        break
                                    else:
                                        continue
                        if not found:
                            prefix = prefix + window[:1]
                        windows_hash = windows_hash - ord(window[:1]) * 5 + ord(file_bytes) * 5
                        window = window[1:] + file_bytes
                    file_bytes = f.read(1)

                if prefix != b"":
                    delta_2_list.append(prefix)
                if len(window) < self.hash.HASH_BLOCK_SIZE:
                    found_index = -1
                    if windows_hash in delta_1_hash_dict:
                        if isinstance(delta_1_hash_dict[windows_hash], tuple):
                            if self.hash.get_byte_strong_hash(window) == delta_1_hash_dict[windows_hash][0]:
                                found_index = delta_1_hash_dict[windows_hash][1]
                        else:
                            for elem in delta_1_hash_dict[windows_hash]:
                                if self.hash.get_byte_strong_hash(window) == elem[0]:
                                    found_index = delta_1_hash_dict[windows_hash][1]
                                    break
                    if found_index != -1:
                        delta_2_list.append(found_index)
                    else:
                        delta_2_list.append(window)
                else:
                    delta_2_list.append(window)

            self.send_fixed_string_size(self.ReturnCode.SUCCESS)
            return delta_2_list
        except IOError:
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
            return self.ReturnCode.FAILURE

    def create_dict(self, weak, strong):
        """
        Creates the dictionary for delta_1 transaction.
        Matches weak hash keys with (strong hash, index in the file) pair
        """
        hash_dict = {}
        index = 0
        for x in zip(weak, strong):
            weak, strong = x
            if weak in hash_dict:
                if isinstance(hash_dict[weak], tuple):
                    hash_dict[weak] = [hash_dict[weak], (strong, index)]
                else:
                    hash_dict[weak].append((strong, index))
            else:
                hash_dict[weak] = (strong, index)
            index = index + 1
        return hash_dict

    # ____________

    def send_all_data(self, event_list, fm):
        """
        Send all the modification data happening on this host
        """
        if event_list:
            self.send_fixed_string_size(self.ReturnCode.SUCCESS)
            self.receive_fixed_string_size()
            self.send_object(event_list)

            for event in event_list:
                if event[3] == events.EVENT_TYPE_CREATED:
                    if event[2]:
                        pass
                    else:
                        self.transaction_send_created(event, fm)
                elif event[3] == events.EVENT_TYPE_MOVED:
                    self.transaction_send_move(event, fm)
                elif event[3] == events.EVENT_TYPE_MODIFIED:
                    self.transaction_send_modified(event, fm)

        else:
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
        fm.clear_exceptions()

    def receive_all_data(self, fm):
        """
        Receive all the modification data happening on the remote host
        """

        fm.clear_exceptions()
        if self.receive_fixed_string_size() == self.ReturnCode.SUCCESS:
            self.send_fixed_string_size()
            event_list = self.receive_object()

            for event in event_list:
                if event[3] == events.EVENT_TYPE_CREATED:
                    if event[2]:
                        self.transaction_created_folders(event, fm)
                    else:
                        self.transaction_receive_created(event, fm)
                elif event[3] == events.EVENT_TYPE_MOVED:
                    self.transaction_receive_move(event, fm)
                elif event[3] == events.EVENT_TYPE_MODIFIED:
                    self.transaction_receive_modified(event, fm)
                elif event[3] == events.EVENT_TYPE_DELETED:
                    self.transaction_remove(event, fm)

    # ____________

    def filter_queue(self, event_queue, fm):
        """
        Removes duplicate events from the queue and matches files to the corresponding event.
        Fixes modify events that appear as move events in case of buffer writes
        """

        event_dict = {}
        size = event_queue.qsize()
        for j in range(0, size):
            event_data = event_queue.get()
            e_type = event_data.event_type
            src = event_data.src_path.split(self.shared_folder, 1)[1]
            is_dir = event_data.is_directory

            # move event
            if hasattr(event_data, "dest_path"):
                dest = event_data.dest_path.split(self.shared_folder, 1)[1]
            # create, modify, delete events
            else:
                dest = None

            # create a single event type for each file
            if e_type == events.EVENT_TYPE_DELETED:
                event_dict[(src, None, is_dir, e_type)] = e_type
            elif e_type == events.EVENT_TYPE_CREATED:
                event_dict[(src, None, is_dir, e_type)] = e_type
            elif e_type == events.EVENT_TYPE_MOVED:
                # modified event, destination file is important
                if src not in fm.local_rel_paths and dest in fm.local_rel_paths:
                    event_dict[(dest, None, is_dir, events.EVENT_TYPE_MODIFIED)] = events.EVENT_TYPE_MODIFIED
                # move event, both source and destination are important
                else:
                    event_dict[(src, dest, is_dir, e_type)] = events.EVENT_TYPE_MOVED
                    # if the src file had a modify event, carry it on to dest to preserve it
                    if (src, None, is_dir, events.EVENT_TYPE_MODIFIED) in event_dict:
                        event_dict[(dest, None, is_dir, events.EVENT_TYPE_MODIFIED)] = events.EVENT_TYPE_MODIFIED
            elif e_type == events.EVENT_TYPE_MODIFIED:
                event_dict[(src, dest, is_dir, e_type)] = e_type

        # updates local files monitored and creates result event list
        event_list = []
        for elem in event_dict.keys():
            if elem in fm.files_just_received:
                fm.files_just_received.remove(elem)
                continue

            if event_dict[elem] == events.EVENT_TYPE_CREATED:
                if elem[2]:
                    event_list.append(elem)
                    fm.local_rel_paths.append(elem[0])
                else:
                    fm.local_rel_paths.append(elem[0])
                    event_list.append(elem)
            elif event_dict[elem] == events.EVENT_TYPE_DELETED:
                if elem[0] in fm.local_rel_paths:
                    fm.local_rel_paths.remove(elem[0])
                event_list.append(elem)
            elif event_dict[elem] == events.EVENT_TYPE_MOVED:
                if elem[0] in fm.local_rel_paths:
                    fm.local_rel_paths.remove(elem[0])
                fm.local_rel_paths.append(elem[1])
                event_list.append(elem)
            else:
                if elem[1] is not None and elem[0] in fm.local_rel_paths:
                    fm.local_rel_paths.remove(elem[0])
                event_list.append(elem)

        return event_list

    # ____________

    def transaction_created_folders(self, event, fm):
        """
        Create empty folders remotely
        """
        src, dest, is_dir, type = event
        path = os.path.join(self.shared_folder, src)
        print("Send create folder :", path)
        if not os.path.isdir(path):
            try:
                fm.local_rel_paths.append(src)
                fm.add_unique_exception(event)
                os.makedirs(path)
            except IOError:
                fm.local_rel_paths.remove(src)
                fm.rm_unique_exception(event)

    def transaction_send_created(self, event, fm):
        """
        Send files remotely
        """
        src, dest, is_dir, type = event
        if src:
            path = os.path.join(self.shared_folder, src)
            print("Send create file :", path)
            self.send_file(os.path.join(self.shared_folder, path))

    def transaction_receive_created(self, event, fm):
        """
        Receive files
        """
        src, dest, is_dir, type = event
        if src:
            path = os.path.join(self.shared_folder, src)
            print("Receive file :", src, path)
            try:
                fm.local_rel_paths.append(src)
                fm.add_unique_exception(event)
                if self.receive_file(path) == self.ReturnCode.FAILURE:
                    fm.local_rel_paths.remove(src)
                    fm.rm_unique_exception(event)
            except IOError:
                fm.local_rel_paths.remove(src)
                fm.rm_unique_exception(event)

    def transaction_send_modified(self, event, fm):
        """
        Send file deltas. On error send the entire file
        """
        src, dest, is_dir, type = event
        print("Send modified file :", src)
        error_code = self.send_delta2_file()
        if error_code == self.ReturnCode.FAILURE:
            print("Failed. Sending file :", src)
            self.transaction_send_created((src, None, False, events.EVENT_TYPE_CREATED), fm)

    def transaction_receive_modified(self, event, fm):
        """
        Receive file deltas and reconstruct the file. On error receive the entire file
        """
        src, dest, is_dir, type = event
        print("Receive modified file :", src)
        fm.add_unique_exception(event)
        return_code = self.reconstruct_file(src)
        if return_code == self.ReturnCode.FAILURE:
            fm.rm_unique_exception(event)
            print("Failed. Receive file :", src)
            self.transaction_receive_created((src, None, False, events.EVENT_TYPE_CREATED), fm)

    def transaction_send_move(self, event, fm):
        """
        Send move file/folder in case of move error
        """
        src, dest, is_dir, type = event
        print("Send move file/folder :", src, dest)
        if self.receive_fixed_string_size() == self.ReturnCode.FAILURE:
            self.transaction_send_created((dest, None, is_dir, events.EVENT_TYPE_CREATED), fm)

    def transaction_receive_move(self, event, fm):
        """
        Receive move file/folder from remote. Receive element on move error
        """
        src_rel, dest_rel, is_dir, type = event
        print("Receive move file/folder :", src_rel, dest_rel)
        if src_rel is None or dest_rel is None:
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
            self.transaction_receive_created((dest_rel, None, False, events.EVENT_TYPE_CREATED), fm)
            return
        try:
            src_abs = os.path.join(self.shared_folder, src_rel)
            dest_abs = os.path.join(self.shared_folder, dest_rel)
            if not os.path.exists(src_abs):
                raise IOError
            if os.path.isdir(src_abs):
                if not os.path.exists(os.path.dirname(dest_abs)):
                    os.makedirs(os.path.dirname(dest_abs))
                fm.add_unique_exception(event)
                fm.update_local_files_from_dir(src_abs, True)
                fm.update_local_files_from_dir(dest_abs, False)
                shutil.move(src_abs, dest_abs)
            else:
                if not os.path.exists(os.path.dirname(dest_abs)):
                    os.makedirs(os.path.dirname(dest_abs))
                if src_abs in fm.local_rel_paths:
                    fm.local_rel_paths.remove(src_rel)
                fm.add_unique_exception(event)
                fm.local_rel_paths.append(dest_rel)
                shutil.move(src_abs, dest_abs)
            self.send_fixed_string_size(self.ReturnCode.SUCCESS)
        except IOError:
            fm.rm_unique_exception(event)
            self.send_fixed_string_size(self.ReturnCode.FAILURE)
            self.transaction_receive_created((dest_rel, None, False, events.EVENT_TYPE_CREATED), fm)

    def transaction_remove(self, event, fm):
        """
        Remove files or folders locally
        """
        src, dest, is_dir, type = event
        path = os.path.join(self.shared_folder, src)
        print("Receive remove :", path)
        try:
            fm.add_unique_exception(event)
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            if src in fm.local_rel_paths:
                fm.local_rel_paths.remove(src)
        except IOError:
            fm.rm_unique_exception(event)
