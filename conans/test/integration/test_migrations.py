import json
import os
import textwrap
import unittest

from io import StringIO

from conans import __version__
from conans.client.cache.editable import EDITABLE_PACKAGES_FILE
from conans.client.migrations import migrate_plugins_to_hooks, migrate_to_default_profile, \
    migrate_editables_use_conanfile_name
from conans.client.output import ConanOutput
from conans.client.tools.version import Version
from conans.migrations import CONAN_VERSION
from conans.model.ref import ConanFileReference, PackageReference
from conans.paths import EXPORT_TGZ_NAME, EXPORT_SOURCES_TGZ_NAME, PACKAGE_TGZ_NAME
from conans.test.utils.test_files import temp_folder
from conans.test.utils.tools import TestClient, GenConanfile, NO_SETTINGS_PACKAGE_ID
from conans.util.files import load, save
from conans.client import migrations_settings
from conans.client.conf import get_default_settings_yml


class TestMigrations(unittest.TestCase):

    def test_migrations_matches_config(self):
        # Check that the current settings matches what is stored in the migrations file
        current_settings = get_default_settings_yml()
        v = Version(__version__)
        var_name = "settings_{}".format("_".join([v.major, v.minor, v.patch]))

        self.assertTrue(hasattr(migrations_settings, var_name),
                        "Migrations var '{}' not found".format(var_name))
        migrations_settings_content = getattr(migrations_settings, var_name)
        self.assertListEqual(current_settings.splitlines(), migrations_settings_content.splitlines())

    def test_migrate_config_install(self):
        client = TestClient()
        client.run('config set general.config_install="url, http:/fake.url, None, None"')
        version_file = os.path.join(client.cache_folder, CONAN_VERSION)
        save(version_file, "1.12.0")
        client.run("search")
        self.assertEqual(load(version_file), __version__)
        conf = load(client.cache.conan_conf_path)
        self.assertNotIn("http:/fake.url", conf)
        self.assertNotIn("config_install", conf)
        self.assertIn("http:/fake.url", load(client.cache.config_install_file))

    def test_migration_to_default_profile(self):
        tmp = temp_folder()
        old_conf = """
[general]
the old general

[settings_defaults]
some settings

[other_section]

with other values

"""
        conf_path = os.path.join(tmp, "conan.conf")
        default_profile_path = os.path.join(tmp, "conan_default")
        save(conf_path, old_conf)

        migrate_to_default_profile(conf_path, default_profile_path)

        new_content = load(conf_path)
        self.assertEqual(new_content, """
[general]
the old general

[other_section]

with other values

""")

        default_profile = load(default_profile_path)
        self.assertEqual(default_profile, """[settings]
some settings""")

        old_conf = """
[general]
the old general

[settings_defaults]
some settings

"""
        conf_path = os.path.join(tmp, "conan.conf")
        default_profile_path = os.path.join(tmp, "conan_default")
        save(conf_path, old_conf)

        migrate_to_default_profile(conf_path, default_profile_path)
        default_profile = load(default_profile_path)
        self.assertEqual(default_profile, """[settings]
some settings""")

        new_content = load(conf_path)
        self.assertEqual(new_content, """
[general]
the old general

""")

    def test_migration_from_plugins_to_hooks(self):

        def _create_old_layout():
            old_user_home = temp_folder()
            old_conan_folder = old_user_home
            old_conf_path = os.path.join(old_conan_folder, "conan.conf")
            old_attribute_checker_plugin = os.path.join(old_conan_folder, "plugins",
                                                        "attribute_checker.py")
            save(old_conf_path, "\n[general]\n[plugins]    # CONAN_PLUGINS\nattribute_checker")
            save(old_attribute_checker_plugin, "")
            # Do not adjust cpu_count, it is reusing a cache
            cache = TestClient(cache_folder=old_user_home, cpu_count=False).cache
            assert old_conan_folder == cache.cache_folder
            return old_user_home, old_conan_folder, old_conf_path, \
                   old_attribute_checker_plugin, cache

        output = ConanOutput(StringIO())
        _, old_cf, old_cp, old_acp, cache = _create_old_layout()
        migrate_plugins_to_hooks(cache, output=output)
        self.assertFalse(os.path.exists(old_acp))
        self.assertTrue(os.path.join(old_cf, "hooks"))
        conf_content = load(old_cp)
        self.assertNotIn("[plugins]", conf_content)
        self.assertIn("[hooks]", conf_content)

        # Test with a hook folder: Maybe there was already a hooks folder and a plugins folder
        _, old_cf, old_cp, old_acp, cache = _create_old_layout()
        existent_hook = os.path.join(old_cf, "hooks", "hook.py")
        save(existent_hook, "")
        migrate_plugins_to_hooks(cache, output=output)
        self.assertTrue(os.path.exists(old_acp))
        self.assertTrue(os.path.join(old_cf, "hooks"))
        conf_content = load(old_cp)
        self.assertNotIn("[plugins]", conf_content)
        self.assertIn("[hooks]", conf_content)

    def test_migration_editables_to_conanfile_name(self):
        # Create the old editable_packages.json file (and user workspace)
        tmp_folder = temp_folder()
        conanfile1 = os.path.join(tmp_folder, 'dir1', 'conanfile.py')
        conanfile2 = os.path.join(tmp_folder, 'dir2', 'conanfile.py')
        save(conanfile1, "anything")
        save(conanfile2, "anything")
        save(os.path.join(tmp_folder, EDITABLE_PACKAGES_FILE),
             json.dumps({"name/version": {"path": os.path.dirname(conanfile1), "layout": None},
                         "other/version@user/testing": {"path": os.path.dirname(conanfile2),
                                                        "layout": "anyfile"}}))

        cache = TestClient(cache_folder=tmp_folder).cache
        migrate_editables_use_conanfile_name(cache)

        # Now we have same info and full paths
        with open(os.path.join(tmp_folder, EDITABLE_PACKAGES_FILE)) as f:
            data = json.load(f)

        self.assertEqual(data["name/version"]["path"], conanfile1)
        self.assertEqual(data["name/version"]["layout"], None)
        self.assertEqual(data["other/version@user/testing"]["path"], conanfile2)
        self.assertEqual(data["other/version@user/testing"]["layout"], "anyfile")

    def test_migration_tgz_location(self):
        client = TestClient(default_server_user=True)
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            class Pkg(ConanFile):
                exports = "*.txt"
                exports_sources = "*.h"
            """)
        client.save({"conanfile.py": conanfile,
                     "file.h": "contents",
                     "file.txt": "contents"})
        client.run("create . pkg/1.0@")
        ref = ConanFileReference.loads("pkg/1.0")
        layout = client.cache.package_layout(ref)
        export_tgz = os.path.join(layout.export(), EXPORT_TGZ_NAME)
        export_src_tgz = os.path.join(layout.export(), EXPORT_SOURCES_TGZ_NAME)
        pref = PackageReference(ref, NO_SETTINGS_PACKAGE_ID)
        pkg_tgz = os.path.join(layout.package(pref), PACKAGE_TGZ_NAME)
        save(export_tgz, "")
        save(export_src_tgz, "")
        save(pkg_tgz, "")
        self.assertTrue(os.path.isfile(export_tgz))
        self.assertTrue(os.path.isfile(export_src_tgz))
        self.assertTrue(os.path.isfile(pkg_tgz))
        save(os.path.join(client.cache_folder, "version.txt"), "1.30.0")
        client2 = TestClient(client.cache_folder)
        client2.run("-h")
        self.assertIn("Removing temporary .tgz files, they are stored in a different "
                      "location now", client2.out)
        self.assertFalse(os.path.isfile(export_tgz))
        self.assertFalse(os.path.isfile(export_src_tgz))
        self.assertFalse(os.path.isfile(pkg_tgz))
