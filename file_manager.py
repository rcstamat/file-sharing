import os.path


class FileManager:
    def __init__(self, shared_folder=""):
        self.shared_folder = shared_folder
        self.local_abs_paths = []
        self.local_rel_paths = []
        self.local_empty_folder = []
        self.remote_empty_folders = []
        self.remote_rel_paths = []
        self.matched = []
        self.local_only = []
        self.remote_only = []
        self.files_just_received = []

        self.get_local_files()

    def get_local_files(self):
        if self.shared_folder and os.path.isdir(self.shared_folder):
            for root, dirs, files in os.walk(self.shared_folder):
                for name in files:
                    abs_path = os.path.join(os.path.abspath(root), name)
                    rel_path = abs_path.split(self.shared_folder, 1)[1]
                    self.local_abs_paths.append(abs_path)
                    self.local_rel_paths.append(rel_path)
                for directory in dirs:
                    directory_path = os.path.join(os.path.abspath(root), directory)
                    if len(os.listdir(directory_path)) == 0:
                        self.local_empty_folder.append(directory_path.split(self.shared_folder, 1)[1])

    def update_local_files_from_dir(self, dir_path, files_needed=True):
        if os.path.isdir(dir_path):
            for root, dirs, files in os.walk(self.shared_folder):
                for name in files:
                    rel_path = os.path.join(os.path.abspath(root), name).split(self.shared_folder, 1)[1]
                    try:
                        if rel_path not in self.local_rel_paths:
                            if files_needed:
                                self.local_rel_paths.append(rel_path)

                            else:
                                self.local_rel_paths.remove(rel_path)
                    except ValueError:
                        pass

    def calc_matched_files(self):
        self.matched = list(set(self.local_rel_paths) & set(self.remote_rel_paths))
        self.local_only = list(set(self.local_rel_paths) - set(self.remote_rel_paths))
        self.remote_only = list(set(self.remote_rel_paths) - set(self.local_rel_paths))

    def list_to_event(self, input_list, event_type, is_folder=False):
        event_list = []
        for x in input_list:
            event_list.append((x, None, is_folder, event_type))
        return event_list

    def add_unique_exception(self, elem):
        if elem not in self.files_just_received:
            self.files_just_received.append(elem)

    def rm_unique_exception(self, elem):
        if elem in self.files_just_received:
            self.files_just_received.remove(elem)

    def clear_exceptions(self):
        if self.files_just_received:
            self.files_just_received = []