import json
import textwrap
import unittest

from conans.cli.exit_codes import ERROR_INVALID_CONFIGURATION
from conans.client.graph.graph import BINARY_INVALID
from conans.test.assets.genconanfile import GenConanfile
from conans.test.utils.tools import TestClient


class TestValidate(unittest.TestCase):

    def test_validate_create(self):
        client = TestClient()
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            from conans.errors import ConanInvalidConfiguration
            class Pkg(ConanFile):
                settings = "os"

                def validate(self):
                    if self.settings.os == "Windows":
                        raise ConanInvalidConfiguration("Windows not supported")
            """)

        client.save({"conanfile.py": conanfile})

        client.run("create . pkg/0.1@ -s os=Linux")
        self.assertIn("pkg/0.1: Package 'cb054d0b3e1ca595dc66bc2339d40f1f8f04ab31' created",
                      client.out)

        error = client.run("create . pkg/0.1@ -s os=Windows", assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("pkg/0.1: Invalid ID: Windows not supported", client.out)
        client.run("info pkg/0.1@ -s os=Windows")
        self.assertIn("ID: INVALID", client.out)
        client.run("info pkg/0.1@ -s os=Windows --json=myjson")
        myjson = json.loads(client.load("myjson"))
        self.assertEqual(myjson[0]["binary"], BINARY_INVALID)
        self.assertEqual(myjson[0]["id"], 'INVALID')

    def test_validate_compatible(self):
        client = TestClient()
        conanfile = textwrap.dedent("""
            from conans import ConanFile
            from conans.errors import ConanInvalidConfiguration
            class Pkg(ConanFile):
                settings = "os"

                def validate(self):
                    if self.settings.os == "Windows":
                        raise ConanInvalidConfiguration("Windows not supported")

                def package_id(self):
                    if self.settings.os == "Windows":
                        compatible_pkg = self.info.clone()
                        compatible_pkg.settings.os = "Linux"
                        self.compatible_packages.append(compatible_pkg)
            """)

        client.save({"conanfile.py": conanfile})

        client.run("create . pkg/0.1@ -s os=Linux")
        self.assertIn("pkg/0.1: Package 'cb054d0b3e1ca595dc66bc2339d40f1f8f04ab31' created",
                      client.out)

        client.run("create . pkg/0.1@ -s os=Windows")
        self.assertIn("pkg/0.1: Main binary package 'INVALID' missing. "
                      "Using compatible package 'cb054d0b3e1ca595dc66bc2339d40f1f8f04ab31'",
                      client.out)
        self.assertIn("pkg/0.1:cb054d0b3e1ca595dc66bc2339d40f1f8f04ab31 - Cache", client.out)
        client.run("info pkg/0.1@ -s os=Windows")
        self.assertIn("pkg/0.1: Main binary package 'INVALID' missing. "
                      "Using compatible package 'cb054d0b3e1ca595dc66bc2339d40f1f8f04ab31'",
                      client.out)
        self.assertIn("ID: cb054d0b3e1ca595dc66bc2339d40f1f8f04ab31", client.out)

    def test_validate_compatible_also_invalid(self):
        client = TestClient()
        conanfile = textwrap.dedent("""
           from conans import ConanFile
           from conans.errors import ConanInvalidConfiguration
           class Pkg(ConanFile):
               settings = "os", "build_type"

               def validate(self):
                   if self.settings.os == "Windows":
                       raise ConanInvalidConfiguration("Windows not supported")

               def package_id(self):
                   if self.settings.build_type == "Debug" and self.settings.os != "Windows":
                       compatible_pkg = self.info.clone()
                       compatible_pkg.settings.build_type = "Release"
                       self.compatible_packages.append(compatible_pkg)
               """)

        client.save({"conanfile.py": conanfile})

        client.run("create . pkg/0.1@ -s os=Linux -s build_type=Release")
        self.assertIn("pkg/0.1: Package '24c3aa2d6c5929d53bd86b31e020c55d96b265c7' created",
                      client.out)
        # compatible_packges fallback works
        client.run("install pkg/0.1@ -s os=Linux -s build_type=Debug")
        self.assertIn("pkg/0.1:24c3aa2d6c5929d53bd86b31e020c55d96b265c7 - Cache", client.out)

        error = client.run("create . pkg/0.1@ -s os=Windows -s build_type=Release",
                           assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("pkg/0.1: Invalid ID: Windows not supported", client.out)

        client.run("info pkg/0.1@ -s os=Windows")
        self.assertIn("ID: INVALID", client.out)

    def test_validate_compatible_also_invalid_fail(self):
        client = TestClient()
        conanfile = textwrap.dedent("""
           from conans import ConanFile
           from conans.errors import ConanInvalidConfiguration
           class Pkg(ConanFile):
               settings = "os", "build_type"

               def validate(self):
                   if self.settings.os == "Windows":
                       raise ConanInvalidConfiguration("Windows not supported")

               def package_id(self):
                   if self.settings.build_type == "Debug":
                       compatible_pkg = self.info.clone()
                       compatible_pkg.settings.build_type = "Release"
                       self.compatible_packages.append(compatible_pkg)
               """)

        client.save({"conanfile.py": conanfile})

        client.run("create . pkg/0.1@ -s os=Linux -s build_type=Release")
        self.assertIn("pkg/0.1: Package '24c3aa2d6c5929d53bd86b31e020c55d96b265c7' created",
                      client.out)
        # compatible_packges fallback works
        client.run("install pkg/0.1@ -s os=Linux -s build_type=Debug")
        self.assertIn("pkg/0.1:24c3aa2d6c5929d53bd86b31e020c55d96b265c7 - Cache", client.out)

        # Windows invalid configuration
        error = client.run("create . pkg/0.1@ -s os=Windows -s build_type=Release",
                           assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("pkg/0.1: Invalid ID: Windows not supported", client.out)

        error = client.run("install pkg/0.1@ -s os=Windows -s build_type=Release",
                           assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("pkg/0.1: Invalid ID: Windows not supported", client.out)

        # Windows missing binary: INVALID
        error = client.run("install pkg/0.1@ -s os=Windows -s build_type=Debug",
                           assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("pkg/0.1: Invalid ID: Windows not supported", client.out)

        error = client.run("create . pkg/0.1@ -s os=Windows -s build_type=Debug",
                           assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("pkg/0.1: Invalid ID: Windows not supported", client.out)

        # info
        client.run("info pkg/0.1@ -s os=Windows")
        self.assertIn("ID: INVALID", client.out)
        client.run("info pkg/0.1@ -s os=Windows -s build_type=Debug")
        self.assertIn("ID: INVALID", client.out)

    def test_validate_options(self):
        client = TestClient()
        client.save({"conanfile.py": GenConanfile().with_option("myoption", [1, 2, 3])
                                                   .with_default_option("myoption", 1)})
        client.run("create . dep/0.1@")
        client.run("create . dep/0.1@ -o dep:myoption=2")
        conanfile = textwrap.dedent("""
           from conans import ConanFile
           from conans.errors import ConanInvalidConfiguration
           class Pkg(ConanFile):
               requires = "dep/0.1"

               def validate(self):
                   if self.options["dep"].myoption == 2:
                       raise ConanInvalidConfiguration("Option 2 of 'dep' not supported")
           """)

        client.save({"conanfile.py": conanfile})
        client.run("create . pkg1/0.1@ -o dep:myoption=1")

        client.save({"conanfile.py": GenConanfile().with_requires("dep/0.1")
                                                   .with_default_option("dep:myoption", 2)})
        client.run("create . pkg2/0.1@")

        client.save({"conanfile.py": GenConanfile().with_requires("pkg1/0.1", "pkg2/0.1")})
        error = client.run("install .", assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("pkg1/0.1: Invalid ID: Option 2 of 'dep' not supported", client.out)

    def test_validate_requires(self):
        client = TestClient()
        client.save({"conanfile.py": GenConanfile()})
        client.run("create . dep/0.1@")
        client.run("create . dep/0.2@")
        conanfile = textwrap.dedent("""
           from conans import ConanFile
           from conans.errors import ConanInvalidConfiguration
           class Pkg(ConanFile):
               requires = "dep/0.1"

               def validate(self):
                   # FIXME: This is a ugly interface DO NOT MAKE IT PUBLIC
                   # if self.info.requires["dep"].full_version ==
                   if self.requires["dep"].ref.version > "0.1":
                       raise ConanInvalidConfiguration("dep> 0.1 is not supported")
           """)

        client.save({"conanfile.py": conanfile})
        client.run("create . pkg1/0.1@")

        client.save({"conanfile.py": GenConanfile().with_requires("pkg1/0.1", "dep/0.2")})
        error = client.run("install .", assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("pkg1/0.1: Invalid ID: dep> 0.1 is not supported", client.out)

    def test_validate_package_id_mode(self):
        client = TestClient()
        client.run("config set general.default_package_id_mode=full_package_mode")
        conanfile = textwrap.dedent("""
          from conans import ConanFile
          from conans.errors import ConanInvalidConfiguration
          class Pkg(ConanFile):
              settings = "os"

              def validate(self):
                  if self.settings.os == "Windows":
                      raise ConanInvalidConfiguration("Windows not supported")
              """)
        client.save({"conanfile.py": conanfile})
        client.run("export . dep/0.1@")

        client.save({"conanfile.py": GenConanfile().with_requires("dep/0.1")})
        error = client.run("create . pkg/0.1@ -s os=Windows", assert_error=True)
        self.assertEqual(error, ERROR_INVALID_CONFIGURATION)
        self.assertIn("dep/0.1:INVALID - Invalid", client.out)
        self.assertIn("pkg/0.1:INVALID - Invalid", client.out)
        self.assertIn("ERROR: There are invalid packages (packages that cannot "
                      "exist for this configuration):", client.out)
        self.assertIn("dep/0.1: Invalid ID: Windows not supported", client.out)
        self.assertIn("pkg/0.1: Invalid ID: Invalid transitive dependencies", client.out)
