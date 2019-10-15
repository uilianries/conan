import os
import unittest

from conans.client.store.localdb import LocalDB
from conans.test.utils.test_files import temp_folder


class LocalStoreTest(unittest.TestCase):

    def localdb_test(self):
        tmp_dir = temp_folder()
        db_file = os.path.join(tmp_dir, "dbfile")
        localdb = LocalDB.create(db_file)

        # Test write and read login
        user, token, access_token = localdb.get_login("myurl1")
        self.assertIsNone(user)
        self.assertIsNone(token)
        self.assertIsNone(access_token)

        localdb.store("pepe", "token", "access_token", "myurl1")
        user, token, access_token = localdb.get_login("myurl1")
        self.assertEqual("pepe", user)
        self.assertEqual("token", token)
        self.assertEqual("access_token", access_token)
        self.assertEqual("pepe", localdb.get_username("myurl1"))
