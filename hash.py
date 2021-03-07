import hashlib
from array import array
import numpy as np


class Hash:
    HASH_BLOCK_SIZE = 256

    def get_file_bytes(self, filename):
        '''
        Convert given filename into bytearray
        '''
        bytes_list = []
        with open(filename, "rb") as f:
            file_bytes = f.read(self.HASH_BLOCK_SIZE)
            while file_bytes != b"":
                bytes_list.append(file_bytes)
                file_bytes = f.read(self.HASH_BLOCK_SIZE)
        return bytes_list

    def get_file_checksum(self, filename):
        '''
        Calculate file checksum
        '''
        with open(filename, "rb") as f:
            file_hash = hashlib.sha1()
            chunk = f.read(8192)
            while chunk:
                file_hash.update(chunk)
                chunk = f.read(8192)
        return file_hash.hexdigest()

    def get_file_hashes(self, filename):

        weak_list = array("I")
        strong_list = []

        with open(filename, "rb") as f:
            file_bytes = f.read(self.HASH_BLOCK_SIZE)
            while file_bytes != b"":
                weak_list.append(self.get_byte_weak_hash(file_bytes))
                strong_list.append(self.get_byte_strong_hash(file_bytes))
                file_bytes = f.read(self.HASH_BLOCK_SIZE)
        return weak_list, strong_list

    def get_byte_strong_hash(self, file_bytes):
        '''
        Calculate strong hash for given bytes
        '''
        return hashlib.sha1(file_bytes).hexdigest()

    def get_byte_weak_hash(self, file_bytes):
        '''
        Calculate weak hash for given bytes
        '''
        return np.sum(np.multiply(5, list(bytes(file_bytes))))